# 09 — Agent Graph (LangGraph)

Requirements covered: FR-DEC-1..7, FR-EXT-1, FR-VER-1..5, FR-CND-1..3, FR-AAN-1..3, FR-UI-5/NFR-4, NFR-3. The graph is the orchestration spine. Nodes contain **no business math** — they load, call domain/policy/aus/llm, persist, audit, and update state.

---

## 1. Topology

```
package_validate → document_extraction → data_verification → income_calc
→ credit_analysis → asset_analysis → collateral_analysis → fraud_screen
→ rules_eval → aus_simulate → condition_synthesis → prepare_decision
→ ⟦interrupt⟧ human_review ──(approve_with_conditions | suspend | counteroffer)──► finalize
                    └──(decline)──► adverse_action ──► finalize
finalize → audit_seal → END
```

Hard topology invariants (T-TOP-1/2): (a) every path from START to `finalize` passes `human_review`; (b) no node other than `rules_eval` writes eligibility outcomes; (c) `adverse_action` is reachable only from `human_review` with `action=decline`.

## 2. State schema (`schemas/agent-state.schema.json`; TS mirror `frontend/lib/agent-state.ts`)

```python
class Stage(TypedDict):
    id: str; label: str
    status: Literal["pending", "running", "done", "warning", "error"]
    detail: str            # one-line human summary, e.g. "14 fields from 6 documents"

class UnderwritingState(TypedDict):
    application_id: str
    policy_pack_version: str
    progress: list[Stage]                  # one entry per pipeline node — drives generative UI
    four_cs: dict                          # {credit: {representative_score, flags}, capacity: {front_ratio, back_ratio},
                                           #  capital: {reserves_months, unsourced_deposits}, collateral: {ltv, cltv}}
    red_flags: list[dict]                  # [{code, severity, description}]
    aus: dict                              # {recommendation, message_count}
    conditions_summary: list[dict]         # [{id, category, title, source_kind}]
    decision_packet: dict | None           # §5.1 — set by prepare_decision
    human_decision: dict | None            # §5.2 — set on resume
    messages: Annotated[list, add_messages]  # chat channel
```

**State budget (NFR-4, FR-UI-5):** serialized state MUST stay < 32 KB at every node boundary (asserted in T-STA-1). Only summaries live here; full rows come from REST. No document text, no lineage graphs, no full rule traces in state.

## 3. Node contracts

Common contract for every node: open one DB session; on success commit + append its audit events + set its `progress` stage `done` with `detail`; on exception set stage `error`, append `node_error` audit event, re-raise (LangGraph retry policy: max 2 retries for nodes marked idempotent below; others fail the run to `suspended` status with condition `SYSTEM-RETRY`).

### 3.1 `package_validate` *(idempotent)*
- Reads: `package_json`. Asserts Tier-1/2 validity (defense in depth; API already validated), pins `policy_pack_version` into state from the application row (FR-PKG-3), sets status `in_review`, stamps `review_started_at`.
- Audit: `state_change:in_review`.

### 3.2 `document_extraction` *(idempotent per document)*
- For each document: select prompt by `doc_type` (`prompts/extraction/<doc_type>.v*.yaml`), call `LLMClient.extract`, validate output against the prompt's output schema, persist `ExtractedField` rows (+ `extracted_field` lineage leaves), FR-EXT-1..3.
- Doc types with no registered extraction prompt (`tri_merge_credit`, `voe`) are **skipped by design** — their data enters through the package's structured credit block and the VOE adapter respectively; the skip is noted in the stage `detail` (no audit event, no error).
- Retry once on schema-invalid output; then mark `extraction_failed` + condition.
- Audit: one `llm_call` per call (FR-LLM-2). Progress detail: "N fields from M documents".

### 3.3 `data_verification`
- Runs adapters (VOE per borrower, flood, OFAC — FR-VER-4/5) and cross-checks stated vs documented per `06 §7` tolerance table → `Discrepancy` rows (FR-VER-1..3).
- OFAC hit ⇒ set status `suspended`, raise `GraphHalt` (run ends; gate never reached; mandatory-review condition recorded) — FR-VER-5.
- Audit: `adapter_call` × N, `discrepancy_found` × N.

### 3.4 `income_calc`, `credit_analysis`, `asset_analysis`, `collateral_analysis`
- Pure-domain computation per `06 §2–6`; persist components/profiles/DTI/ATR rows + lineage; update `state.four_cs.<dimension>`.
- `income_calc` also writes all 8 `AtrEvaluation` rows (factors 1,3,4,5,6,7 computable here; 2 from VOE results; 8 from credit — the node orchestrates the full set after credit_analysis completes: implementers MAY move ATR write to `rules_eval` pre-step; the invariant is 8 rows exist before `prepare_decision` — T-CAL-7).
- Audit: `calculation_set` per dimension (payload: labels + lineage refs, not full trees).

### 3.5 `fraud_screen`
- Evaluates `06 §9` red-flag rules → `RedFlag` rows; updates `state.red_flags`.
- Audit: `red_flag` × N.

### 3.6 `rules_eval`
- Builds evaluation context (`07 §3`) from persisted rows only; `RulesEngine.evaluate` with the pinned pack; persists `RuleEvaluationRecord`s; audit `rule_eval_batch` (payload: pack version + per-rule {id, outcome, reason_code}).

### 3.7 `aus_simulate`
- Runs the simulator (`08`); persists findings + messages; updates `state.aus`.
- Audit: `aus_run` (payload incl. simulator_version + breakdown).

### 3.8 `condition_synthesis`
- Sources: documentation-severity rule failures, AUS messages, discrepancies, red flags (FR-CND-1). Dedup by (source, requirement) (FR-CND-3). Category set deterministically by source table; text drafted via `LLMClient.draft_condition` (prompt `conditions/draft-condition.v1`) with deterministic fallback template if LLM unavailable (FR-CND-2).
- Audit: `llm_call` × N (drafting), `condition_created` × N.

### 3.9 `prepare_decision`
- Assembles the decision packet (§5.1); computes `suggested_action` by the first matching row:
  1. any **critical** red flag ⇒ `suspend`
  2. rollup `ineligible` ⇒ `decline` (counteroffer hints surfaced if present)
  3. rollup `refer` (eligibility-severity refers, per `07 §4.4`) ⇒ `suspend`
  4. any **elevated** red flag, or any borrower's VOE ≠ `verified` ⇒ `suspend`
  5. else ⇒ `approve_with_conditions`
  (Documentation/informational rule failures alone do **not** trigger suspend — they ride along as conditions; e.g., a clean LTV-82 loan is suggested approve with the DU-MI-07 PTF condition.)
- Requests the display narrative via `LLMClient.narrate` (`narrative/four-cs-summary`, register row 11); persists it on the application row; on failure the narrative is `null` and the UI shows structured data only. This is the only narrative generation point.
- Sets status `ready_for_decision` + `decision_ready_at`; audit `decision_packet_ready`; then **`interrupt(decision_packet)`** (FR-DEC-1).

### 3.10 `human_review`
- Receives resume payload (§5.2). Validates (FR-DEC-2/3/4/7): action enum; underwriter_id present; decline ⇒ 1–4 reason codes ⊆ `eligible_reason_codes`; override (action ≠ suggested) ⇒ justification ≥ 20 chars + `OverrideRecord`; four-eyes (decline OR amount ≥ threshold) ⇒ `second_reviewer_id` present and ≠ `underwriter_id`. Invalid ⇒ re-`interrupt` with `validation_errors` attached (graph does not advance).
- Audit: `human_action` (full payload), `override` when applicable.

### 3.11 `adverse_action` (decline only)
- Builds `AdverseActionNotice` (FR-AAN-1): principal reasons = selected codes' `ecoa_text` verbatim — no additions, removals, or rewording (FR-AAN-2, HR-10); FCRA block from credit data (score, range, date, ≤4 key factors, bureaus); fixed ECOA statement template. LLM not called here.
- Audit: `adverse_action_generated`.

### 3.12 `finalize`
- Writes `UnderwritingDecision`; counteroffer path first revalidates modified terms through the policy engine (FR-DEC-5) — if the counteroffer still fails eligibility, re-`interrupt` with the failure attached; maps HMDA action-taken via `hmda/action_taken.py`; sets terminal status + `decided_at`.
- Audit: `state_change:<terminal>`, `hmda_action_taken`.

### 3.13 `audit_seal`
- Builds the `DecisionSnapshot` (`11 §6`), stores it, appends the terminal `seal` event containing its SHA-256, writes `snapshot_hash` onto the decision row.

## 4. (reserved)

Section intentionally merged into §3 node contracts.

## 5. The decision gate

### 5.1 Decision packet (interrupt payload; schema `schemas/interrupt-resume.schema.json#/$defs/decision_packet`)
```jsonc
{
  "application_id": "...", "suggested_action": "approve_with_conditions",
  "four_cs": { ... },                       // same summaries as state
  "rules": {"overall": "eligible", "failed": [{"rule_id","reason_code","description","inputs":[{path,value}]}]},
  "eligible_reason_codes": ["RC-..."],      // decline picker source (FR-DEC-2)
  "aus": {"recommendation": "...", "messages_by_category": {"PTA": [...], "PTD": [...], "PTF": [...]}},
  "red_flags": [...], "conditions": [...],
  "counteroffer_hints": [{"rule_id","parameter":"loan.amount","max_value":"429000.00"}],
  "four_eyes_required": true|false,
  "atr_complete": true,
  "validation_errors": []                   // populated on re-present after invalid resume
}
```

### 5.2 Resume payload (`#/$defs/resume`)
```jsonc
{
  "action": "approve_with_conditions|suspend|decline|counteroffer",
  "underwriter_id": "uw-1042",
  "second_reviewer_id": null,
  "reason_codes": [],                        // decline: 1–4, ⊆ eligible_reason_codes
  "justification": null,                     // required when action != suggested_action
  "condition_edits": [{"id":"...", "text":"...", "status":"open|waived"}],
  "counteroffer_terms": {"loan_amount": "560000.00"}   // required when action=counteroffer
}
```

### 5.3 Overrides & four-eyes (FR-DEC-3/4)
Override = `action != suggested_action` (any direction). Both directions are recorded — approve-over-suggested-decline and decline-over-suggested-approve — because override *patterns* are the fair-lending monitoring signal (`02 §4`). Four-eyes threshold from `FOUR_EYES_THRESHOLD` env (default 1,000,000) plus all declines.

### 5.4 Counteroffer (FR-DEC-5)
Modified terms revalidate through `rules_eval`-equivalent evaluation before finalize; HMDA treats an unaccepted counteroffer as denial (acceptance flows are out of scope; the record notes `counteroffer_extended=true`).

## 6. Durability (FR-DEC-6, NFR-3)

Checkpointer: `AsyncSqliteSaver` on `data/db/checkpoints.db`; `thread_id = application_id`; checkpoint after every node. A process restart while interrupted: the run stays `ready_for_decision`; resume arrives via the same AG-UI endpoint with the thread id; the graph continues from the checkpoint (T-DEC-6 kills the process between interrupt and resume).

## 7. Chat path (FR-LLM-5)

The same graph exposes a chat lane: user messages route to a `chat` node (conditional entry) with read-only tools — `get_loan_summary`, `get_dti_breakdown(borrower?)`, `get_rule_result(rule_id)`, `get_open_conditions`, `get_red_flags`, `explain_lineage(ref)`, `draft_condition_text(source_id)`. Tools read repositories only; no tool mutates decisions, rules, conditions (except returning *draft text* the UI may apply via REST with human confirmation), or the ledger. Every tool call and chat completion is audited (`llm_call`, `tool_call`). The chat lane never triggers `interrupt` and cannot resume one.
