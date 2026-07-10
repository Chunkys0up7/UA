# 05 — Loan Package Input Contract

Requirements covered: FR-PKG-1..5. The normative machine-readable contract is `schemas/loan-package.schema.json`; this document explains it and defines validation semantics. The package is the **complete underwriting submission**: everything the underwriter (agent) needs arrives here. There is no other input channel.

---

## 1. Design intent

The package mirrors what a processor hands to underwriting at a large bank: URLA-1003-shaped application data, tri-merge credit, stated income/assets/liabilities with processor-computed figures, and the document set. Two principles:

1. **Stated ≠ trusted (HR-8).** Stated/processor figures are hypotheses. The pipeline recomputes everything from documents; the package's `processor_computed` block exists precisely so discrepancies can be detected and surfaced.
2. **Self-contained.** Documents are embedded as text renderings (this reference implementation does not process binaries/images; a production swap to a vision pipeline changes only the extraction prompts — see `10 §3`).

## 2. Top-level shape

```jsonc
{
  "package_version": "1.0",
  "loan": {
    "amount": "640000.00", "purpose": "purchase",          // purchase|rate_term_refi|cash_out_refi
    "occupancy": "primary",                                 // primary|second_home|investment
    "loan_type": "conventional_conforming",
    "note_rate": "6.125", "term_months": 360,
    "mlo_nmls_id": "1234567",
    "county_high_cost": false
  },
  "property": {
    "address": {"street":"...","city":"...","state":"CA","zip":"...","county":"..."},
    "property_type": "sfr_detached",                        // sfr_detached|sfr_attached|condo|two_to_four_unit|manufactured
    "units": 1,
    "purchase_price": "800000.00",                          // null for refis
    "appraised_value": "805000.00",
    "appraisal_effective_date": "2026-06-20",
    "subordinate_liens": [{"balance":"0.00","kind":"heloc"}],
    "annual_taxes": "9600.00", "annual_hazard_insurance": "1800.00",
    "monthly_hoa": "0.00", "flood_zone_sidecar": "X"        // consumed by sim adapter only
  },
  "borrowers": [{
    "borrower_id": "b1", "full_name": "...", "ssn": "###-##-####", "dob": "1988-04-02",
    "is_primary": true, "self_employed": false,
    "employment": [{"employer":"...", "position":"...", "start_date":"2019-03-01",
                    "monthly_base_income_stated":"9200.00",
                    "distance_to_property_miles_sidecar": 12}],   // consumed by sim geo adapter only
    "stated_other_income": [{"type":"bonus","monthly_amount":"600.00","history_months":30}],
    "voe_sidecar": {"result":"verified"}                    // consumed by sim adapter only
  }],
  "credit": {                                               // tri-merge, structured
    "report_date": "2026-06-28", "permissible_purpose": "credit_transaction",
    "scores": [{"borrower_id":"b1","equifax":761,"experian":768,"transunion":755}],
    "tradelines": [{"kind":"auto_loan","monthly_payment":"480.00","balance":"18000.00","dispute":false, "derog":null}],
    "derogatories": [], "open_disputes": 0,
    "score_range": {"low": 300, "high": 850},
    "key_factors": ["Proportion of balances to credit limits is too high", "..."]  // up to 4, per bureau feed
  },
  "assets": {
    "accounts": [{"account_id":"a1","kind":"checking","balance":"92000.00",
                  "statements_doc_ids":["d7","d8"]}],
    "retirement_accounts": [{"kind":"401k","vested_balance":"150000.00"}],
    "down_payment_source": "checking a1", "gift_funds": []
  },
  "liabilities_stated_monthly_total": "1480.00",
  "processor_computed": {                                   // recomputed, never trusted (HR-8)
    "front_dti": "31.2", "back_dti": "42.9", "qualifying_income_monthly": "10300.00"
  },
  "documents": [{
    "doc_id": "d1", "doc_type": "paystub", "borrower_id": "b1", "period_label": "2026-06",
    "text_rendering": "ACME CORP — Earnings Statement ... Gross Pay 4,600.00 ...",
    "ground_truth": {"gross_pay_period":"4600.00","pay_frequency":"semi_monthly","ytd_gross":"55200.00"}
  }],
  "hmda_demographics": {                                    // stripped at intake (HR-6)
    "b1": {"ethnicity":"not_hispanic","race":"white","sex":"female","age_band":"35-44"}
  }
}
```

Full field-by-field definitions, enums, and required/optional status: `schemas/loan-package.schema.json`.

## 3. Required document coverage (validated structurally)

| Situation | Required documents |
|---|---|
| Any W-2 borrower | ≥1 recent `paystub` + 2 tax years of `w2` |
| `self_employed: true` | 2 years `tax_return_1040` + 2 years `schedule_c` |
| Bonus/commission/overtime income claimed | documents establishing ≥ history (paystubs w/ YTD, W-2s) |
| Rental income claimed | `lease` (or Schedule E within `tax_return_1040`) |
| Any asset account used | 2 months `bank_statement` per account |
| Gift funds | `gift_letter` |
| Always | `tri_merge_credit`, `appraisal`, `urla_1003` |

Missing coverage is **not** an API rejection — it is accepted and produces conditions/red flags in the pipeline (that is an underwriting finding, not a malformed package). Structural rejection (§4) is reserved for packages the pipeline cannot process at all.

## 4. Validation semantics (FR-PKG-1, -2, -4)

**Tier 1 — schema validation (reject with 422):** JSON Schema conformance; enums; `Decimal`-parsable money strings; date formats.

**Tier 2 — referential integrity (reject with 422):**
- every `documents[].borrower_id`, `assets.accounts[].statements_doc_ids[]`, and `gift_funds[].gift_letter_doc_id` resolves;
- exactly one primary borrower; ≥1 borrower with scores in `credit.scores`;
- `purchase_price` present iff `purpose == "purchase"`;
- `units` consistent with `property_type` (`two_to_four_unit` ⇔ units 2–4; all other types ⇔ units 1);
- no duplicate `doc_id` / `account_id` / `borrower_id`;
- `loan.amount > 0`, `term_months ∈ {120..480}`.

Rejections return the error envelope (12 §2) with a `violations[]` list; **no rows are written** (FR-PKG-4).

**Tier 3 — underwritability findings (accept; surfaced by pipeline):** missing document coverage (§3), stale credit report (> 120 days), stale appraisal (> 120 days), etc. These become conditions/red flags, mirroring how a real underwriter suspends rather than refuses the file.

## 5. Intake side effects (FR-PKG-3, -5)

On acceptance: assign ULID `application_id`; persist immutable `package_json` copy; strip `hmda_demographics` into the isolated table; pin `policy_pack_version` from `POLICY_PACK` env; set status `received` + timestamp; append audit events `state_change:received` and `package_accepted` (payload: package sha256, document count, pack version pinned).
