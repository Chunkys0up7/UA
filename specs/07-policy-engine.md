# 07 — Policy Engine & Rule Packs

Requirements covered: FR-POL-1..8, HR-1, HR-7, HR-10. The engine is the **only** component that produces eligibility outcomes. Machine-readable pack: `specs/policy-pack/conforming-2026.1.0/` (normative deliverable — the implementation ships it verbatim under `policy/packs/`).

---

## 1. Role and boundaries

- Consumes: persisted `TracedValue`s assembled into a flat **evaluation context** (dot-path keyed, §3).
- Produces: one `RuleEvaluationRecord` per rule (FR-POL-3) + a rollup (`eligible | ineligible | refer`, failed rules, eligible reason codes, counteroffer hints).
- Never reads: raw documents, LLM output not yet persisted as human-verifiable `ExtractedField`s, demographics (HR-6), the clock, or the network.
- Determinism: same context + same pack ⇒ identical records, byte-for-byte (basis of replay, HR-5).

## 2. `RulesEngine` protocol (FR-POL-8)

```python
class RulesEngine(Protocol):
    def load_pack(self, pack_dir: Path) -> PolicyPack: ...          # verifies manifest (FR-POL-2)
    def evaluate(self, pack: PolicyPack, context: EvalContext) -> RulesResult: ...

class RulesResult(BaseModel):
    pack_version: str
    evaluations: list[RuleEvaluation]      # every rule, incl. passes
    overall: Literal["eligible", "ineligible", "refer"]
    failed_rule_ids: list[str]
    eligible_reason_codes: list[str]       # codes bound to failed rules (decision-gate picker source)
    counteroffer_hints: list[CounterofferHint]
```

The shipped implementation is `JsonRulesEngine` (custom, ~400 lines). ADR: GoRules ZEN was considered and rejected because its trace output is engine-shaped, not lineage-shaped; a translation layer would rival the evaluator's size. The protocol keeps ZEN substitutable.

## 3. Evaluation context

Built by `rules_eval` node from persisted rows; keys are dot-paths, values are `{value, lineage_ref}`:

```
loan.amount, loan.purpose, loan.occupancy, loan.units, loan.county_high_cost
ltv.ltv, ltv.cltv
dti.front_ratio, dti.back_ratio                          (percent scale, 3 dp)
income.qualifying_monthly, income.residual_monthly,
income.variable_included_under_12mo, income.discrepancies_exceeded,
income.se_history_months
credit.representative_score, credit.open_disputes, credit.bk7_months_since,
credit.fc_months_since, credit.late_mortgage_12mo, credit.report_age_days
assets.reserves_months, assets.unsourced_large_deposits, assets.unseasoned_funds,
assets.gift_funds_undocumented
compensating.count, compensating.factors[]               (computed per §7.6)
property.type, appraisal.age_days
```

Derivations (all measured against `as_of_date`, `06 §1`):

| Path | Derivation |
|---|---|
| `income.residual_monthly` | qualifying_monthly − PITIA − monthly_liabilities |
| `income.variable_included_under_12mo` | count of *included* variable components with history < 12 months (0 by construction — guard rule) |
| `income.discrepancies_exceeded` | count of exceeded income discrepancies (`06 §7` rows 1–2) |
| `income.se_history_months` | months from the self-employed borrower's earliest `employment[].start_date` to `as_of_date`; absent if no SE borrower |
| `credit.bk7_months_since` | min `months_since` over derogatories `kind=bk7_discharge`; absent if none |
| `credit.fc_months_since` | min `months_since` over derogatories `kind=foreclosure`; absent if none |
| `credit.late_mortgage_12mo` | Σ `late_30_count_12mo` over tradelines `kind=mortgage` |
| `assets.unseasoned_funds`, `assets.gift_funds_undocumented` | `06 §5.1` |
| `credit.report_age_days`, `appraisal.age_days` | as_of_date − report/effective date |

Referencing a missing key ⇒ rule outcome `refer` with reason code `RC-DATA-MISSING` (never a crash, never a silent pass).

## 4. Rule schema (normative: `schemas/rule.schema.json`)

```jsonc
{
  "id": "DTI-001",                       // unique across pack; prefix = ruleset
  "description": "Back-end DTI ≤ 45%, or ≤ 50% with ≥2 compensating factors",
  "inputs": ["dti.back_ratio", "compensating.count"],
  "when": { "or": [                       // predicate AST, §4.1
      { "<=": ["dti.back_ratio", "45.0"] },
      { "and": [ { "<=": ["dti.back_ratio", "50.0"] },
                 { ">=": ["compensating.count", 2] } ] } ] },
  "on_fail": {
    "outcome": "ineligible",             // ineligible | refer
    "reason_code": "RC-DTI-EXCESSIVE",   // REQUIRED (FR-POL-4)
    "counteroffer": { "solve_for": "loan.amount",
                      "target": { "<=": ["dti.back_ratio", "45.000"] } }   // optional (§4.3)
  },
  "severity": "eligibility"              // eligibility | documentation | informational
}
```

### 4.1 Predicate AST
Operators: `and`, `or`, `not`, `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `absent`, `present`, and `table` (§4.2). Comparison operands: dot-path strings (context lookup) or literals; numeric literals written as strings are parsed as `Decimal`. No user-defined functions, no side effects — the AST is data.

### 4.2 Lookup tables & derived inputs
```jsonc
{ "table": {
    "from": "max_ltv",                   // table defined in the same rules file
    "select": "max_ltv",
    "match": {"purpose_group": "purpose_group", "occupancy": "loan.occupancy", "units_group": "units_group"} } }
```
Tables make limit changes data-only (loan limits, LTV matrix, reserves). Match values are resolved first against the file's `derived_inputs`, then the evaluation context.

**`derived_inputs`** (file-scoped) map a context path through a case table:
```jsonc
"derived_inputs": {
  "units_group": {"map": "loan.units", "cases": {"1": "1", "2": "2", "3": "3_4", "4": "3_4"}}
}
```
The mapped context value is stringified (`str(value)`) before case lookup; an unmapped case, like a match tuple with no table row, makes the referencing rule evaluate to `refer` with `RC-DATA-MISSING` — a table **miss is never a pass and never a crash** (e.g., a 2-unit second home finds no `max_ltv` row and refers for manual review).

### 4.3 Counteroffer hints (FR-POL-7)
When a failed rule declares `counteroffer.solve_for = "loan.amount"`:
- If the target is a **direct comparison on the solve_for path itself** (e.g., LIMIT-001's `loan.amount ≤ table(limit)`), the hint is that bound exactly (e.g., `832750.00`).
- Otherwise the engine binary-searches the largest loan amount at **$1,000 granularity** (recomputing P&I → PITIA → DTI via injected pure calculators) satisfying the target, holding all else constant (e.g., archetype #10 → `429000.00`).
Result: `CounterofferHint{rule_id, parameter, max_value, achieved_ratio}`. Purely deterministic.

### 4.4 Rollup
- `ineligible` if any `severity=eligibility` rule failed with `outcome=ineligible`;
- else `refer` if any `severity=eligibility` rule failed with `outcome=refer` (incl. eligibility-severity `RC-DATA-MISSING` misses);
- else `eligible`.

**Documentation- and informational-severity failures never affect the rollup** — they synthesize conditions (`09 §3.8`) and decision-packet context only. (This is why archetype #2 is AUS `Approve/Eligible` despite AST-002 referring.)

## 5. Pack versioning & integrity (FR-POL-2, -5, HR-7)

```
policy-pack/conforming-2026.1.0/
├── pack.json          # {"pack_id":"conforming","version":"2026.1.0","effective_date":"2026-01-01",
│                      #  "files": {"dti.rules.json":"<sha256>", ...}}  ← manifest
├── loan-limits.rules.json · ltv-matrix.rules.json · dti.rules.json · credit.rules.json
├── income.rules.json · assets.rules.json · property.rules.json
├── compensating-factors.json · reason-codes.json · constants.json
```

- Loader computes each file's sha256 and compares to the manifest; any mismatch ⇒ abort with `PolicyPackIntegrityError` (T-POL-2).
- Version scheme `<year>.<major>.<minor>`; released packs are immutable — any change is a new directory (FR-POL-5).
- Load-time validation: every `on_fail.reason_code` exists in `reason-codes.json` (FR-POL-4); every input path is in the documented context vocabulary; every table `match` is resolvable.
- The pack version + manifest-root hash go into every `RuleEvaluationRecord`, audit event, and the DecisionSnapshot.

## 6. Reason codes (`reason-codes.json`) (HR-10)

The machine-readable file `policy-pack/conforming-2026.1.0/reason-codes.json` is **normative** — its `ecoa_text` strings are the exact adverse-action notice strings (T-AAN-1 asserts string equality against that file, not against any prose excerpt). Structure per code:

```jsonc
{ "RC-DTI-EXCESSIVE": {
    "ecoa_text": "Income insufficient for amount of credit requested; excessive obligations in relation to income",
    "hmda_denial_code": 1,
    "category": "capacity" } }
```

Codes defined (see the file for exact texts): `RC-DTI-EXCESSIVE`, `RC-INCOME-UNVERIFIABLE`, `RC-INCOME-HISTORY`, `RC-CREDIT-SCORE`, `RC-CREDIT-DISPUTE`, `RC-CREDIT-HISTORY`, `RC-LTV-EXCESSIVE`, `RC-PROPERTY-INELIGIBLE`, `RC-RESERVES-INSUFFICIENT`, `RC-ASSETS-UNSOURCED`, `RC-DATA-MISSING`, `RC-LIMIT-EXCEEDED`.

## 7. `conforming-2026.1.0` pack content (FR-POL-6) — normative highlights

Full rules in `specs/policy-pack/`. The engine input vocabulary contains **only** guideline financial variables — no geography beyond high-cost-county boolean (a federal limit parameter), no behavioral or demographic data (fair-lending control, `02 §4`).

- **LIMIT-001**: loan amount ≤ conforming limit by units × high-cost flag. 2026 baseline (1-unit): $832,750; high-cost: $1,249,125; 2-unit $1,066,350/$1,599,150; 3-unit $1,289,200/$1,933,650; 4-unit $1,602,050/$2,402,650. Fail ⇒ `RC-LIMIT-EXCEEDED` (ineligible — jumbo out of program).
- **LTV-001**: LTV ≤ matrix: purchase/rate-term — 1-unit primary 95; 2-unit primary 95 (85 manual note); 3–4-unit primary 80 *(pack uses the conservative manual bound)*; second home 90; 1-unit investment 85; cash-out — primary 80, second/investment 75, 2–4-unit 75. Fail ⇒ `RC-LTV-EXCESSIVE`, counteroffer `solve_for loan.amount`.
- **LTV-002**: CLTV ≤ same matrix + 0 (no CLTV allowance in v1).
- **DTI-001**: back ≤ 45, or ≤ 50 with `compensating.count ≥ 2`. Fail ⇒ `RC-DTI-EXCESSIVE` + counteroffer hint.
- **DTI-002** *(informational)*: front > 38 flags a documentation-severity note.
- **CR-001**: representative score ≥ 620. Fail ⇒ `RC-CREDIT-SCORE`.
- **CR-002**: open credit disputes == 0. Fail ⇒ `RC-CREDIT-DISPUTE` (ineligible — mirrors AUS behavior).
- **CR-003**: BK Ch.7 discharge ≥ 48 months; **CR-004**: foreclosure ≥ 84 months; **CR-005**: mortgage lates (30d) in last 12 months == 0 (fail ⇒ refer).
- **INC-001**: qualifying income > 0 verified (`RC-INCOME-UNVERIFIABLE`); **INC-002**: variable income history ≥ 12 months to include; **INC-004**: SE history ≥ 24 months (fail ⇒ refer `RC-INCOME-HISTORY`).
- **AST-001**: reserves ≥ matrix (primary 1-unit: 0 mo; 2–4-unit: 6; second home: 2; investment: 6). Fail ⇒ `RC-RESERVES-INSUFFICIENT`.
- **AST-002**: unsourced large deposits == 0 (fail ⇒ documentation severity → condition; if still unsourced at gate, human may decline w/ `RC-ASSETS-UNSOURCED`).
- **AST-003**: funds seasoned ≥ 60 days or sourced (documentation severity).
- **PROP-001**: property type ∈ eligible set (manufactured ⇒ refer in v1) — `RC-PROPERTY-INELIGIBLE`.
- **DOC-001/002** *(documentation)*: credit report ≤ 120 days; appraisal ≤ 120 days.

### 7.6 Compensating factors (`compensating-factors.json`)
Counted when: representative score ≥ 740; reserves ≥ 6 months; LTV ≤ 75; residual income ≥ $2,500/mo (income − PITIA − liabilities). `compensating.count` = number satisfied, each with lineage to its basis.
