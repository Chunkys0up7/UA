# 08 — AUS Simulator (DU-style)

Requirements covered: FR-AUS-1..4. A **deterministic, versioned scorer** that emulates the *shape* of Fannie Mae Desktop Underwriter output (recommendation + verification messages) so the workbench and decision packet look and behave like real underwriting. It is explicitly a simulation — the adapter protocol (`03 §6`) lets a real AUS integration replace it on the internal network.

**It is advisory only (FR-AUS-4).** Its output never finalizes anything; the policy engine decides eligibility and the human decides the action.

---

## 1. Position in the pipeline

Runs after `rules_eval` (it consumes the same evaluation context + rules rollup). Output persisted as `AusFindings` + `AusMessage[]`, shown on the workbench AUS card, included in the decision packet.

## 2. Config (`policy/aus/du-sim.v1.json`, versioned — HR-7)

The file `policy-pack/aus/du-sim.v1.json` is **normative**; its shape:

```jsonc
{
  "simulator_version": "du-sim.v1",
  "risk_factors": {
    "credit_score":    {"kind": "bands_desc_gte", "bands": [[760, 0], [740, 2], [700, 5], [660, 10], [620, 16], [0, 28]]},
    "back_dti":        {"kind": "bands_asc_lte",  "bands": [["36.000", 0], ["43.000", 4], ["45.000", 7], ["50.000", 12], ["999", 25]]},
    "ltv":             {"kind": "bands_asc_lte",  "bands": [["60.00", 0], ["75.00", 2], ["80.00", 4], ["90.00", 8], ["95.00", 12], ["999", 22]]},
    "reserves_months": {"kind": "bands_desc_gte", "bands": [["12.0", -4], ["6.0", -2], ["2.0", 0], ["0.0", 3]]},
    "self_employed":   {"kind": "bool", "true": 3, "false": 0},
    "occupancy":       {"kind": "enum", "values": {"primary": 0, "second_home": 2, "investment": 4}},
    "red_flag_elevated_each": 4,          // points per elevated red flag
    "red_flag_critical_each": 12          // points per critical red flag
  },
  "thresholds": { "approve_max": 18, "refer_max": 34 },
  "eligibility_gate": "rules_rollup",     // ineligible rollup ⇒ Approve/Ineligible regardless of score
  "critical_flag_floor": "Refer with Caution",
  "messages": [ /* §4 table — trigger → message_id/category/template */ ]
}
```

Band semantics: `bands_desc_gte` — first band whose bound the value meets with ≥ (descending); `bands_asc_lte` — first band whose bound the value meets with ≤ (ascending). All arithmetic on Decimal strings.

## 3. Recommendation mapping (FR-AUS-1)

```
total = Σ factor points
if rules rollup == "ineligible":            recommendation = "Approve/Ineligible"  (risk acceptable path shown for transparency)
elif total <= approve_max and rollup == "eligible":  "Approve/Eligible"
elif total <= refer_max:                    "Refer with Caution"
else:                                       "Out of Scope"
Exception: any critical red flag ⇒ minimum "Refer with Caution".
```

The full factor-by-factor breakdown (`score_breakdown_json`) is persisted — the workbench shows exactly why the recommendation is what it is, and the DecisionSnapshot pins `simulator_version`.

## 4. Verification messages (FR-AUS-2)

Generated deterministically from findings; each has a stable `message_id` for condition-source linking:

| message_id | Trigger | Category | Text template |
|---|---|---|---|
| DU-VOE-01 | VOE ≠ verified for any borrower | PTD | Obtain verbal verification of employment within 10 business days of note date for {borrower}. |
| DU-INC-02 | income discrepancy > tolerance | PTA | Provide documentation supporting qualifying income of {amount} for {borrower}. |
| DU-AST-03 | unsourced large deposit | PTA | Source large deposit of {amount} dated {date} in account {account}. |
| DU-AST-04 | funds unseasoned | PTD | Document 60-day seasoning or acceptable source for funds used to close. |
| DU-CR-05 | credit report age > 90 days | PTD | Obtain updated credit report; current report expires prior to typical closing window. |
| DU-APP-06 | appraisal age > 90 days | PTD | Obtain appraisal update/recertification of value. |
| DU-MI-07 | LTV > 80 | PTF | Evidence of mortgage insurance coverage meeting program requirements. |
| DU-HOI-08 | always | PTF | Evidence of hazard insurance with acceptable coverage and mortgagee clause. |
| DU-TITLE-09 | always | PTF | Clear title commitment showing first-lien position. |
| DU-GIFT-10 | gift funds present | PTA | Executed gift letter and evidence of donor ability and transfer. |

## 5. Versioning & change control (FR-AUS-3)

Config is immutable per version (`du-sim.v1.json`, `v2`, …). The active version is named in env/pack constants, pinned into the run at start, recorded in `AusFindings.simulator_version` and the DecisionSnapshot. Changing weights = new file version + rerun of golden archetype expectations (T-AUS-1 goldens fail loudly on drift).
