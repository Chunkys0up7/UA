# 03 — System Architecture

Requirements covered: FR-API-2, FR-VER-4, NFR-5. Read after `01-requirements.md`.

---

## 1. Component overview

```
┌────────────────────────────── Browser ──────────────────────────────┐
│  Next.js 14 Workbench (frontend/)                                   │
│  ├─ REST fetchers ──────────────► FastAPI /api/* (loan data, audit, │
│  │                                 lineage, decisions)              │
│  ├─ CopilotKit React (@copilotkit/react-core, react-ui)             │
│  │   ├─ chat ► /api/copilotkit (Next route: CopilotRuntime)         │
│  │   └─ agent (HttpAgent) ► FastAPI /agent/underwriter (AG-UI SSE)  │
└──────────────────────────────────────────────────────────────────────┘
                                   │
┌───────────────────────── backend/ (Python 3.12) ─────────────────────┐
│ FastAPI app                                                          │
│  ├─ api/            REST routers (loans, audit, lineage, decisions)  │
│  ├─ runtime.py      ← ONLY file importing copilotkit + ag_ui SDKs    │
│  ├─ agent/          LangGraph graph + nodes + chat tools             │
│  ├─ domain/         pure models, lineage, calculations, ATR (no IO)  │
│  ├─ policy_engine/  deterministic JSON rules evaluator               │
│  ├─ aus/            deterministic DU-style simulator                 │
│  ├─ adapters/       simulated integrations (bureau, VOE, flood, OFAC)│
│  ├─ llm/            LLMClient protocol; anthropic_client, mock_client│
│  ├─ audit/          hash-chained ledger, verify, snapshot/replay     │
│  ├─ persistence/    SQLAlchemy 2.0 (async) repositories              │
│  └─ hmda/           action-taken machine; demographics (ISOLATED)    │
│                                                                      │
│ Storage (SQLite, WAL mode):                                          │
│  data/db/loans.db        – applications, analysis, decisions         │
│  data/db/audit.db        – append-only audit_events (+ snapshots)    │
│  data/db/checkpoints.db  – LangGraph AsyncSqliteSaver                │
└──────────────────────────────────────────────────────────────────────┘
```

Two processes in dev: `uvicorn` (port **8000**) and `next dev` (port **3000**). One shared `.env` at repo root (see §7).

## 2. Layering rules (enforced by tests and review)

1. `domain/` is pure: no IO, no clock, no randomness, no imports from any other app layer (T-CAL-8).
2. `policy_engine/`, `aus/` depend only on `domain/`.
3. `agent/nodes/*` orchestrate: load via repositories → call domain/policy/aus/llm → persist → append audit events → update graph state.
4. `runtime.py` is the **only** module importing `copilotkit` or `ag_ui_langgraph` (isolates SDK churn).
5. `llm/anthropic_client.py` is the **only** module importing `anthropic` (HR-9).
6. Nothing outside `hmda/` imports `hmda/demographics` (HR-6, T-ISO-1).

## 3. Technology matrix (pinned)

| Layer | Package | Version constraint | Notes |
|---|---|---|---|
| Python | CPython | `>=3.12,<3.13` via `uv` | copilotkit PyPI had 3.13 wheel issues; 3.12 is the verified lane |
| API | fastapi | `>=0.115,<1` | |
| Server | uvicorn[standard] | `>=0.32,<1` | |
| Agent | langgraph | `>=0.4,<1` | interrupts + checkpointing |
| Checkpoint | langgraph-checkpoint-sqlite | `>=2,<3` | `AsyncSqliteSaver` |
| CopilotKit (py) | copilotkit | `>=0.1.88,<0.2` | see §5 for known-defect workaround |
| AG-UI bridge | ag-ui-langgraph | `>=0.0.7` | direct agent mount |
| LLM | anthropic | `>=0.42,<1` | behind LLMClient only |
| Models/validation | pydantic | `>=2.11,<3` | copilotkit needs pydantic-core ≥2.35 |
| ORM | sqlalchemy + aiosqlite | `>=2.0,<3` / `>=0.20,<1` | async engine |
| Logging | structlog | `>=25,<26` | PII masking processor |
| Frontend | next / react / typescript | `14.2.x` / `18.x` / `5.7.x` | App Router |
| CopilotKit (js) | @copilotkit/react-core, react-ui, runtime | `^1.10.0` | resolves ~1.5x line |
| Agent client | @ag-ui/client | latest compatible | `HttpAgent` |
| UI kit | tailwindcss + shadcn/ui | 3.x | |
| Lint | eslint 8.x, ruff, mypy | | eslint 9 breaks next 14 config |

Lockfiles (`package-lock.json`, `uv.lock`) are committed and authoritative.

## 4. Request/data flows

### 4.1 Underwriting run
1. `POST /loans` — package validated against `schemas/loan-package.schema.json`, persisted, `application_id` (ULID) returned; policy pack version pinned; audit `state_change: received`.
2. `POST /loans/{id}/run` (or chat: "underwrite this loan") — starts the LangGraph run with `thread_id = application_id`. Nodes execute per `09-agent-graph.md`, streaming `progress` state deltas over AG-UI SSE.
3. Graph reaches `prepare_decision` → `interrupt(decision_packet)`. Run pauses; checkpoint persisted; UI renders the DecisionGate.
4. Underwriter submits the resume payload → validated → graph resumes → finalize (+ adverse action on decline) → `audit_seal` → END.

### 4.2 Lineage drill-down
UI number click → `GET /lineage/{ref}` → lineage node + transitive parents (calculation ← extracted fields ← document). Pure read.

### 4.3 Chat
Sidebar message → Next `/api/copilotkit` (CopilotRuntime) → agent via AG-UI → LangGraph chat path with the seven read-only tools defined in `09 §7` (`get_loan_summary`, `get_dti_breakdown`, `get_rule_result`, `get_open_conditions`, `get_red_flags`, `explain_lineage`, `draft_condition_text`) → grounded answer. All tool calls audited.

## 5. CopilotKit ⇄ LangGraph wiring (CRITICAL — encodes known-defect workarounds)

**Known defect:** `copilotkit` PyPI 0.1.88's `LangGraphAGUIAgent` bridge is broken (`dict_repr`/`execute` errors). **Do not use it.** Use the **two-endpoint pattern**:

**Backend (`runtime.py`):**
```python
# Endpoint A: CopilotKit remote endpoint (actions; agents list EMPTY)
from copilotkit import CopilotKitRemoteEndpoint
from copilotkit.integrations.fastapi import add_fastapi_endpoint
sdk = CopilotKitRemoteEndpoint(actions=[...], agents=[])
add_fastapi_endpoint(app, sdk, "/copilotkit_remote")

# Endpoint B: direct AG-UI mount of the LangGraph agent
from ag_ui_langgraph import LangGraphAgent, add_langgraph_fastapi_endpoint
agent = LangGraphAgent(name="underwriter", graph=build_underwriting_graph(checkpointer))
add_langgraph_fastapi_endpoint(app, agent, "/agent/underwriter")
```

**Frontend:**
- `app/api/copilotkit/route.ts`: `CopilotRuntime({ remoteEndpoints: [{ url: `${BACKEND_URL}/copilotkit_remote` }] })` with `ExperimentalEmptyAdapter` (agent-lock mode; the Python side owns the LLM).
- `components/CopilotProvider.tsx`: register the agent directly:
```tsx
const agent = useMemo(() => new HttpAgent({ url: `${NEXT_PUBLIC_BACKEND_URL}/agent/underwriter` }), []);
<CopilotKit runtimeUrl="/api/copilotkit" agents__unsafe_dev_only={{ underwriter: agent }} agent="underwriter">
```
(memoize the HttpAgent — re-creating it per render breaks SSE resumption).

**Interrupts:** `useLangGraphInterrupt({ render })` on the deep-dive page renders the DecisionGate from the interrupt event and resolves with the resume payload. **Fallback** (if the hook misbehaves against the ag-ui mount): a `useCopilotAction` with `renderAndWaitForResponse` wired to the identical resume schema — swapping is one component (`schemas/interrupt-resume.schema.json` is shared).

**Phase-0 gate (16 §4):** this wiring, with a trivial 3-node graph, MUST round-trip an interrupt in the browser before any domain code is built.

## 6. Adapter interfaces (simulated integrations)

All external-world calls go through `adapters/base.py` Protocols so real vendors can replace sims on the internal network without touching callers:

| Protocol | Sim implementation | Emits (audited) |
|---|---|---|
| `CreditBureauAdapter.pull(application_id) -> TriMergeReport` | reads package credit section | `adapter_call` event w/ `permissible_purpose="credit_transaction"` |
| `EmploymentVerifier.verify(borrower) -> VoeResult` | derives from package employment + archetype flags | `adapter_call` w/ verified/failed/unavailable |
| `FloodZoneService.lookup(property) -> FloodResult` | from package property sidecar | zone + SFHA flag |
| `OfacScreen.screen(parties) -> OfacResult` | name-list sim (always clear except archetype) | hit ⇒ pipeline suspends (FR-VER-5) |
| `GeoDistanceAdapter.distance(property, employment) -> DistanceResult` | reads `employment[].distance_to_property_miles_sidecar` from package | miles; feeds RF-OCC-DISTANCE (`06 §9`) |

Every adapter result carries `adapter_name`, `adapter_version`, and is persisted + audited (FR-VER-4).

## 7. Configuration & environments

Single root `.env` (template `.env.example`), loaded by both processes:

```
LLM_PROVIDER=mock            # mock | anthropic
ANTHROPIC_API_KEY=           # required only when LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6  # exact model id, logged per call
BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
DATABASE_DIR=./data/db
POLICY_PACK=conforming-2026.1.0
FOUR_EYES_THRESHOLD=1000000
CODE_GIT_SHA=                # stamped by scripts/dev.ps1 (git rev-parse HEAD)
```

Profiles: **default** = SQLite + mock LLM (no keys, no Docker — NFR-5); **live-llm** = `LLM_PROVIDER=anthropic`; **postgres** (optional) = docker-compose Postgres 16 with equivalent DDL (11 §2 documents both dialects).

## 8. AI inventory (GSE mandate artifact)

Maintained in `ARCHITECTURE.md` of the repo root, seeded with:

| Component | Type | Version source | Scope | Decision authority |
|---|---|---|---|---|
| Policy engine + pack | deterministic rules | pack semver + sha256 manifest | eligibility outcomes | **decides eligibility, human finalizes** |
| AUS simulator | deterministic scorer | `du-sim.v1.json` | advisory recommendation | none (advisory) |
| LLM (Anthropic, swappable) | generative | prompt id+version, model id per call | extraction, narrative, condition drafting, chat | **none — never decides (HR-1)** |
| Fraud screen | deterministic rules | pack version | red flags | none (informs human) |
