# 01 — Requirements

All requirements carry stable IDs. Every ID appears in at least one spec section (the **Spec** column) and at least one test (the **Test** column, defined in `15-testing-acceptance.md`). RFC-2119 keywords are normative.

Status values used below: all requirements are **mandatory** unless marked *(SHOULD)*.

---

## 1. Loan package intake & validation (FR-PKG)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-PKG-1 | The system MUST accept a loan package conforming to `schemas/loan-package.schema.json` via `POST /loans` and reject non-conforming packages with field-level errors. | 05 §2, 12 §3.1 | T-PKG-1 |
| FR-PKG-2 | Package validation MUST verify internal referential integrity per the Tier-2 list in `05 §4` (all id references resolve; exactly one primary borrower; purchase price present iff purchase; units consistent with property type; no duplicate ids). | 05 §4 | T-PKG-2 |
| FR-PKG-3 | The policy pack version MUST be pinned to the application at package acceptance and used unchanged for the entire run (HR-7). | 07 §5, 09 §3.1 | T-REP-1 |
| FR-PKG-4 | A package failing structural validation MUST NOT create an underwriting run; it is rejected at the API boundary with no partial state. | 05 §4, 12 §3.1 | T-PKG-1 |
| FR-PKG-5 | Each accepted package MUST receive a ULID `application_id` and an initial `received` status with timestamp (HMDA milestone). | 04 §5, 09 §3.1 | T-HMD-2 |

## 2. Document extraction (FR-EXT)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-EXT-1 | The system MUST extract structured fields from each document's text rendering using the LLM extraction prompts defined in `prompts/extraction/`, producing `ExtractedField` rows with confidence scores. | 09 §3.2, 10 §3 | T-EXT-1 |
| FR-EXT-2 | Every extraction MUST record the prompt id + version and exact model id used (HR-7). | 10 §4 | T-LLM-2 |
| FR-EXT-3 | Extraction output MUST validate against the per-document-type output schema in the prompt definition; non-conforming output is retried once, then the field is marked `extraction_failed` and a condition is raised. | 10 §3 | T-EXT-2 |
| FR-EXT-4 | With `LLM_PROVIDER=mock`, extraction MUST return the package's ground-truth sidecar values deterministically. | 10 §5, 14 §3 | T-EXT-3 |
| FR-EXT-5 | Extracted monetary values MUST be parsed to `Decimal`; dates to ISO-8601; no floats anywhere in money math (NFR-2). | 06 §1 | T-CAL-1 |

## 3. Data verification (FR-VER)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-VER-1 | The system MUST cross-check extracted document values against package-stated values (income, balances, employment) and record a `Discrepancy` for every mismatch beyond tolerance (HR-8). | 06 §7, 09 §3.3 | T-VER-1 |
| FR-VER-2 | Tolerances per the normative table in `06 §7`: paystub-annualized vs stated income ±2%; W-2 vs tax-return wages ±5%; stated vs documented asset balances ±$100 or 1%, whichever is greater. | 06 §7 | T-VER-1 |
| FR-VER-3 | Discrepancies MUST become findings (red flags and/or conditions) — never silent corrections. The documented (extracted) value is used for calculations, with the discrepancy noted in lineage. | 06 §7, 09 §3.3 | T-VER-2 |
| FR-VER-4 | Simulated verifications (VOE, flood zone, OFAC) MUST run through adapter interfaces and record results with adapter name + config version. | 03 §6 | T-ADP-1 |
| FR-VER-5 | An OFAC simulated hit MUST hard-stop the pipeline into `suspended` with a mandatory-review flag; it never auto-declines. | 09 §3.3 | T-VER-3 |

## 4. Calculations (FR-CAL)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-CAL-1 | Qualifying income MUST be computed per component type using the algorithms in `06-calculations.md §2` (base, overtime/bonus/commission 2-yr average or 75% YTD rule, self-employed 2-yr Schedule C average with add-backs, rental 75% of gross, other). | 06 §2 | T-CAL-2 |
| FR-CAL-2 | DTI MUST be computed as front-end = PITIA ÷ qualifying monthly income and back-end = (PITIA + monthly liabilities) ÷ qualifying monthly income, using `Decimal` with banker's rounding, expressed in percent scale to 3 dp (displayed to 1 dp) per `06 §1`. | 06 §3 | T-CAL-3 |
| FR-CAL-3 | LTV = loan amount ÷ min(purchase price, appraised value) for purchases; ÷ appraised value for refinances. CLTV includes all subordinate liens. Rounded up to 2 decimal places (conservative). | 06 §4 | T-CAL-4 |
| FR-CAL-4 | Reserves MUST be computed as post-closing liquid assets ÷ PITIA, in months, floored to 1 decimal. Retirement assets count at 60% of vested value *(SHOULD, configurable in pack)*. | 06 §5 | T-CAL-5 |
| FR-CAL-5 | Representative credit score: per borrower = middle of 3 scores (lower of 2 if 2, the score if 1); loan level = lowest representative among borrowers. | 06 §6 | T-CAL-6 |
| FR-CAL-6 | All eight ATR factors (12 CFR 1026.43) MUST be explicitly evaluated and persisted as `AtrEvaluation` rows, each with basis and lineage, for every run. | 06 §8 | T-CAL-7 |
| FR-CAL-7 | Every calculation output MUST be a `TracedValue`; every operand's lineage ref is recorded in the calculation's lineage node (HR-3). | 04 §3, 06 §1 | T-LIN-1 |
| FR-CAL-8 | Calculations MUST be pure functions (no IO, no clock, no randomness) — same inputs, same outputs, always (NFR-1). | 06 §1 | T-CAL-8 |

## 5. Policy engine (FR-POL)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-POL-1 | Eligibility MUST be decided exclusively by the deterministic policy engine evaluating the pinned pack against persisted TracedValues (HR-1). | 07 §1 | T-TOP-2 |
| FR-POL-2 | The engine MUST load packs only after verifying the sha256 manifest in `pack.json`; any file hash mismatch aborts the load. | 07 §5 | T-POL-2 |
| FR-POL-3 | Each rule evaluation MUST produce a `RuleEvaluationRecord`: rule id, pack version, concrete input values consumed (with lineage refs), predicate result, outcome, reason-code binding. | 07 §4 | T-POL-1 |
| FR-POL-4 | Every rule's `on_fail` MUST bind a reason code defined in `reason-codes.json`; a pack containing an unbound failure outcome MUST fail validation at load. | 07 §6 | T-POL-3 |
| FR-POL-5 | Rule packs are immutable: a released pack directory is never edited; changes ship as a new semver directory. | 07 §5 | T-POL-2 |
| FR-POL-6 | The shipped `conforming-2026.1.0` pack MUST implement the eligibility matrix in `07-policy-engine.md §7` (2026 conforming limits, LTV/CLTV matrix, DTI 45/50 with ≥2 compensating factors, credit rules incl. open-dispute ineligibility, reserves, large-deposit sourcing, asset seasoning). | 07 §7, policy-pack/ | T-POL-4 |
| FR-POL-7 | Rules MUST support `counteroffer_hint` outputs (e.g., max loan amount at which DTI passes) computed deterministically. | 07 §4.3 | T-POL-5 |
| FR-POL-8 | The engine MUST be exposed behind a `RulesEngine` protocol so an alternative engine (e.g., GoRules ZEN) can be substituted without touching callers. | 07 §2 | T-POL-6 |

## 6. AUS simulator (FR-AUS)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-AUS-1 | The AUS simulator MUST deterministically map the loan's risk profile to one of: `Approve/Eligible`, `Approve/Ineligible`, `Refer with Caution`, `Out of Scope`, per `08-aus-simulator.md`. | 08 §3 | T-AUS-1 |
| FR-AUS-2 | The simulator MUST emit verification messages grouped PTA/PTD/PTF derived from its findings, each with a stable message id. | 08 §4 | T-AUS-2 |
| FR-AUS-3 | The simulator's weights/thresholds MUST load from a versioned config (`policy/aus/du-sim.v1.json`); the version is pinned in the DecisionSnapshot (HR-7). | 08 §5 | T-REP-1 |
| FR-AUS-4 | The AUS recommendation is advisory: it MUST NOT finalize any decision (HR-2); it feeds the decision packet only. | 08 §1, 09 §3.7 | T-TOP-1 |

## 7. Fraud screen (FR-FRD)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-FRD-1 | The fraud screen MUST evaluate the deterministic red-flag ruleset in `06-calculations.md §9` (occupancy distance > 200 mi, insurance-type mismatch, unsourced large deposits > 25% monthly income, W-2/tax-return wage mismatch > 5% with unverified VOE, round-dollar deposit patterns, undisclosed-liability indicators). | 06 §9 | T-FRD-1 |
| FR-FRD-2 | Each red flag MUST carry severity (`info`/`elevated`/`critical`), lineage to its evidence, and a recommended action; `critical` flags force the suggested action to `suspend` in the decision packet. | 06 §9, 09 §3.5 | T-FRD-2 |

## 8. Conditions (FR-CND)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-CND-1 | Conditions MUST be synthesized from three sources: failed/deferred rule outcomes, AUS verification messages, and discrepancies/red flags — each condition records its source (rule id / AUS msg id / discrepancy id). | 09 §3.8 | T-CND-1 |
| FR-CND-2 | Condition text MAY be drafted by the LLM from the source finding, but the category (PTA/PTD/PTF), source link, and requirement basis are set deterministically; the human can edit text at the gate. | 09 §3.8, 10 §3 | T-CND-2 |
| FR-CND-3 | Duplicate conditions (same source + same requirement) MUST be merged. | 09 §3.8 | T-CND-1 |

## 9. Decision gate & human review (FR-DEC)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-DEC-1 | Every run MUST stop at a LangGraph `interrupt()` carrying the decision packet (schema `schemas/interrupt-resume.schema.json`) before any final decision (HR-2). | 09 §5 | T-TOP-1 |
| FR-DEC-2 | The resume payload MUST specify `action ∈ {approve_with_conditions, suspend, decline, counteroffer}`, the acting underwriter id, and — for declines — ≥1 and ≤4 reason codes chosen only from codes bound to actually-failed rules. | 09 §5.2 | T-DEC-2 |
| FR-DEC-3 | An override (human action contradicting the engine-suggested action) MUST require a written justification and MUST be recorded as an `OverrideRecord`. | 09 §5.3 | T-DEC-3 |
| FR-DEC-4 | Four-eyes: declines and loans with amount ≥ `FOUR_EYES_THRESHOLD` (default $1,000,000) MUST require a second reviewer id distinct from the first; the resume is rejected otherwise. | 09 §5.3 | T-DEC-4 |
| FR-DEC-5 | Counteroffers MUST carry modified terms (at minimum a reduced loan amount) and revalidate against the policy engine before finalization. | 09 §5.4 | T-DEC-5 |
| FR-DEC-6 | Interrupted runs MUST survive process restarts and be resumable via the checkpointer (`thread_id = application_id`). | 09 §6 | T-DEC-6 |
| FR-DEC-7 | Invalid resume payloads (missing reasons on decline, missing justification on override, same second reviewer) MUST be rejected without advancing the graph, re-presenting the gate. | 09 §5.2 | T-DEC-2 |

## 10. Adverse action (FR-AAN)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-AAN-1 | On decline, the system MUST generate an adverse-action notice containing: the specific principal reasons (ECOA text from the selected reason codes), creditor identification placeholder, ECOA notice text, and the FCRA credit-score disclosure block (score, range, date, up-to-4 key factors, bureau identification). | 09 §5.5, 04 §4 | T-AAN-1 |
| FR-AAN-2 | Notice reasons MUST be exactly the human-selected reason codes' ECOA texts — no LLM additions, removals, or rewording (HR-10). | 10 §3 | T-AAN-1 |
| FR-AAN-3 | Each selected reason code MUST also map to its HMDA denial reason code on the HMDA record. | 04 §5 | T-HMD-1 |

## 11. HMDA & fair lending (FR-HMD)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-HMD-1 | The system MUST maintain an action-taken state machine producing HMDA codes (1 originated-proxy→approved, 2 approved-not-accepted, 3 denied, 4 withdrawn, 5 incomplete) with action date, for every application. | 04 §5 | T-HMD-1 |
| FR-HMD-2 | Milestone timestamps MUST be captured: received, review started, decision-ready, decided. | 04 §5 | T-HMD-2 |
| FR-HMD-3 | Demographic data MUST live only in the isolated `hmda/demographics` module + table; no decisioning module may import it (HR-6). | 04 §6 | T-ISO-1 |
| FR-HMD-4 | A demographics export endpoint *(SHOULD)* provides the fair-lending monitoring extract (decisions joined to demographics) for out-of-band analysis — read-only, flagged as monitoring-only. | 12 §3.6 | T-HMD-3 |

## 12. Audit & repeatability (FR-AUD)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-AUD-1 | Every state change, tool call, LLM call, rule evaluation batch, adapter call, human action, override, and seal MUST append exactly one event to the audit ledger per `11-audit-repeatability.md §3`. | 11 §3 | T-AUD-1 |
| FR-AUD-2 | Events MUST be hash-chained: `hash = SHA-256(prev_hash ‖ event_id ‖ event_type ‖ canonical_payload ‖ created_at)`; the first event's `prev_hash = "GENESIS"`. | 11 §4 | T-AUD-2 |
| FR-AUD-3 | The audit store MUST reject UPDATE and DELETE at the storage layer (SQLite triggers `RAISE(ABORT)`), independent of application code (HR-4). | 11 §2 | T-AUD-3 |
| FR-AUD-4 | Chain verification MUST recompute every hash and report the exact first broken sequence number on tamper. | 11 §5 | T-AUD-2 |
| FR-AUD-5 | Every finalized run MUST produce a `DecisionSnapshot` per `schemas/decision-snapshot.schema.json`, and a terminal seal event containing the snapshot's SHA-256 (HR-4). | 11 §6 | T-AUD-1 |
| FR-AUD-6 | `replay(snapshot)` MUST re-execute calculations + rules from snapshot inputs and versions and assert an identical outcome, rule-by-rule (HR-5). | 11 §7 | T-REP-1 |
| FR-AUD-7 | Audit payloads MUST use canonical JSON (sorted keys, no insignificant whitespace, `Decimal` as strings) so hashes are stable across platforms. | 11 §4.1 | T-AUD-2 |
| FR-AUD-8 | PII (SSN, DOB, account numbers) MUST be masked in application logs; the audit ledger stores them only inside encrypted-at-rest-capable payload fields, never in `event_type`/`actor` metadata. | 11 §8 | T-SEC-1 |

## 13. Lineage (FR-LIN)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-LIN-1 | `GET /lineage/{ref}` MUST resolve any lineage ref to its node + parents transitively down to `ExtractedField` leaves (doc id, field, confidence, prompt+model version) (HR-3). | 04 §3, 12 §3.4 | T-LIN-1 |
| FR-LIN-2 | Every UI-displayed computed number MUST be clickable and open its lineage chain (13 §4). | 13 §4 | T-UI-2 |

## 14. LLM layer (FR-LLM)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-LLM-1 | All LLM access MUST go through the `LLMClient` protocol; exactly one module imports the vendor SDK (HR-9). | 10 §2 | T-LLM-3 |
| FR-LLM-2 | Every LLM call MUST emit an `llm_call` audit event with prompt id+version, model id, parameters, token counts, and a content hash of input/output. | 10 §4 | T-LLM-2 |
| FR-LLM-3 | The registry in `10-llm-usage-register.md §3` is exhaustive: an LLM call from any site not in the register is a defect. A runtime assertion MUST reject prompt ids not in the registry. | 10 §3 | T-LLM-1 |
| FR-LLM-4 | `LLM_PROVIDER=mock` MUST make the entire system runnable and testable with no vendor key and full determinism. | 10 §5 | T-EXT-3 |
| FR-LLM-5 | Chat answers MUST be grounded via read-only tools over persisted loan state; the chat path has no write access to decisions, rules, or the ledger (its tool calls are still audited). | 10 §3, 09 §7 | T-LLM-4 |

## 15. API (FR-API)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-API-1 | The REST surface MUST implement `12-api-contracts.md` exactly: loans list/detail/submit/run, lineage resolve, audit page + verify, decision snapshot + adverse-action preview. | 12 | T-API-1 |
| FR-API-2 | The agent MUST be reachable by the frontend via the AG-UI endpoint `/agent/underwriter` (SSE) and the CopilotKit remote endpoint, per `03-architecture.md §5`. | 03 §5 | T-P0-1 |
| FR-API-3 | Errors MUST follow the error envelope in `12 §2` with machine-readable codes. | 12 §2 | T-API-1 |

## 16. Workbench UI (FR-UI)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-UI-1 | The workbench MUST implement the screens in `13-frontend-workbench.md`: queue, loan deep-dive (summary, 4 Cs, AUS, conditions, red flags, decision, audit), with the CopilotKit sidebar. | 13 | T-UI-1 |
| FR-UI-2 | Live agent progress MUST render via `useCoAgentStateRender` from `state.progress`; 4 Cs summaries and red flags update live via `useCoAgent` shared state. | 13 §5 | T-UI-1 |
| FR-UI-3 | The decision gate MUST render from the interrupt event and submit the resume payload; the reason-code picker MUST list only codes bound to actually-failed rules. | 13 §6 | T-UI-3 |
| FR-UI-4 | The audit timeline MUST display chain-verification status from `GET /loans/{id}/audit/verify` and support filtered browsing + JSON export. | 13 §7 | T-UI-4 |
| FR-UI-5 | Serialized agent state MUST stay < 32 KB (NFR-4): heavy data flows over REST, not agent state. | 09 §2, 13 §5 | T-STA-1 |

## 17. Synthetic data (FR-DAT)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-DAT-1 | A seeded generator MUST produce internally consistent loan packages (documents agree with structured data by construction) with ground-truth sidecars. | 14 §2 | T-DAT-1 |
| FR-DAT-2 | The 12 golden archetypes in `14 §4` MUST be committed with expected outcomes (rule hits, conditions, suggested action) asserted by tests. | 14 §4 | T-DAT-2 |
| FR-DAT-3 | The corpus generator MUST produce ≥ 500 packages spanning rule boundaries (values at, just below, and just above every numeric threshold in the pack). | 14 §5 | T-DAT-3 |
| FR-DAT-4 | Same seed → byte-identical output (no wall-clock, no unseeded randomness). | 14 §2 | T-DAT-1 |

## 18. State overlays (FR-STA)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| FR-STA-1 | State overlay rules MUST evaluate in the same engine, produce the same `RuleEvaluationRecord`s (with outcome `not_applicable` when their `applies` guard is false), bind reason codes, and flow into the decision packet, adverse action, audit, and snapshot identically to base rules. | 17 §1, §3 | T-SOV-1 |
| FR-STA-2 | Every overlay rule MUST carry a `citation` naming its statutory authority; a pack containing an uncited overlay rule MUST fail load validation. Citations render in the workbench rules table. | 17 §1, §7.1 | T-SOV-2 |
| FR-STA-3 | Overlays MUST only tighten: no overlay mechanism may relax, override, or suppress a base-pack rule (most-restrictive-wins by construction). | 17 §1 | T-SOV-3 |
| FR-STA-4 | The overlay pack MUST be versioned with its own sha256 manifest, pinned at intake alongside the base pack, and recorded in every evaluation and the DecisionSnapshot (HR-7). | 17 §2, §3 | T-SOV-4 |
| FR-STA-5 | The shipped `state-overlays-2026.1.0` pack MUST implement the rule set in `17 §7.2` (TX 50(a)(6) gates, NY §6-l/§6-m, MA c.183C/§28C, GA FLA, FL insurance, CO ADMT, community-property/funding/attorney flags, HOEPA baseline). | 17 §7, policy-pack/ | T-SOV-5 |
| FR-STA-6 | `property.state` MUST be used solely to select applicable state law; overlay rules MUST NOT risk-differentiate beyond the cited statute (fair-lending posture, `02 §4`); NY/MA/CA/IL loans carry the effects-based monitoring flag on the monitoring extract. | 17 §1.4, §7.4 | T-SOV-2, T-HMD-3 |
| FR-STA-7 | On decline in a state flagged `admt_adverse_artifact` (CO, CA), the adverse-action package MUST include the state-required ADMT artifacts (explanation, human-review path, data-correction path / notice references) sourced from actual decision provenance. | 17 §7.3 | T-SOV-6 |

## 19. Non-functional requirements (NFR)

| ID | Requirement | Spec | Test |
|----|-------------|------|------|
| NFR-1 | **Determinism:** with the mock LLM provider, an entire pipeline run is deterministic — identical inputs and versions produce identical outputs, events (excluding timestamps/ULIDs), and decisions. | 06 §1, 10 §5 | T-REP-2 |
| NFR-2 | **Numeric integrity:** all money and ratio math uses `Decimal`; floats are forbidden in `domain/` (lint-enforced). | 06 §1 | T-CAL-1 |
| NFR-3 | **Durability:** interrupted runs survive process restarts (checkpointer-backed). | 09 §6 | T-DEC-6 |
| NFR-4 | **State budget:** serialized `UnderwritingState` < 32 KB at every node boundary. | 09 §2 | T-STA-1 |
| NFR-5 | **Portability:** default profile runs on Windows 11 with no Docker (SQLite, uv-managed Python 3.12, npm); Postgres compose profile optional. | 03 §7, 16 §3 | T-ENV-1 |
| NFR-6 | **Latency (SHOULD):** mock-provider pipeline run ≤ 10 s per package; corpus run of 500 ≤ 20 min on a developer laptop. | 16 §6 | T-PER-1 |
| NFR-7 | **Version transparency:** `GET /loans/{id}/decision` exposes every pinned version (pack, prompts, models, AUS config, code git SHA). | 11 §6, 12 §3.5 | T-REP-1 |
| NFR-8 | **Retention posture:** ledger + snapshots are designed for ≥ 7-year retention; no code path expires or compacts them. | 11 §9 | T-AUD-3 |
