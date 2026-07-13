# 18 — Advisory LLM Layer (Whole-File Coherence Critic)

**Status: PROPOSED (v0.1) — specified, not yet implemented.** · **Date:** 2026-07-13

Motivation and evidence base: `docs/llm-placement-report.md` §5–§6 (advisory gaps). This document
specifies the **advisory lane**: LLM capabilities that increase what the system *notices* and how
well it *communicates* — without ever touching what it *decides*. Its centerpiece is the
**whole-file coherence critic**, the one capability of long-running agentic underwriting builds
that this architecture does not yet capture.

Requirements defined here: **FR-ADV-1..12**, **HR-11**, tests **T-ADV-1..8**. On adoption, this
document amends: `00-overview.md §2` (HR-11), `01-requirements.md` (FR-ADV block),
`10-llm-usage-register.md §3` (register row 13), `09-agent-graph.md` (advisory node),
`12-api-contracts.md` (advisory endpoints), `13-frontend-workbench.md` (advisory panel),
`15-testing-acceptance.md` (T-ADV block), `schemas/` (advisory-finding schema),
`prompts/` (advisory prompt group). Until implemented, those documents remain unchanged and
this spec is the single normative source for the advisory lane.

All normative statements use RFC-2119 keywords.

---

## 1. What "advisory" means (and why it is a separate lane)

The system's decision core is deterministic by construction (HR-1): eligibility comes only from
the policy engine over persisted, human-verifiable extracted fields; the final action comes only
from a human. That core is legally load-bearing (ECOA/Reg B reason accuracy, replayability,
fair-lending consistency) and MUST NOT change.

What the deterministic core cannot do is **judgment across the whole file**: notice that the
gift-letter story conflicts with deposit timing, that the appraisal's occupancy commentary
contradicts the stated occupancy, that a self-employed borrower's income trend deserves a
condition nobody wrote a rule for. Senior underwriters do this by reading the entire package.
An LLM can too — *provided its output is structurally incapable of altering the decision*.

**Definition.** An *advisory output* is any LLM-produced artifact whose only consumers are
(a) the human underwriter's display surfaces, (b) the audit record, and (c) suggestion inputs
that a human must explicitly accept before they have any effect. Advisory outputs are never
read by the policy engine, the AUS simulator, the calculations layer, the suggested-action
ladder, or adverse-action composition.

The system already ships three advisory capabilities (register rows 10–12 in
`10-llm-usage-register.md §3`): condition **wording** drafts, the 4 Cs **narrative**, and the
grounded **chat** sidebar. This spec (1) formalizes the containment contract they all share as a
hard rule, and (2) adds the fourth and most valuable capability: the coherence critic.

### Explicit non-goals

- The critic MUST NOT score, rank, grade, or recommend an action on the loan.
- The critic is not a fraud *decision* engine. The deterministic fraud screen and its red flags
  are unchanged; critic findings may *corroborate* red flags but never create or suppress them.
- No auto-anything: a finding never auto-adds a condition, never auto-suspends, never blocks
  approval by itself (it may *require disposition* — see §7 — which is a human act).
- Live-extraction hardening (multi-pass agentic extraction) is out of scope here; it is an
  upstream extraction concern and will be specified separately if pursued.

---

## 2. HR-11 — the advisory containment rule

> **HR-11 — Advisory outputs are display- and suggestion-only.** LLM advisory artifacts
> (coherence findings, narratives, condition drafts, chat responses) MUST NOT be read by any
> module that computes values, evaluates rules, simulates AUS, derives the suggested action, or
> composes adverse action. The only way an advisory artifact affects a loan file is through an
> explicit, audited human act (accepting a suggested condition, recording a note, making a gate
> decision). | *Rationale:* preserves HR-1's legal guarantees while widening LLM use — every
> advisory artifact is provably outside the decision basis, so ECOA reason accuracy, replay, and
> fair-lending consistency are untouched. | *Enforced by:* T-ADV-1 (static import/dataflow scan),
> T-ADV-2 (decision-invariance corpus test).

On adoption this row is appended to the hard-rules table in `00-overview.md §2`.

---

## 3. Requirements

| ID | Requirement |
|---|---|
| FR-ADV-1 | The pipeline SHALL run a **coherence critic** exactly once per underwriting run, in a dedicated `advisory_review` graph node positioned after `condition_synthesis` and before `prepare_decision`. The node consumes the assembled case view (extracted fields with confidences, stated/package data, computed TracedValues, rule results, red flags, AUS result, synthesized conditions) and produces zero or more **AdvisoryFindings**. |
| FR-ADV-2 | Every AdvisoryFinding SHALL conform to the schema in §5: category, severity, a one-sentence claim, and ≥ 1 **evidence citation**. Each citation MUST name a persisted artifact: a `document_id`, an extracted-field id, or a `lineage_ref`. |
| FR-ADV-3 | **Grounding validation (deterministic):** after the LLM responds, every citation SHALL be resolved against persisted case data. A finding with any unresolvable citation SHALL be discarded and an `advisory_finding_rejected` audit event written (with the rejected content's hash and the failing citation). Discarded findings never reach the UI. |
| FR-ADV-4 | Findings SHALL be capped at **12 per run** (highest severity first; ties by LLM order) and deduplicated on `(category, sorted evidence set)`. Over-cap truncation SHALL be recorded in the `advisory_findings_produced` event (`truncated_count`). |
| FR-ADV-5 | Advisory findings SHALL be import-isolated from decisioning: no module under `policy_engine/`, `aus/`, `domain/`, or the suggested-action / adverse-action code paths in `agent/decisioning.py` may import the advisory store or read its tables. (Same mechanism as the HR-6 demographics isolation.) |
| FR-ADV-6 | The critic's input payload SHALL be built from the demographics-stripped case view. Demographic (HMDA) data MUST NOT appear in any advisory prompt payload (extends HR-6 to the advisory lane). |
| FR-ADV-7 | **Failure isolation:** critic failure, timeout, malformed output after one retry, or provider unavailability SHALL NOT block or fail the run. The decision packet then carries `advisory: {status: "unavailable", reason}`. Zero findings is a normal, non-error outcome (`status: "clean"`). |
| FR-ADV-8 | Every critic call SHALL emit an `llm_call` audit event from a `CallRecord` (FR-LLM-2 applies unchanged), and the produced finding set SHALL be persisted with the exact `prompt_id`+version and `model_id` that produced it. |
| FR-ADV-9 | The decision packet presented at the human gate SHALL include the advisory section (§6). The UI SHALL label it "AI ADVISORY — not part of eligibility" and visually distinguish it from rule results (text labels only; no pictographs). |
| FR-ADV-10 | **Dispositions:** the resume payload MAY carry per-finding dispositions (`accept_condition` / `accept_note` / `dismiss`). `validate_resume` SHALL reject an `approve_with_conditions` or `counteroffer` resume while any finding of severity `significant` is undisposed (re-present with a validation error, existing mechanism). `accept_condition` creates a human-added condition through the existing human-condition path; `dismiss` of a `significant` finding requires a non-empty reason. Every disposition writes an `advisory_finding_disposed` audit event naming the underwriter. |
| FR-ADV-11 | The DecisionSnapshot SHALL embed the advisory section (findings + dispositions + status + prompt/model pins) as a **sealed display-only block**. Replay (HR-5) SHALL NOT re-invoke the critic; it SHALL verify the sealed block byte-for-byte like every other snapshot section. Advisory content MUST NOT feed any recomputed value during replay. |
| FR-ADV-12 | **Monitoring (SR 26-2 spirit):** disposition outcomes SHALL be derivable from the ledger (produced/rejected/disposed events), so acceptance-rate and category-usefulness reporting requires no additional writes. A findings-quality report over the golden archetypes SHALL be part of the eval gate (§9). |

---

## 4. Register amendment and protocol change

### 4.1 New register row (`10-llm-usage-register.md §3`)

| # | Call site | Prompt id | Purpose | Inputs | Output contract | Why an LLM | Failure behavior |
|---|---|---|---|---|---|---|---|
| 13 | `advisory_review` node | `advisory/coherence-critic` | whole-file cross-document coherence review | demographics-stripped case view JSON (§4.3) | JSON `findings[]` per §5 schema | judgment across an entire file is the one underwriting task that is genuinely unstructured; output is advisory-only (HR-11) | retry ×1 → `advisory.status=unavailable`; pipeline unaffected (FR-ADV-7) |

The never-list in `10 §3` gains: *"…and no LLM call exists in the disposition-validation path
(`validate_resume`) — dispositions are validated deterministically."*

### 4.2 `UALLMClient` protocol addition (`backend/app/llm/ua_base.py`)

```python
@dataclass(frozen=True)
class AdvisoryResult:
    findings: list[dict]           # pre-grounding-validation, schema-shaped
    record: CallRecord

class UALLMClient(Protocol):
    ...existing extract / narrate / draft...
    async def advise(self, *, prompt: Prompt, payload: dict,
                     call_site: str) -> AdvisoryResult: ...
```

Provider obligations (both mock and live): render the prompt template with the payload, honor
`model_params`, return bare JSON (`{"findings": [...]}`), one retry on parse/schema failure,
build the `CallRecord` via `make_record`. The mock provider returns the archetype's
`advisory_ground_truth` sidecar verbatim (§8), keeping CI deterministic and keyless.

### 4.3 Critic input payload (normative shape)

Built by a pure function `build_advisory_view(case) -> dict` in `agent/assembly.py` (so replay
tooling and tests share it):

```json
{
  "application": {"loan_purpose": "...", "occupancy": "...", "property_state": "..."},
  "stated":      {"...package-stated fields (no demographics)..."},
  "documents":   [{"document_id": "...", "type": "paystub",
                   "extracted_fields": {"field": {"value": "...", "confidence": "0.97"}}}],
  "computed":    {"front_dti_pct": "31.250", "back_dti_pct": "44.913", "ltv_pct": "80.00",
                  "reserves_months": "7.4", "qualifying_income_monthly": "9500.00"},
  "rules":       {"failed": ["..."], "passed_count": 41, "not_applicable_count": 6},
  "red_flags":   [{"id": "...", "description": "..."}],
  "conditions":  [{"id": "...", "category": "PTF", "text": "..."}]
}
```

All Decimal values serialize as strings (canonical-JSON rules apply). The payload is hashed into
the `CallRecord.input_sha256` as usual.

---

## 5. AdvisoryFinding schema

Normative JSON Schema; on implementation this lands as `schemas/advisory-finding.schema.json`
(and is referenced from the decision-snapshot and interrupt-resume schemas).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "ua:advisory-finding",
  "type": "object",
  "required": ["finding_id", "category", "severity", "claim", "evidence"],
  "additionalProperties": false,
  "properties": {
    "finding_id":  {"type": "string", "pattern": "^ADV-[0-9]{3}$"},
    "category":    {"enum": ["consistency", "plausibility", "completeness",
                             "fraud_signal", "income_quality", "collateral_quality"]},
    "severity":    {"enum": ["info", "attention", "significant"]},
    "claim":       {"type": "string", "minLength": 20, "maxLength": 400,
                    "description": "One-sentence, specific, falsifiable statement."},
    "evidence":    {"type": "array", "minItems": 1, "maxItems": 6,
                    "items": {"type": "object",
                              "required": ["kind", "ref"],
                              "additionalProperties": false,
                              "properties": {
                                "kind":  {"enum": ["document", "extracted_field", "lineage"]},
                                "ref":   {"type": "string"},
                                "quote": {"type": "string", "maxLength": 300}}}},
    "suggested_condition": {"type": ["string", "null"], "maxLength": 400,
                            "description": "Draft wording only; becomes a condition ONLY via human accept_condition."},
    "confidence":  {"type": "string", "pattern": "^0\\.[0-9]{1,2}$|^1\\.0$"}
  }
}
```

Semantics:

- **`severity`** drives one behavior only: `significant` findings must be disposed before an
  approve/counteroffer resume is accepted (FR-ADV-10). It never feeds the suggested action.
- **`evidence.ref`** resolution: `document` → a `document_id` in the package; `extracted_field`
  → a persisted extracted-field id; `lineage` → an existing lineage ref (resolvable via
  `GET /lineage/{id}/{ref}`). The UI renders each as a click-through chip.
- **`finding_id`** is assigned deterministically post-validation (`ADV-001…` in presentation
  order), not by the LLM.

Persistence (amends `04-domain-model.md` DDL on adoption):

```sql
CREATE TABLE advisory_findings (          -- immutable after insert
  application_id TEXT NOT NULL,
  run_seq        INTEGER NOT NULL,        -- same seq family as decision_snapshots
  finding_id     TEXT NOT NULL,           -- ADV-001…
  payload        TEXT NOT NULL,           -- canonical JSON of the schema object
  prompt_id      TEXT NOT NULL, prompt_version INTEGER NOT NULL,
  model_id       TEXT NOT NULL,
  created_at     TEXT NOT NULL,
  PRIMARY KEY (application_id, run_seq, finding_id)
);
CREATE TABLE advisory_dispositions (      -- separate: findings stay immutable
  application_id TEXT NOT NULL,
  run_seq        INTEGER NOT NULL,
  finding_id     TEXT NOT NULL,
  disposition    TEXT NOT NULL CHECK (disposition IN
                   ('accept_condition','accept_note','dismiss')),
  reason         TEXT,                    -- required when dismissing 'significant'
  disposed_by    TEXT NOT NULL,
  disposed_at    TEXT NOT NULL,
  PRIMARY KEY (application_id, run_seq, finding_id)
);
```

Both tables live in `loans.db`. Append-only enforcement for the corresponding **audit events**
is already provided by the ledger; these tables are operational reads for the UI.

New audit event types (amends the `audit-event` schema enum):
`advisory_findings_produced` (count, truncated_count, findings hash, prompt/model pins),
`advisory_finding_rejected` (grounding failure detail), `advisory_finding_disposed`
(finding_id, disposition, reason, actor).

---

## 6. Pipeline and packet integration (amends `09-agent-graph.md`)

```
… → condition_synthesis → advisory_review → prepare_decision → [interrupt] human_review → …
```

- `advisory_review` is **failure-isolated**: any exception inside it is caught, audited
  (`advisory_findings_produced` with `status=unavailable`), and the run proceeds (FR-ADV-7).
- Graph topology invariants are unchanged: the node is on the single mandatory path; it cannot
  route around the human gate (T-TOP-1 still holds).
- **State budget:** `UnderwritingState` gains only `advisory_status: str` and
  `advisory_count: int` (< 32 KB rule unaffected). Full findings are served over REST and
  embedded in the decision packet.

Decision-packet addition (amends the interrupt packet contract):

```json
"advisory": {
  "status": "findings | clean | unavailable",
  "findings": [ …schema §5 objects, ≤ 12… ],
  "undisposed_significant": ["ADV-002"]
}
```

Resume-payload addition (amends `schemas/interrupt-resume.schema.json`):

```json
"advisory_dispositions": [
  {"finding_id": "ADV-001", "disposition": "accept_condition"},
  {"finding_id": "ADV-002", "disposition": "dismiss", "reason": "Deposit sourced via …"}
]
```

`validate_resume` additions (all deterministic): unknown `finding_id` → reject; duplicate
disposition → reject; undisposed `significant` finding on approve/counteroffer → reject
(re-present with `validation_errors`, the existing loop); `dismiss` of `significant` without
`reason` → reject. Declines and suspends do NOT require dispositions (the file is not moving
forward on the strength of an unreviewed advisory).

API additions (amends `12-api-contracts.md`):

- `GET /loans/{id}/advisory` → `{run_seq, status, findings[], dispositions[]}` (latest run;
  `?seq=` for history, mirroring `/decisions`).
- Findings and dispositions also appear inside `GET /loans/{id}/decision` and `/decisions`
  entries via the snapshot's sealed advisory block.

---

## 7. Workbench UI (amends `13-frontend-workbench.md`)

- **Advisory panel** on the loan deep-dive (its own tab or a section on the Decision tab):
  header text `AI ADVISORY — NOT PART OF ELIGIBILITY`; one card per finding showing severity
  (text label: `INFO` / `ATTENTION` / `SIGNIFICANT`), category, claim, and evidence chips —
  each chip opens the existing lineage popover (`lineage` kind) or the document/extracted-field
  view. Styling must be visibly distinct from rule results (advisory cards use a neutral border,
  never the pass/fail palette).
- **DecisionGate additions:** when the packet carries findings, the gate lists them with
  disposition controls per finding (`Accept as condition` — pre-filled editable text from
  `suggested_condition`; `Record as note`; `Dismiss` — reason textarea appears when the finding
  is `significant`). The submit button is enabled regardless; server-side validation re-presents
  on violations (client mirrors the rule as a courtesy, server remains authoritative —
  consistent with four-eyes handling).
- **Audit timeline:** the three new event types render with text TYPE_TAGs
  (`ADVISORY`, `ADVISORY-REJECTED`, `ADVISORY-DISPOSED`).
- No emojis or pictographs anywhere in the advisory surfaces.

---

## 8. Prompt and synthetic-data amendments

### 8.1 Prompt spec (lands as `prompts/advisory/coherence-critic.v1.yaml`)

```yaml
id: advisory/coherence-critic
version: 1
model_params: {temperature: 0, max_tokens: 2048}
output_schema: { "$ref": "ua:advisory-finding (array wrapper)" }
template: |
  You are a senior mortgage underwriter performing a second-look coherence review of a
  complete, already-analyzed loan file. Deterministic systems have already computed all
  ratios and evaluated all guidelines; a human underwriter will make the decision.

  Your ONLY job: identify cross-document inconsistencies, implausibilities, or gaps that
  field-level checks cannot see. You MUST NOT recommend an action, score the loan, or
  restate rule results as findings.

  For every finding: one specific, falsifiable claim, citing the document ids /
  extracted-field ids / lineage refs it rests on. If you cannot cite evidence from the
  provided case file, do not report it. If the file is coherent, return {"findings": []}.

  Return ONLY JSON: {"findings": [ …schema… ]}.

  <case_file>{{payload_json}}</case_file>
```

Registered in `prompts/registry.json` under `active`; pinned into every snapshot per HR-7.
Prompt changes require rerunning the advisory golden gate (§9) before activation.

### 8.2 Synthetic data (amends `14-synthetic-data.md`)

- Each golden archetype gains an `advisory_ground_truth` sidecar (possibly empty), consumed by
  the mock provider's `advise()`.
- **Two archetypes gain planted cross-document inconsistencies** with known expected findings,
  e.g.: (16) *gift-letter/deposit mismatch* — gift letter states $25,000 from a relative, bank
  statement shows a $25,000 deposit 10 days before the letter's date with a wire descriptor
  inconsistent with the donor (expected: `consistency`/`significant`); (17) *occupancy
  commentary conflict* — URLA states owner-occupied, appraisal commentary notes tenant present
  (expected: `fraud_signal`/`attention`, corroborating the deterministic occupancy red flag,
  never replacing it). Both archetypes MUST still produce the same deterministic decision with
  the critic disabled (T-ADV-2 anchors).
- Corpus generation is unchanged (advisory sidecars default empty for the 500-corpus; corpus
  regression asserts decision invariance, not advisory content).

---

## 9. Testing and acceptance (amends `15-testing-acceptance.md`)

| ID | Test | Asserts |
|---|---|---|
| T-ADV-1 | static isolation scan | no module under `policy_engine/`, `aus/`, `domain/`, nor the suggested-action/adverse-action paths, imports the advisory store or references its tables (mirror of T-ISO-1) |
| T-ADV-2 | decision invariance | all golden archetypes + a 50-loan corpus sample run twice (critic enabled with mock findings vs. critic disabled): rule results, suggested action, eligible reason codes, conditions from `condition_synthesis`, AUS result, and adverse-action content are **byte-identical**; only the advisory block and its audit events differ |
| T-ADV-3 | grounding rejection | mock returns a finding citing a nonexistent document id → finding absent from packet/store; `advisory_finding_rejected` event present with the failing ref |
| T-ADV-4 | disposition gate | archetype 16: approve resume without disposing the `significant` finding → re-presented with validation error; dismissing it without a reason → re-presented; valid dispositions → run completes, `advisory_finding_disposed` events written, accepted condition appears as a human-added condition |
| T-ADV-5 | snapshot + replay | sealed advisory block present in the snapshot; replay reproduces the decision byte-exactly **without any `advise()` invocation** (spy asserts zero calls); tampering with the sealed advisory block fails snapshot verification |
| T-ADV-6 | demographics containment | spy on the critic payload across archetypes: no demographic field name or value ever present (extends T-ISO-1 fixtures) |
| T-ADV-7 | failure isolation | provider `advise()` raises / times out / returns invalid JSON twice → run reaches the gate normally; packet carries `advisory.status=unavailable`; seal succeeds |
| T-ADV-8 | cap + dedupe | mock returns 20 findings incl. duplicates → ≤ 12 persisted, severity-ordered, `truncated_count` recorded |

**Live-provider eval gate** (extends `10 §6` swap gates): run the critic over the 15 golden
archetypes with the live provider — archetypes 16/17 must each yield ≥ 1 finding whose evidence
set intersects the planted ground truth; archetypes with empty `advisory_ground_truth` must
yield only findings that survive grounding validation (hallucination ceiling: 0 unresolvable
citations reaching the packet, by construction). Record findings-per-archetype and category
distribution in the eval report (FR-ADV-12).

**Acceptance:** all T-ADV green + full existing suite green + corpus regression unchanged +
a browser walkthrough (archetype 16: finding rendered with working evidence chips → blocked
approve → disposition → completed run → advisory block visible in decision history and audit
timeline).

---

## 10. Implementation plan (Phase P8, amends `16-implementation-plan.md`)

| Step | Work | Gate |
|---|---|---|
| P8.1 | Schema + DDL + audit event types + `advise()` on protocol/mock; archetypes 16–17 + sidecars | schema validates; mock returns sidecars; existing suite green |
| P8.2 | `build_advisory_view` + `advisory_review` node + grounding validation + cap/dedupe + failure isolation | T-ADV-1/2/3/6/7/8 green |
| P8.3 | Packet/resume/`validate_resume` + snapshot sealed block + `/advisory` endpoint + decision-history integration | T-ADV-4/5 green |
| P8.4 | Workbench advisory panel + DecisionGate dispositions + audit-timeline tags | browser walkthrough per §9 |
| P8.5 | Live-provider path in `ua_anthropic.py` (`advise()`), prompt v1 registered, eval gate run | live eval report committed |

Estimated runtime impact per loan: +1 LLM call (mock: negligible; live: ~10–30 s for a full
case-file read). Decision latency at the human gate is unaffected — the critic completes before
the interrupt is raised, and on timeout the gate opens without it.

---

## 11. Compliance posture (amends `02-compliance-matrix.md` on adoption)

| Concern | Why the advisory lane is safe |
|---|---|
| ECOA/Reg B reason accuracy | Findings never enter eligibility or adverse action (HR-11, T-ADV-1/2). Stated reasons remain rule-trace-derived (HR-10 unchanged). |
| Reproducibility / exam defense | Findings are sealed as display artifacts with prompt+model pins; replay verifies them as bytes and never re-invokes the LLM (FR-ADV-11, T-ADV-5). |
| Fair lending | Demographics never reach advisory prompts (FR-ADV-6, T-ADV-6); decision invariance is proven per corpus run (T-ADV-2), so advisory adoption cannot introduce outcome disparity. Disposition events give fair-lending analytics a record of *what the human saw and did* — strengthening, not weakening, the file. |
| GSE AI mandates (LL-2026-04 / 2025-16) | The critic is a new AI-inventory entry (register row 13) with documented purpose, inputs, failure mode, and human-in-the-loop consumption; disposition audit satisfies "document AI influence on the file". |
| SR 26-2 / OCC 2026-13 | Acceptance-rate monitoring from ledger events (FR-ADV-12); versioned prompt with eval gate before activation. |
| UDAAP / explainability | Every finding is evidence-cited and falsifiable by construction (grounding validation); un-cited output is structurally discarded. |
