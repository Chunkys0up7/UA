# 15 — Testing & Acceptance

Every test ID below is referenced from `01-requirements.md`; every FR/NFR maps to ≥ 1 test here. Framework: `pytest` + `pytest-asyncio` (backend), `vitest` (frontend utils), manual demo script (UI acceptance). **CI default: `LLM_PROVIDER=mock`** — the full suite runs with no keys and no network.

---

## 1. Test inventory

### Package & intake
- **T-PKG-1**: valid archetype packages → 201 with pinned pack version; mutated packages (bad enum, float money, missing borrower) → 422 with field-level violations; DB row count unchanged after rejection (FR-PKG-1, -4).
- **T-PKG-2**: referential-integrity fixtures (dangling doc_id, two primaries, purchase without price) → 422 naming the violation (FR-PKG-2). Appraised value flows from package only (appraisal-independence row, `02 §9`).

### Extraction & LLM governance
- **T-EXT-1**: mock-provider extraction over all 15 archetypes matches `ground_truth` exactly, field-level (golden). Live-provider variant (opt-in, `LLM_PROVIDER=anthropic`): ≥ 98% numeric-field exact match (FR-EXT-1).
- **T-EXT-2**: prompt returning schema-invalid JSON (mock injected) → one retry → `extraction_failed` + condition (FR-EXT-3).
- **T-EXT-3**: two runs of the same package (mock) produce identical extracted fields (FR-EXT-4, FR-LLM-4).
- **T-LLM-1**: register exhaustiveness — grep/AST scan: no `LLMClient` call site outside register rows; runtime rejects unregistered prompt_id; no LLM imports under `policy_engine/`, `aus/`, `domain/`, `audit/` (FR-LLM-3, HR-1).
- **T-LLM-2**: every LLM call in a run has a matching `llm_call` audit event with prompt id+version+model id+hashes (FR-LLM-2, FR-EXT-2).
- **T-LLM-3**: import-graph scan — `anthropic` imported only by `llm/anthropic_client.py` (FR-LLM-1, HR-9).
- **T-LLM-4**: chat tools are read-only — after a scripted chat session (mock planner), no decision/condition/rule/ledger mutation occurred; all tool calls audited (FR-LLM-5).

### Verification & adapters
- **T-VER-1**: tolerance-table cases: values inside tolerance → no discrepancy; outside → `Discrepancy` row with documented-value-governs semantics (FR-VER-1, -2).
- **T-VER-2**: discrepancy never mutates `package_json`; calculation lineage cites the documented value (FR-VER-3).
- **T-VER-3**: OFAC-hit fixture → run halts `suspended`, no gate, mandatory-review condition (FR-VER-5).
- **T-ADP-1**: every adapter call produces an `adapter_call` event with adapter version; bureau adapter logs permissible purpose (FR-VER-4, `02 §5`).

### Calculations (golden files: `tests/golden/calculations.json`)
- **T-CAL-1**: no float in money paths (AST lint over `domain/`); Decimal-string round-trip stability (FR-EXT-5, NFR-2).
- **T-CAL-2**: income algorithms vs goldens — every worked example in `06 §2` plus per-archetype vectors (FR-CAL-1).
- **T-CAL-3**: DTI vs goldens incl. the `06 §3` worked example exactly (FR-CAL-2).
- **T-CAL-4**: LTV/CLTV vs goldens incl. round-up behavior (FR-CAL-3).
- **T-CAL-5**: reserves vs goldens incl. retirement haircut (FR-CAL-4).
- **T-CAL-6**: representative-score derivation vs goldens (FR-CAL-5).
- **T-CAL-7**: after any full run, exactly 8 ATR rows exist, each with non-empty basis + resolvable evidence lineage (FR-CAL-6).
- **T-CAL-8**: property-based (hypothesis): calculations are pure — repeated invocation identical; no IO/clock imports in `domain/` (FR-CAL-8).

### Policy engine
- **T-POL-1**: every rule evaluation carries concrete inputs with lineage refs; uniform-rules check: same context → same result across 100 shuffled evaluations (FR-POL-3, `02 §4`).
- **T-POL-2**: manifest tamper — modify one byte of a rules file in a copied pack → loader aborts with `PolicyPackIntegrityError` (FR-POL-2, -5).
- **T-POL-3**: pack lint — every `on_fail.reason_code` resolves in `reason-codes.json`; every input path in the documented vocabulary; fixture pack with unbound code fails load (FR-POL-4).
- **T-POL-4**: rule-outcome goldens per archetype (exact failed-rule sets from `14 §4` table) (FR-POL-6).
- **T-POL-5**: counteroffer solver — archetypes #10/#11/#12 produce hints within $1,000 of analytic solutions; hint revalidates as passing (FR-POL-7).
- **T-POL-6**: a stub second engine implementing `RulesEngine` passes the same golden suite (protocol conformance) (FR-POL-8).
- **T-POL-7 (missing-data)**: context missing a referenced key → rule outcome `refer` with `RC-DATA-MISSING`, no exception.

### AUS simulator
- **T-AUS-1**: recommendation goldens per archetype + band-edge cases (points exactly at approve_max/refer_max) (FR-AUS-1).
- **T-AUS-2**: message triggers — each trigger fixture yields its message id/category; stable ids (FR-AUS-2).

### Fraud screen
- **T-FRD-1**: each red-flag rule's trigger/no-trigger fixture pair (FR-FRD-1).
- **T-FRD-2**: critical flag forces suggested_action=suspend in the packet (FR-FRD-2).

### Conditions
- **T-CND-1**: sources → conditions mapping incl. dedup (same source twice → one condition) (FR-CND-1, -3).
- **T-CND-2**: LLM-drafted text present when provider available; deterministic fallback template when the draft call fails; category/source unaffected either way (FR-CND-2).

### Decision gate & graph
- **T-TOP-1**: graph-topology assertion — every START→finalize path contains `human_review`; `adverse_action` predecessors = {human_review(decline)} (HR-2, FR-DEC-1, FR-AUS-4).
- **T-TOP-2**: eligibility provenance — decision packet `rules.overall` traces to `rule_eval_batch` events only; no other writer of eligibility exists (grep/AST + runtime check) (HR-1, FR-POL-1).
- **T-DEC-2**: resume validation matrix — decline without codes ✗; decline with 5 codes ✗; codes ⊄ eligible set ✗; valid decline w/ second reviewer ✓; each ✗ re-presents the gate with `validation_errors` (FR-DEC-2, -7).
- **T-DEC-3**: override (action ≠ suggested, both directions) without justification ✗; with justification → `OverrideRecord` + `override` event (FR-DEC-3).
- **T-DEC-4**: four-eyes — decline with same second reviewer ✗; loan ≥ threshold without second reviewer ✗ (FR-DEC-4).
- **T-DEC-5**: counteroffer terms revalidated; failing counteroffer re-presents gate (FR-DEC-5).
- **T-DEC-6**: kill the process between interrupt and resume; restart; resume completes from checkpoint (FR-DEC-6, NFR-3).
- **T-STA-1**: serialized state < 32 KB at every node boundary across all archetypes; TS mirror types match `agent-state.schema.json` (FR-UI-5, NFR-4).

### Adverse action & HMDA
- **T-AAN-1**: decline archetypes → notice contains exactly the selected codes' `ecoa_text` strings (string equality), FCRA block complete (score/range/date/≤4 factors/bureaus); no other reason text present (FR-AAN-1, -2, HR-10).
- **T-HMD-1**: action-taken mapping per decision type; denial HMDA codes = selected codes' mappings (FR-HMD-1, FR-AAN-3).
- **T-HMD-2**: milestone timestamps present and ordered (FR-HMD-2, FR-PKG-5).
- **T-HMD-3**: monitoring extract joins decisions↔demographics; demographics absent from every other endpoint's response (schema assertion) (FR-HMD-4).
- **T-ISO-1**: AST import-graph walk — no module under `agent/`, `policy_engine/`, `aus/`, `domain/` imports `hmda.demographics` or names its table (HR-6, FR-HMD-3).

### Audit & repeatability
- **T-AUD-1**: event completeness — a full run emits every catalogue type expected for its path; seal present; every event's application linkage correct (FR-AUD-1, -5).
- **T-AUD-2**: chain verify OK over a multi-run interleaved database; byte-flip a payload via raw SQL on a **copy** (triggers dropped) → verify reports that exact seq; canonical JSON stable across platforms (sorted keys, Decimal strings) (FR-AUD-2, -4, -7).
- **T-AUD-3**: UPDATE and DELETE against `audit_events` raise from the trigger even via raw SQL; no repo method exists for either; snapshots likewise (FR-AUD-3, NFR-8).
- **T-REP-1**: replay every sealed archetype decision → `identical: true`; corrupt one snapshot input → replay reports a structured diff (not a crash); snapshot exposes all pinned versions (FR-AUD-6, HR-5, HR-7, NFR-7, FR-PKG-3, FR-AUS-3).
- **T-REP-2**: full determinism — run the same archetype twice (mock): identical decisions, rule records, extracted fields; event streams identical modulo ULIDs/timestamps (NFR-1).
- **T-SEC-1**: log capture during a full run: no unmasked SSN/DOB/account-number patterns; ledger payload keys PII-free (FR-AUD-8).

### API & UI
- **T-API-1**: contract tests over every `12 §3` endpoint (happy + error envelope) against seeded archetypes; OpenAPI completeness (FR-API-1, -3).
- **T-P0-1**: walking-skeleton gate — trivial graph interrupt round-trips through AG-UI in a browser (FR-API-2; Phase 0 exit criterion).
- **T-LIN-1**: lineage resolution from a displayed DTI down to paystub extracted fields; depth/dedup behavior (FR-LIN-1, HR-3, FR-CAL-7).
- **T-UI-1**: demo-script walkthrough steps 1–5 — screens render, live stepper streams, 4 Cs update (FR-UI-1, FR-UI-2).
- **T-UI-2**: every displayed computed number opens its lineage popover (vitest for TracedNumber + manual step 3) (FR-LIN-2).
- **T-UI-3**: decision-form validation mirrors server rules — reason-code picker limited to eligible codes, override justification, four-eyes fields (FR-UI-3, `02 §9` UDAAP row).
- **T-UI-4**: audit timeline shows verify badge, replay result, filters, and export (FR-UI-4).

### State overlays
- **T-SOV-1**: overlay rules produce standard `RuleEvaluationRecord`s; guarded-out rules record `not_applicable`; an overlay eligibility failure flows to rollup/packet/adverse action identically to base failures (FR-STA-1).
- **T-SOV-2**: pack lint — every overlay rule has a non-empty `citation` (fixture without one fails load); no overlay rule reads any input beyond the documented context vocabulary + state additions (FR-STA-2, -6).
- **T-SOV-3**: most-restrictive-wins — a loan passing all base rules but failing STX-001 is ineligible; no API or pack mechanism can suppress a base rule (grep/AST: no override construct exists) (FR-STA-3).
- **T-SOV-4**: overlay manifest tamper rejected at load; DecisionSnapshot carries `state_overlay_pack` + manifest sha; replay covers overlay evaluations (FR-STA-4, extends T-REP-1).
- **T-SOV-5**: state-selection goldens — the identical loan evaluated with property.state TX vs OH produces overlay findings only for TX; TX boundary sweep (LTV 79.99/80.00/80.01 on a6, fees 1.999/2.000/2.001%, seasoning 364/365/366 days); NY/MA/GA high-cost trigger fixtures; archetype #13–15 expected outcomes (FR-STA-5).
- **T-SOV-6**: decline in CO/CA appends the ADMT artifact block to the adverse-action package with provenance references; decline in OH does not (FR-STA-7).

### Synthetic data
- **T-DAT-1**: same seed → byte-identical generator output (hash the output tree) (FR-DAT-1, -4).
- **T-DAT-2**: 15 archetype expected-outcome assertions (the `14 §4` table is the fixture) (FR-DAT-2).
- **T-DAT-3**: corpus run — ≥ 500 packages: 100% pipeline completion, 100% chain verification, 100% replay-identical, boundary-case table all-correct, distribution report generated (FR-DAT-3, `02 §6/§7`).
- **T-PER-1** *(SHOULD)*: single-run ≤ 10 s, corpus ≤ 20 min, laptop-class hardware (NFR-6).
- **T-ENV-1**: fresh-clone bootstrap on Windows (scripts only, no Docker) reaches a passing T-P0-1 (NFR-5).

## 2. Demo script (UI acceptance — `docs/demo-script.md`)

1. `scripts/dev.ps1` → both services up → `/pipeline` lists the 15 archetypes.
2. Open `borderline-dti-compensating` → Run → watch the 13-stage stepper stream live.
3. 4 Cs tab: click **back-DTI 48.5%** → lineage popover → expand to the paystub extraction (confidence, prompt@v1, model id) → open document with highlight.
4. Rules tab: DTI-001 pass via compensating branch, inputs visible. ATR tab: 8 factors green.
5. Decision tab: gate shows suggested approve_with_conditions; approve; conditions confirmed.
6. Audit tab: chain verified ✓ badge; seal present; **Replay → Reproducible ✓**; export JSON.
7. Open `decline-credit` → run → gate suggests decline; attempt decline with no reasons (blocked); select RC-CREDIT-SCORE + RC-CREDIT-DISPUTE, add second reviewer → adverse-action preview shows exactly those two ECOA texts + FCRA block.
8. Open `occupancy-fraud-flag` → critical red flag banner; suggested suspend.
9. Sidebar chat on any loan: "Why is the DTI high?" → grounded answer citing tool results; "Draft the VOE condition" → draft text appears for human application.
10. Kill backend mid-interrupt on a fresh run; restart; resume the gate → completes (durability, visible proof of T-DEC-6).

## 3. Acceptance gates (release = all green)

1. `pytest` full suite green, mock provider, Windows.
2. Corpus run report: 500/500 complete, verified, replay-identical.
3. Demo script executed end-to-end without deviation.
4. Cross-reference lint: every FR/NFR ↔ spec section ↔ test mapping intact (`scripts/xref-lint` — part of T-API-1 job).
5. `T-ENV-1` fresh-clone bootstrap.
