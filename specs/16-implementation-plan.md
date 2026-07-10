# 16 — Implementation Plan, Environment & Risk Register

The build order below is normative: **each phase has an exit gate; do not start the next phase until the gate passes.** Phase 0's gate exists because the CopilotKit⇄LangGraph wiring is the highest-risk integration — prove it before writing domain code.

---

## 1. Environment

| Tool | Version | Install |
|---|---|---|
| Python | 3.12.x | `uv python install 3.12` then `uv venv --python 3.12` in `backend/` |
| uv | latest | `winget install astral-sh.uv` (or pipx) |
| Node | ≥ 20 (22 verified) | nvm-windows / winget |
| npm | bundled | lockfile committed |
| Docker | optional | only for the Postgres profile |

Dependency pins: `03 §3` matrix. Verify at bootstrap: `pip index`/`npm view` the pinned ranges still resolve; record actual resolved versions in the lockfiles (authoritative).

## 2. Repository layout (target)

```
UA/
├── README.md · ARCHITECTURE.md · COMPLIANCE.md · CHANGELOG.md · .env.example · .gitignore
├── specs/                          # this package (immutable during build except DEVIATIONS.md)
├── policy/
│   ├── packs/conforming-2026.1.0/  # verbatim copy of specs/policy-pack/conforming-2026.1.0
│   ├── prompts/                    # verbatim copy of specs/prompts
│   └── aus/du-sim.v1.json          # verbatim copy of specs/policy-pack/aus/du-sim.v1.json
├── backend/
│   ├── pyproject.toml · requirements.txt · uv.lock
│   ├── app/
│   │   ├── main.py · config.py · logging_config.py · runtime.py
│   │   ├── api/{loans,audit,lineage,decisions,hmda}.py
│   │   ├── domain/{models,lineage,atr}.py · domain/calculations/{income,dti,ltv,reserves,score}.py
│   │   ├── policy_engine/{engine,ast,loader,result}.py
│   │   ├── aus/du_simulator.py
│   │   ├── adapters/{base,sim_credit_bureau,sim_verifications,sim_flood,sim_ofac}.py
│   │   ├── llm/{base,anthropic_client,mock_client,prompt_registry}.py
│   │   ├── agent/{state,graph,chat_tools}.py · agent/nodes/*.py
│   │   ├── audit/{ledger,canonical,verify,snapshot}.py
│   │   ├── persistence/{database,tables,repositories}.py
│   │   └── hmda/{action_taken,demographics}.py
│   ├── synthetic/{generate,archetypes,renderers,boundary}.py
│   └── tests/ (per 15) + tests/golden/
├── frontend/
│   ├── package.json · tsconfig.json · next.config.js · tailwind.config.ts
│   ├── app/{layout,page}.tsx · app/pipeline/page.tsx · app/loans/[id]/page.tsx · app/api/copilotkit/route.ts
│   ├── components/CopilotProvider.tsx
│   ├── components/workbench/{PipelineTable,AppSummaryCard,FourCsPanel,TracedNumber,LineagePopover,AtrChecklist,RulesTable,AusFindingsCard,ConditionsBoard,RedFlagsPanel,AdverseActionPreview,AuditTimeline,NarrativeCard}.tsx
│   ├── components/copilot/{AgentProgress,StageStepper,DecisionGate,DecisionForm}.tsx
│   ├── lib/{api,agent-state,format}.ts
│   └── __tests__/
├── scripts/{dev.ps1,seed.ps1,verify-audit.ps1,generate-corpus.ps1,xref-lint.py}
├── docs/demo-script.md
└── data/{loans/ (committed goldens), generated/ (gitignored), db/ (gitignored)}
```

`policy/` is a build-time copy of `specs/` artifacts (copy script in `seed.ps1`); the loader verifies the manifest either place — the copy exists so the runtime never reads from `specs/`.

## 3. Phases & gates

### Phase 0 — Walking skeleton ⚠ GATE FIRST
Scaffold Next.js + FastAPI + CopilotKit exactly per `03 §5` (two-endpoint pattern; **do not** use `LangGraphAGUIAgent` from copilotkit PyPI). Trivial 3-node graph: `hello → interrupt("confirm?") → done`, SQLite checkpointer. Frontend: provider + `useLangGraphInterrupt` stub button.
**Gate (T-P0-1, T-ENV-1):** in a browser — run agent, interrupt renders, resume completes; `LLM_PROVIDER=mock` with no keys; sanity curls: `GET :8000/healthz`, `GET :8000/copilotkit_remote/info`, `POST :3000/api/copilotkit` (GraphQL ping), SSE headers on `/agent/underwriter`.
If `useLangGraphInterrupt` fails against the ag-ui mount: switch to the pre-specified `renderAndWaitForResponse` fallback (`13 §6`) and record in DEVIATIONS.md.

### Phase 1 — Domain core
`domain/` (models, lineage, calculations, ATR) + `persistence/` + golden calc vectors.
**Gate:** T-CAL-1..8 green (goldens include every `06` worked example).

### Phase 2 — Policy engine + pack
`policy_engine/` + pack loader + `conforming-2026.1.0` copy + compensating factors.
**Gate:** T-POL-1..7 green.

### Phase 3 — Audit ledger + snapshots
`audit/` (canonical, ledger, verify, snapshot/replay) + triggers + append-only repos.
**Gate:** T-AUD-1..3, T-REP-1 (replay over hand-built snapshot fixtures until Phase 5 provides real ones — fixture-first is acceptable).

### Phase 4 — Synthetic data + adapters + LLM layer
`synthetic/` (archetypes, renderers, boundary sweep, corpus CLI) → commit the 12 goldens to `data/loans/`; adapters; `llm/` (protocol, mock, anthropic, prompt registry).
**Gate:** T-DAT-1/2 (generation + expected-outcome fixtures), T-EXT-1..3, T-LLM-1..3, T-ADP-1.

### Phase 5 — Full graph
All nodes per `09 §3`, gate/resume validation, adverse action, HMDA machine, chat tools.
**Gate:** T-TOP-1/2, T-DEC-2..6, T-AAN-1, T-HMD-1..3, T-ISO-1, T-VER-1..3, T-FRD-1/2, T-CND-1/2, T-AUS-1/2, T-STA-1, T-REP-2, T-SEC-1, T-LLM-4, and the full corpus run T-DAT-3.

### Phase 6 — Workbench UI
All components per `13`; REST endpoints per `12` (built alongside as needed from Phase 5).
**Gate:** T-API-1, T-LIN-1, demo script (`15 §2`) end-to-end.

### Phase 7 — Hardening & docs
PII masking verification, COMPLIANCE.md finalized from `02` with any DEVIATIONS, README (bootstrap, backup/retention procedure), ARCHITECTURE.md (incl. AI inventory `03 §8`), CHANGELOG, `verify-audit.ps1`, `xref-lint.py`.
**Gate:** `15 §3` acceptance gates 1–5 all green.

Commit discipline: capability-grouped commits at each gate minimum; cite requirement IDs in messages (`02 §11`).

## 4. Scripts

- `dev.ps1` — checks ports 8000/3000, stamps `CODE_GIT_SHA`, copies `specs/` artifacts → `policy/`, seeds goldens if DB empty, starts uvicorn + next dev.
- `seed.ps1` — regenerate archetypes (seed 42) + load via `POST /loans`.
- `generate-corpus.ps1` — corpus generation + regression run + report.
- `verify-audit.ps1` — chain verification CLI over `data/db/audit.db`.
- `xref-lint.py` — parses `01` IDs, asserts each appears in ≥1 other spec doc and ≥1 test id in `15`; asserts pack reason-code closure and prompt-register closure.

## 5. Risk register

| # | Risk | Mitigation (specified) |
|---|---|---|
| 1 | CopilotKit⇄LangGraph interrupt wiring breaks (known PyPI bridge defect) | Two-endpoint pattern (`03 §5`); Phase 0 gate; `renderAndWaitForResponse` fallback with identical resume schema |
| 2 | SSE state bloat degrades streaming | State = IDs + summaries only; < 32 KB assertion (T-STA-1); heavy data over REST |
| 3 | Dependency drift (`copilotkit`↔`pydantic-core`, `@copilotkit` exports) | Pinned ranges (`03 §3`) + committed lockfiles; bootstrap verification step |
| 4 | LLM nondeterminism contaminates decisions | HR-1 architecture; mock provider CI default; rules read persisted fields only (T-TOP-2); provider-swap regression must show zero decision diffs (`10 §6`) |
| 5 | Hash-chain mismatch across platforms | Single canonical-JSON implementation (`11 §4.1`); cross-platform vector in T-AUD-2 |
| 6 | Windows friction (paths, wheels) | SQLite default; uv-managed 3.12; PowerShell scripts; Docker optional |
| 7 | Spec drift during build | specs/ immutable during build; deviations only via DEVIATIONS.md with compliance-row linkage (`02 §11`) |

## 6. Performance budgets (NFR-6)

Mock-provider single run ≤ 10 s; 500-package corpus ≤ 20 min (parallelizable across worker processes as long as ledger writes remain serialized per §11 write protocol); UI stepper latency dominated by SSE — no client polling.
