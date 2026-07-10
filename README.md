# UA — Underwriting Agent

An AI-assisted **mortgage underwriting workbench** reference implementation for a large US national bank: a deterministic LangGraph underwriting pipeline with a mandatory human decision gate, a CopilotKit visual workbench with click-through lineage on every number, and a tamper-evident, hash-chained, replayable audit trail.

**Synthetic data only. Not a production system.** It implements the *controls* a production system needs — ECOA/Reg B adverse action with specific reasons, ATR/QM 8-factor evaluation, HMDA capture, fair-lending demographics isolation, state-law overlays with statutory citations (TX 50(a)(6), NY/MA/GA high-cost, CO/CA ADMT), GSE AI-governance patterns, and byte-exact decision replay — so the architecture transfers onto a bank's internal network.

> **The spec is the source of truth.** Everything here was built from [`specs/`](specs/00-overview.md) — an 18-document package written and independently reviewed *before* implementation. Another team (or agent) can rebuild this system from `specs/` alone.

---

## Quickstart (Windows)

**Prerequisites**

| Tool | Version | Install |
|---|---|---|
| Python | 3.12 (via `uv`) | `winget install astral-sh.uv` |
| Node.js | ≥ 20 | `winget install OpenJS.NodeJS.LTS` |
| Git | any recent | `winget install Git.Git` |

**1. Clone and configure**

```powershell
git clone https://github.com/Chunkys0up7/UA.git
cd UA
Copy-Item .env.example .env      # defaults to LLM_PROVIDER=mock — no keys needed
```

**2. Backend (Python 3.12 via uv)**

```powershell
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
cd ..
```

**3. Frontend**

```powershell
cd frontend
npm install
cd ..
```

**4. Run everything**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

This frees ports 8000/3000, starts both servers in their own windows, and opens **http://localhost:3000** — you'll land on the underwriting pipeline with 15 synthetic loan files.

**5. Verify the build (optional but recommended)**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q -k "not Corpus"   # ~180 tests, <30s
.\.venv\Scripts\python.exe -m pytest tests -q -k Corpus         # 500-loan regression, ~3 min
cd ..
powershell -ExecutionPolicy Bypass -File scripts\verify-audit.ps1   # audit chain check
```

Everything above runs with **zero API keys** — the mock provider returns each synthetic document's ground truth, and every downstream step (rules, decisions, audit, replay) is fully real.

---

## A 3-minute tour

1. Open **http://localhost:3000** → the pipeline lists 15 archetype loans (clean approvals, a Texas 50(a)(6) seasoning decline, a NY high-cost decline, fraud red flags, a counteroffer candidate…).
2. Open any loan with status **received** → click **▶ Run underwriting**. The pipeline extracts documents, re-computes income/DTI/LTV/reserves with full lineage, evaluates both rule packs, runs the AUS simulator, and stops at the **decision gate** — no loan ever decides itself.
3. On the **4 Cs** tab, click any underlined number (e.g. back-DTI) → the lineage popover walks the derivation down to the source document extraction, with confidence, prompt version, and model id.
4. On the **Decision** tab: the suggested action is *only a suggestion*. Declines force you to pick 1–4 reason codes **from the rules that actually failed** (ECOA/Reg B), plus a second reviewer. Overriding the suggestion demands a written justification — recorded forever.
5. On the **Audit** tab: the hash-chain badge, the sealed snapshot hash, and **Replay decision** — which re-runs the deterministic core from the sealed inputs and proves the outcome reproduces byte-for-byte.
6. A declined file's Decision tab shows the generated **adverse-action notice**: verbatim ECOA reason texts, the FCRA §609(g) credit-score block, and (for CO/CA properties) the state ADMT disclosure block.

Regenerate test data any time (same seed → byte-identical files):

```powershell
cd backend
.\.venv\Scripts\python.exe -m synthetic.generate --archetypes --out ..\data\loans
.\.venv\Scripts\python.exe -m synthetic.generate --corpus --count 500 --seed 1337 --out ..\data\generated
```

---

## Bring your own LLM provider

The system is **provider-agnostic by construction** (spec [10 — LLM Usage Register](specs/10-llm-usage-register.md)). Three facts make the swap safe:

- **The LLM never makes credit decisions** (hard rule HR-1). It only extracts document fields, drafts condition wording, writes display narratives, and answers chat. Eligibility comes from the deterministic policy engine; the final action comes from a human.
- **Exactly one file imports a vendor SDK** (HR-9) — enforced by an automated import-graph test (`T-LLM-3`).
- Every LLM call is audited with prompt id+version, exact model id, and content hashes, and the model ids are pinned into every decision snapshot.

### Option A — use Anthropic (wired in)

```powershell
# in .env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6        # or your approved model id
ANTHROPIC_API_KEY=sk-ant-...
```

Restart `scripts\dev.ps1`. Extraction and narratives now run live; decisions are unchanged by construction.

### Option B — plug in your own SDK

1. **Implement the protocol** in ONE new file, `backend/app/llm/ua_yourprovider.py`, satisfying `UALLMClient` from [`backend/app/llm/ua_base.py`](backend/app/llm/ua_base.py):

   ```python
   class YourProviderUALLMClient:
       async def extract(self, *, prompt, document_text, ground_truth, call_site) -> ExtractionResult: ...
       async def narrate(self, *, prompt, payload, call_site) -> TextResult: ...
       async def draft(self, *, prompt, payload, call_site) -> TextResult: ...
   ```

   Use [`ua_anthropic.py`](backend/app/llm/ua_anthropic.py) as the template — ~120 lines. Requirements: render the prompt's `template`, honor its `model_params` (temperature/max_tokens), return **bare JSON** for extraction with one retry on parse failure (FR-EXT-3), and build a `CallRecord` via `make_record(...)` for every call (that's what feeds the audit trail).

2. **Register a factory** in `LLM_PROVIDERS` in [`backend/app/agent/graph.py`](backend/app/agent/graph.py):

   ```python
   LLM_PROVIDERS = {
       "mock": MockUALLMClient,
       "anthropic": _make_anthropic,
       "yourprovider": lambda: YourProviderUALLMClient(model_id=os.environ["LLM_MODEL"]),
   }
   ```

3. **Set the env** — `LLM_PROVIDER=yourprovider`, `LLM_MODEL=<exact model id>` (it is recorded verbatim in every snapshot/audit event).

4. **Run the swap gates** (spec 10 §6):

   ```powershell
   cd backend
   .\.venv\Scripts\python.exe -m pytest tests -q -k "not Corpus"   # incl. the one-vendor-import scan
   .\.venv\Scripts\python.exe -m pytest tests -q -k Corpus         # decision distribution must be UNCHANGED
   ```

   The corpus run is the proof that matters: because the LLM never touches decisions, swapping providers must produce **zero decision-level differences** — only extraction confidence and narrative prose may vary.

What does **not** change on swap: prompts and their output schemas (`policy/prompts/`), audit event shapes, reason codes, rules, the UI, and all tests except provider-specific eval baselines.

---

## Repository map

| Path | What it is |
|---|---|
| [`specs/`](specs/00-overview.md) | **The source of truth**: 18 normative documents + JSON Schemas. Start at `00-overview.md` (hard rules), then `01-requirements.md` (traceable FR/NFR IDs) and `02-compliance-matrix.md` (regulation → control → test). |
| `specs/policy-pack/` | Machine-readable rule packs: `conforming-2026.1.0` (base guidelines) and `state-overlays-2026.1.0` (TX/NY/MA/GA/FL/CO with statutory citations), each sha256-manifested and immutable. |
| `policy/` | Runtime copy of the packs + versioned prompts (loader verifies manifests on every start). |
| `backend/app/domain/` | Pure Decimal calculations with content-addressed lineage (income, DTI, LTV, reserves, score, ATR). |
| `backend/app/policy_engine/` | The deterministic rules engine — the only component that produces eligibility outcomes. |
| `backend/app/audit/` | Hash-chained append-only ledger, canonical JSON, snapshot build + byte-exact replay. |
| `backend/app/agent/` | Case assembly, decisioning, the LangGraph pipeline with the human-gate interrupt. |
| `backend/app/llm/` | Provider boundary: `ua_base.py` (protocol + prompt registry), `ua_mock.py`, `ua_anthropic.py`. |
| `backend/synthetic/` | Seeded loan-package generator (15 golden archetypes + 500-package corpus). |
| `frontend/` | Next.js + CopilotKit workbench (pipeline, deep-dive, lineage popovers, DecisionGate, audit timeline). |
| `specs/DEVIATIONS.md` | Every deviation from spec found during implementation, with rationale (incl. the upstream CopilotKit unbound-method defect and its workaround). |

## Troubleshooting

- **Blank page at `/`** → hard-refresh; `/` redirects to `/pipeline`. If it still fails, check both server windows for errors.
- **`useAgent: Agent not found` overlay** → the backend isn't up (the frontend registers agents against `:8000`). Start it via `scripts\dev.ps1`.
- **Pack integrity error on startup** → your clone converted line endings. The repo pins `eol=lf` via `.gitattributes`; re-clone or run `git checkout -- policy specs`.
- **Port already in use** → `scripts\dev.ps1` frees 8000/3000 automatically; run it again.
- **Python 3.13 on PATH** → irrelevant; the venv pins CPython 3.12 (`uv venv --python 3.12`).

## Status

All phases complete: spec package → walking skeleton (interrupt round-trip) → domain/rules/audit → synthetic data + LLM layer → full pipeline (500-loan regression) → visual workbench (browser-verified walkthrough). ~180 tests plus the corpus regression; every decision seals a replayable snapshot.
