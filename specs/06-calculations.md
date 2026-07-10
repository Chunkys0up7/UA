# 06 — Calculations

Requirements covered: FR-CAL-1..8, FR-VER-1..3, FR-FRD-1..2, FR-EXT-5, NFR-1, NFR-2. All functions live in `backend/app/domain/calculations/` (+ `domain/atr.py`) and are **pure**: no IO, no clock, no randomness (FR-CAL-8). Inputs and outputs are `TracedValue`s; each function creates a `calculation` lineage node whose `parents` are its operands' refs (FR-CAL-7).

**Numeric rules (NFR-2):** `decimal.Decimal` everywhere; context `ROUND_HALF_EVEN` (banker's). DTI ratios are computed, stored, and compared in **percent scale to 3 dp** (e.g., `"48.500"`), displayed to 1 dp — the pack thresholds (`"45.000"`, `"50.000"`) and the boundary sweep (`44.999/45.000/45.001`) use this same scale. LTV/CLTV are percent scale, rounded **up** (`ROUND_CEILING`) to 2 dp — conservative. Currency to 2 dp. Floats are forbidden in `domain/` (ruff rule + T-CAL-1 checks no `float` annotations/literals in money paths).

**As-of anchor:** every age/recency computation (`credit.report_age_days`, `appraisal.age_days`, deposit seasoning, employment history months) is measured against `as_of_date = date(received_at)` — persisted at intake, never the wall clock. This keeps `domain/` clock-free and makes replay byte-identical (HR-5).

---

## 1. Conventions

Each subsection defines: **Inputs → Algorithm → Lineage → Worked example**. Worked examples are normative — they double as golden-test vectors (`backend/tests/golden/calculations.json` must contain exactly these cases among others).

## 2. Qualifying income (FR-CAL-1)

Computed **per IncomeComponent per borrower**, then summed to loan level. `calc_method` recorded on each component.

### 2.1 Base salary (W-2)
- Inputs: extracted `gross_pay_period` + `pay_frequency` from most recent paystub; YTD gross; prior-2-year W-2 box-1 values.
- Algorithm: `monthly = gross_pay_period × frequency_factor` where factor = {weekly: 52/12, biweekly: 26/12, semi_monthly: 2, monthly: 1}. Consistency check: annualized vs current-year W-2 pace within ±2% (else Discrepancy, §7).
- Example: semi-monthly $4,600.00 → `4600 × 2 = 9,200.00/mo`.

### 2.2 Overtime / bonus / commission
- If documented history ≥ 24 months: `monthly = (year1_total + year2_total) / 24`, and if the trend is declining > 20% year-over-year, use the recent year only ÷ 12 and add red flag `RF-INC-DECLINING`.
- If 12–23 months history: `monthly = YTD_total annualized × 0.75 / 12` (75% haircut), method `75pct_ytd`.
- If < 12 months: excluded (`included=0`, `exclusion_reason="insufficient_history"`).
- Example: bonus year1 $8,400, year2 $7,800 → `(8400+7800)/24 = 675.00/mo`.

### 2.3 Self-employed (Schedule C)
- Inputs: 2 years Schedule C net profit; add-backs: depreciation, depletion, business-use-of-home, amortization/casualty (extracted line items).
- Algorithm: `annual_i = net_profit_i + addbacks_i`; if `annual_2 < annual_1 × 0.8` (decline > 20%): use `annual_2 / 12` and add `RF-INC-DECLINING`; else `monthly = (annual_1 + annual_2) / 24`.
- Example: 2024: 92,000 + 6,000 = 98,000; 2025: 101,000 + 5,500 = 106,500 → `(98000+106500)/24 = 8,520.83/mo`.
- Guard: business history < 24 months ⇒ component excluded + condition (rule INC-004 defers).

### 2.4 Rental
- **Subject-property rental income only (v1 scope):** for an investment-purchase subject property with a `lease` document, `monthly = gross_monthly_rent × 0.75`.
- Example: rent $2,400 → `1,800.00/mo`.
- Non-subject rental properties are out of scope in v1: their mortgage payments appear as `mortgage` tradelines in the credit report and are counted as liabilities; no offsetting rental income is credited.

### 2.5 Other (alimony/child support/pension/SS)
- Court-ordered support: include only if `history_months ≥ 3` and continuance ≥ 36 months stated; non-taxable income grossed up ×1.25 when `taxable:false`.

**Loan-level:** `qualifying_monthly_income = Σ included components` (lineage parents = all component refs).

## 3. DTI (FR-CAL-2)

- `PITIA = principal_interest + monthly_taxes + monthly_hazard + monthly_MI + monthly_HOA`.
- `principal_interest = amortized payment(loan_amount, note_rate/12, term_months)` — standard annuity formula evaluated in Decimal (round final to 2 dp): `P × r × (1+r)^n / ((1+r)^n − 1)`.
- `monthly_MI`: if LTV > 80.00, `loan_amount × mi_annual_rate / 12` (`mi_annual_rate` from pack `constants.json`, default `0.0055`), else `0.00`. Lineage: `constant_policy` node citing the pack version.
- `front = (PITIA / income) × 100`, `back = ((PITIA + monthly_liabilities) / income) × 100`; percent scale, 3 dp stored, 1 dp display.
- Monthly liabilities = Σ non-housing tradeline payments (credit report) + court-ordered obligations. Installment debts with ≤ 10 payments remaining MAY be excluded (recorded with method `excluded_le_10_payments`).
- **Worked example (golden):** loan $640,000 @ 6.125%, 360 mo → P&I `3,888.71`; taxes 800.00; hazard 150.00; MI 0 (LTV 80.00); HOA 0 → PITIA `4,838.71`. Income `11,195.83` (9,200 base + 675 bonus + 1,320.83 other). Liabilities `1,480.00`. Front = `4838.71/11195.83 = 43.219%` (43.2%); back = `6318.71/11195.83 = 56.438%` (56.4%). (This vector intentionally exceeds limits — it is archetype #10's basis; its counteroffer hint is `429000.00`, the largest $1,000 multiple with back ≤ 45.000: at 429,000, P&I 2,606.65, back 44.987.)

## 4. LTV / CLTV (FR-CAL-3)

- Purchase: `LTV = loan_amount / min(purchase_price, appraised_value)`. Refi: `/ appraised_value`.
- `CLTV = (loan_amount + Σ subordinate lien balances + Σ HELOC limits drawn) / same denominator`.
- Round **up** to 2 dp. Example: 640,000 / min(800,000, 805,000) = `0.80` → `80.00%`.

## 5. Reserves (FR-CAL-4)

- `funds_to_close = down_payment + estimated_closing_costs` (closing costs = `estimated_closing_cost_rate` × purchase price for purchases, × loan amount for refis; pack constant, `constant_policy` lineage).
- `available_funds = Σ liquid balances + Σ retirement vested balances × retirement_asset_haircut` (0.60 default, pack constant).
- `post_closing_available = available_funds − funds_to_close`.
- `reserves_months = post_closing_available / PITIA`, floor (ROUND_FLOOR) to 1 dp.
- Example: liquid 92,000 + retirement 150,000 × 0.6 = 90,000 → available 182,000; funds_to_close = 160,000 + 16,000 = 176,000 → post-closing 6,000 → `6000 / 4838.71 = 1.2 months`.

### 5.1 Seasoning & gift documentation inputs (rules AST-003 / AST-004)
- A deposit is **unseasoned** if `deposit_date` is within `asset_seasoning_days` (60) of `as_of_date` AND it is not sourced (`sourced=false`, no source document).
- `assets.unseasoned_funds` = `1` if `(Σ liquid balances − Σ unseasoned deposit amounts) < funds_to_close`, else `0` — i.e., the file *needs* unseasoned money to close.
- `assets.gift_funds_undocumented` = count of `gift_funds[]` entries where the referenced gift-letter document is missing, its extraction lacks `no_repayment_clause=true`, or `transfer_evidenced=false`.
- Both values carry lineage to the deposits/gift entries they were computed from.

## 6. Representative credit score (FR-CAL-5)

Per borrower: middle of 3 bureau scores; if 2, the lower; if 1, that score. Loan-level: **lowest** representative across borrowers. Example: (761, 768, 755) → 761; co-borrower (742, 749, 731) → 742; loan-level → `742`.

## 7. Verification & discrepancies (FR-VER-1..3, HR-8)

For each verifiable quantity, compare **stated** (package) vs **documented** (extracted). The tolerance values below are normative (FR-VER-2):

| Quantity | Tolerance | On breach |
|---|---|---|
| Base income (paystub-annualized vs stated) | ±2% | Discrepancy + use documented; condition if > 5% |
| W-2 vs tax-return wages | ±5% | Discrepancy; escalates to red flag `RF-INC-MISMATCH` only when VOE ≠ verified (see §9) |
| Account balance (statement vs stated) | max($100, 1%) | Discrepancy + use documented |
| Employment start (VOE vs stated) | 3 months | Discrepancy + condition `updated VOE` |
| Processor DTI vs recomputed DTI | ±0.5 pp | Discrepancy (informational — recomputed always governs) |

Rules: documented value **always** governs calculations; the discrepancy row records both values + tolerance + lineage; discrepancies never mutate the stored package (FR-VER-3).

## 8. ATR eight factors (FR-CAL-6)

`domain/atr.py` produces exactly 8 `AtrEvaluation` rows per run:

| # | Factor (12 CFR 1026.43(c)(2)) | Basis recorded | Evidence lineage |
|---|---|---|---|
| 1 | Current/expected income or assets | qualifying income computation | loan-level income ref |
| 2 | Current employment status | VOE adapter results per borrower | adapter_result refs |
| 3 | Monthly payment on this loan | P&I calculation | P&I ref |
| 4 | Monthly payment on simultaneous loans | subordinate liens | CLTV inputs ref |
| 5 | Mortgage-related obligations | taxes/insurance/HOA/MI | PITIA component refs |
| 6 | Current debts, alimony, support | liability rollup | liabilities ref |
| 7 | DTI or residual income | back-end DTI | back_ratio ref |
| 8 | Credit history | representative score + derogatories | credit profile refs |

A run that cannot populate a factor (e.g., VOE unavailable) still writes the row with `basis="unavailable — condition raised"` — the factor is *considered* and the gap surfaced (that is what the regulation requires).

## 9. Fraud screen rules (FR-FRD-1..2)

Deterministic, evaluated over persisted values; each hit emits a `RedFlag` with lineage:

| Code | Trigger | Severity |
|---|---|---|
| RF-OCC-DISTANCE | occupancy=primary AND property↔employer distance > 200 mi (`occupancy_distance_miles_flag` constant). Distance comes from the `GeoDistanceAdapter` (`03 §6`) — the sim implementation reads `employment[].distance_to_property_miles_sidecar` from the package; a production build swaps in a real geocoding service behind the same protocol | elevated |
| RF-OCC-INSURANCE | hazard policy type = landlord/rental while occupancy=primary | **critical** |
| RF-DEP-UNSOURCED | large deposit (> 25% qualifying monthly income, < 60 days old) with `sourced=false` | elevated |
| RF-DEP-PATTERN | ≥3 round-amount deposits (multiple of $500) within 45 days | elevated |
| RF-INC-MISMATCH | W-2↔tax-return wage variance > 5% (§7 row 2) AND VOE ≠ verified for that borrower | **critical** |
| RF-INC-DECLINING | YoY variable/SE income decline > 20% | info |
| RF-LIAB-UNDISCLOSED | credit tradeline monthly payment absent from stated liabilities by > $50 | elevated |
| RF-DOC-STALE | credit report or appraisal > 120 days old | info |

`critical` ⇒ decision packet `suggested_action = "suspend"` regardless of rule outcomes (FR-FRD-2). Severity/action mapping lives in pack constants (versioned).
