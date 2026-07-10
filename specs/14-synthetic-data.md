# 14 — Synthetic Data: Archetypes & Corpus

Requirements covered: FR-DAT-1..4, FR-EXT-4. All data is synthetic: names/SSNs/employers from seeded fake pools, SSNs always in the invalid `900-xx-xxxx` range. Generator: `backend/synthetic/` — a pure-Python, seeded (`random.Random(seed)`) package factory.

---

## 1. Generator design (FR-DAT-1, -4)

**Backwards construction:** archetypes specify *target outcomes* (e.g., back-DTI 48.5%, LTV 80%, score 742); the generator solves for the raw numbers (income, price, balances) that produce those targets through the real calculation algorithms in `06`, then renders documents whose text contains exactly those numbers, and writes `ground_truth` sidecars matching the renderings. Internal consistency is therefore by construction — the pipeline recomputing from documents lands on the target values.

**Determinism (FR-DAT-4):** the only entropy source is the seed; no wall clock (a fixed `base_date = 2026-06-30` anchors all relative dates); dict ordering fixed; output files serialized with sorted keys + `\n` line endings. Same seed → byte-identical files (T-DAT-1).

**CLI:**
```
python -m synthetic.generate --archetypes --out ../data/loans            # the 12 goldens (fixed seed 42)
python -m synthetic.generate --corpus --count 500 --seed 1337 --out ../data/generated
```

**Document renderers** (`renderers.py`): plain-text plausible layouts per doc type (paystub earnings statement, W-2 box layout, 1040/Schedule C line items, bank statement with transaction rows, appraisal summary page, URLA sections, gift letter, lease). Every number the extractor must find appears verbatim in the text; `ground_truth` mirrors it (mock provider contract, FR-EXT-4).

## 2. Package assembly invariants

- Paystub gross × frequency ≈ stated monthly base (within construction tolerance 0).
- W-2 wages = annualized paystub for stable-income archetypes; deliberately offset for mismatch archetypes.
- Bank statements contain the exact deposits the archetype requires (incl. large/round-pattern deposits) and end at the stated balance.
- Tri-merge scores chosen so the representative-score math (`06 §6`) hits the archetype's target.
- `processor_computed` values are the *correct* recomputation ± the archetype's specified processor error (default +0.2 pp on back DTI — exercising the discrepancy path without exceeding tolerance).

## 3. Ground-truth sidecars

Each document's `ground_truth` holds exactly the fields its extraction prompt's `output_schema` requires. The mock LLM returns them verbatim with confidence 0.99 (except archetypes that specify degraded confidence to exercise the review UX).

## 4. The 12 golden archetypes (FR-DAT-2) — committed at `data/loans/<name>.json`, seed 42

Expected outcomes are asserted by T-DAT-2 (rule outcomes, red flags, AUS recommendation, suggested action, condition set).

| # | Name | Construction targets | Expected: rules / flags / AUS / suggested action |
|---|---|---|---|
| 1 | `clean-approve` | 1-unit primary purchase; score 780 (761/780/792); back-DTI 32.0; LTV 75.0; reserves 8.0 mo; all docs clean, VOE verified | all rules pass / no flags / Approve/Eligible / **approve_with_conditions** (std PTF set: DU-HOI-08, DU-TITLE-09) |
| 2 | `conditional-approve` | as #1 but VOE `unavailable` + one $12,000 deposit (26% of income) unsourced, 30 days old | AST-002 refer / RF-DEP-UNSOURCED elevated / Approve/Eligible (risk points constructed ≤ 18) / **suspend** suggested (elevated red flag + unverified VOE, per 09 §3.9 rule 4) with DU-VOE-01 + DU-AST-03 conditions |
| 3 | `borderline-dti-compensating` | back-DTI 48.500 exactly; score 745; reserves 6.5 mo; LTV 74.0 → compensating.count = 3 (CF-SCORE, CF-RESERVES, CF-LTV) | DTI-001 passes via 50%-branch / no flags / Refer with Caution (DTI points) / **approve_with_conditions** |
| 4 | `self-employed` | Schedule C 2-yr avg $8,520.83/mo (98,000 & 106,500 with add-backs per 06 §2.3 example); 30-mo business history; back-DTI 41.0 | INC-004 passes / no flags / Approve/Eligible / **approve_with_conditions** |
| 5 | `bonus-income-short-history` | base + bonus with 14-mo history → 75% YTD haircut applied; back-DTI lands 44.5 (passes only because of haircut correctness) | INC-002 passes; DTI-001 passes / RF none / Approve/Eligible / **approve_with_conditions** — golden asserts the haircut math |
| 6 | `rental-investor` | investment purchase, 2-unit; lease $2,400 → 75% credit; LTV 74.0; reserves 7.0 mo; score 760 | all pass (investment reserve row) / no flags / Approve/Eligible / **approve_with_conditions** |
| 7 | `large-deposit-flag` | $14,000 round deposit (vs $9,000/mo income, 25%+), 20 days old, unsourced + two more $2,500 round deposits in 40 days | AST-002 refer / RF-DEP-UNSOURCED + RF-DEP-PATTERN elevated / Refer with Caution / **suspend** |
| 8 | `occupancy-fraud-flag` | primary-occupancy claim; `distance_to_property_miles_sidecar: 420`; hazard policy `landlord_rental` | rules pass numerically / RF-OCC-DISTANCE elevated + RF-OCC-INSURANCE **critical** / floor Refer with Caution / **suspend** (critical flag rule) |
| 9 | `decline-credit` | rep score 585 (590/585/579); one open dispute | CR-001 fail + CR-002 fail (ineligible) / no flags / Approve/Ineligible / **decline** — eligible_reason_codes = [RC-CREDIT-SCORE, RC-CREDIT-DISPUTE] |
| 10 | `decline-dti-counteroffer` | back-DTI 56.4 at requested $640,000 (the 06 §3 worked example); passes at ≤ $429,000 (06 §3 worked math) | DTI-001 fail w/ counteroffer hint max_value = 429000.00 / Approve/Ineligible / **decline** suggested, counteroffer available — golden asserts hint value ± $1,000 |
| 11 | `high-ltv-decline` | second home, LTV 93.0 (max 90) | LTV-001 fail / Approve/Ineligible / **decline**, counteroffer hint present |
| 12 | `jumbo-ineligible` | 1-unit standard county, amount $850,000 > $832,750 | LIMIT-001 fail / Approve/Ineligible / **decline** w/ RC-LIMIT-EXCEEDED, counteroffer hint = 832750 |

(Archetype #2's AUS expectation: constructed so risk points stay ≤ 18 — the golden asserts `Approve/Eligible` with the two conditions; the *suspend* suggestion comes from the elevated red flag and unverified VOE (09 §3.9), demonstrating that suggested action ≠ AUS recommendation.)

## 5. The corpus (FR-DAT-3) — `data/generated/`, gitignored

`--corpus --count 500 --seed 1337` produces:

- **Archetype mix:** 40% clean-approve variants, 15% conditional, 10% borderline-DTI, 10% self-employed/variable-income, 10% red-flag (deposit/occupancy), 15% decline family (credit/DTI/LTV/limit).
- **Boundary sweep (mandatory):** for every numeric threshold in the pack, ≥ 3 packages at exactly the threshold, one increment below, one above: DTI 44.999/45.000/45.001 and 49.999/50.000/50.001 (with and without 2 compensating factors); LTV 79.99/80.00/80.01 and per-matrix maxima; score 619/620/621 and 739/740/741; reserves at each matrix row; loan amount at limit−1/limit/limit+1 per units×high-cost cell; deposit at 24.9%/25.0%/25.1% of income. Generated by `boundary_cases()` and tagged `boundary=true` in a corpus manifest.
- **Corpus manifest** `data/generated/manifest.json`: seed, count, per-package archetype + expected-family tags → the regression runner joins actual decisions against expected families.

**Corpus regression run (T-DAT-3):** every package → full pipeline (mock provider) → auto-resume the gate with `action = suggested_action` (test-only auto-approver, clearly marked; four-eyes satisfied with a second synthetic reviewer) → all chains verify + all snapshots replay identical → decision-distribution report (`reports/corpus-run.json`): counts by suggested action, rule-failure frequencies, boundary-case correctness table. The report is diffable across pack/prompt versions (`02 §7` monitoring hook).
