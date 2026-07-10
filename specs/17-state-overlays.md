# 17 — State Overlay Rules

Requirements covered: FR-STA-1..7 (defined in `01-requirements.md §19`). Federal law is the floor, not the ceiling: state law adds underwriting constraints that vary by **property state**. This document specifies the overlay mechanism and the shipped `state-overlays-2026.1.0` pack. Machine-readable content: `specs/policy-pack/state-overlays-2026.1.0/`.

---

## 1. Design principles

1. **Overlays only tighten.** A state overlay can add rules (ineligible/refer/condition/disclosure) — it can never relax a base-pack rule. Where both speak to the same quantity, **most restrictive wins** by construction: overlay rules are additional predicates ANDed into the run; there is no override mechanism.
2. **Same engine, same trace.** Overlay rules use the identical rule schema (`schemas/rule.schema.json`), evaluate in the same `rules_eval` node, produce the same `RuleEvaluationRecord`s, bind reason codes the same way, and appear in the same decision packet, adverse-action pipeline, audit ledger, and DecisionSnapshot. Nothing about state law is special-cased downstream.
3. **Every state rule cites its authority.** Overlay rules carry a mandatory `citation` field (statute/regulation, e.g. `"Tex. Const. art. XVI §50(a)(6)"`). The citation renders in the workbench rules table and the audit record — an examiner can trace any state-driven outcome to its legal basis.
4. **State is a compliance key, not a risk factor (FR-STA-6).** `property.state` enters the evaluation context solely to select which state's LAW applies. Fair-lending posture (`02 §4`): state selection is facially lawful geographic distinction mandated by the states themselves; overlay rules MUST NOT price or risk-differentiate by state beyond what the cited statute requires, and the pack lint (T-SOV-2) rejects any overlay rule without a citation.
5. **Versioned like everything else.** The overlay pack has its own semver directory, sha256 manifest, immutability rule, and its version is pinned at intake alongside the base pack and recorded in every evaluation and the DecisionSnapshot (HR-7).

## 2. Pack layout

```
policy-pack/state-overlays-2026.1.0/
├── pack.json                  # {"pack_id":"state-overlays","version":"2026.1.0","files":{...sha256...}}
├── states-index.json          # state → rule files + flags (community_property, wet_funding,
│                              #   attorney_closing, disparate_impact_monitoring, adverse_action_extra)
├── tx.rules.json              # Texas 50(a)(6) home-equity rules
├── ny.rules.json              # New York subprime/high-cost + CEMA condition
├── nj.rules.json              # New Jersey HOSA high-cost
├── ma.rules.json              # Massachusetts borrower's-interest / high-cost
├── ga.rules.json              # Georgia Fair Lending Act
├── co.rules.json              # Colorado AI Act (ADMT disclosure/appeal artifacts)
├── common.rules.json          # nationwide state-mechanics rules keyed off states-index flags
└── reason-codes.state.json    # RC-STATE-* codes (merged with base reason codes at load)
```

A state with no rule file simply contributes no overlay rules (plus any `common.rules.json` behavior driven by its `states-index` flags).

## 3. Loading & evaluation semantics

- `loader.py` loads base pack + overlay pack, verifies **both** manifests, merges reason-code tables (namespaces disjoint: base `RC-*` vs overlay `RC-STATE-*`; collision = load error).
- `rules_eval` evaluates: (1) all base rules; (2) `common.rules.json`; (3) the property state's rule file if present. Overlay rules see the same evaluation context plus the state inputs (§4).
- Rollup (`07 §4.4`) is computed over the union — an overlay eligibility failure makes the loan ineligible exactly like a base failure.
- Overlay rules may declare `on_fail.artifact` (§6) to require a state disclosure artifact in addition to (or instead of) a condition.
- `RulesResult` gains `overlay_pack_version`; both versions flow to the DecisionSnapshot (`versions.state_overlay_pack`, `versions.state_overlay_manifest_sha256`).

## 4. Evaluation-context additions (extends `07 §3`)

```
property.state                      (two-letter code; compliance key — §1.4)
state.flags.community_property      (bool, from states-index)
state.flags.wet_funding             (bool)
state.flags.attorney_closing       (bool)
state.flags.disparate_impact_monitoring (bool)
loan.apr                            (percent scale, 3 dp — package input)
loan.total_points_and_fees          (money — package input)
loan.points_and_fees_pct            (derived: total_points_and_fees / loan.amount × 100, 3 dp)
loan.is_cash_out                    (derived: purpose == cash_out_refi)
property.homestead                  (derived: occupancy == primary)
property.prior_home_equity_loan_date (date | absent — package input; TX seasoning)
apor.spread                         (derived: loan.apr − apor_reference from overlay constants; used by high-cost triggers)
```

Package-schema additions (also reflected in `schemas/loan-package.schema.json` and `05 §2`): `loan.apr`, `loan.total_points_and_fees`, `property.prior_home_equity_loan_date` (optional). All are processor-supplied inputs — recomputing APR from fee itemization is out of scope v1 (recorded as an accepted limitation; the discrepancy machinery still applies to what is checkable).

## 5. Reason codes (`reason-codes.state.json`)

State reason codes carry the same ECOA/HMDA bindings — a state-law ineligibility still yields a specific, accurate adverse-action reason:

| Code | ECOA text (normative in the JSON) | HMDA |
|---|---|---|
| RC-STATE-TX-50A6-LTV | Loan-to-value exceeds the 80% limit for Texas home equity loans | 4 |
| RC-STATE-TX-50A6-FEES | Fees exceed the 2% limitation for Texas home equity loans | 9 |
| RC-STATE-TX-50A6-SEASONING | Texas home equity refinance seasoning requirements not met | 9 |
| RC-STATE-HIGHCOST | Loan terms exceed state high-cost loan thresholds; program does not originate high-cost loans | 9 |
| RC-STATE-NTB | Net tangible benefit to the borrower not demonstrated as required by state law | 9 |
| RC-STATE-DATA-MISSING | Information required to evaluate state law compliance not provided | 7 |

(The machine-readable file is normative; exact texts live there — HR-10 applies unchanged.)

## 6. Disclosure artifacts

Some state obligations are not eligibility rules but **required artifacts** (e.g., Texas 12-day notice, Colorado ADMT disclosure). Overlay rules express these as `on_fail.artifact`:

```jsonc
"on_fail": {"outcome": "refer", "reason_code": "RC-STATE-DATA-MISSING",
            "artifact": {"id": "TX-12DAY-NOTICE", "category": "PTD",
                          "text_template": "Evidence that the §50(a)(6) 12-day notice was provided no later than {date}."}}
```

Artifacts synthesize as conditions with `source_kind: "state_rule"` and render in a dedicated **State requirements** group on the conditions board (`13 §4`). The Colorado ADMT disclosure artifact additionally links the decision-provenance endpoint (`12 §3.5`) as its fulfillment source.

## 7. Shipped overlay content (`state-overlays-2026.1.0`)

> Grounded in the July 2026 state-rules research pass; every rule's `citation` field names its authority. This is a representative reference set demonstrating each overlay category — a production deployment extends the same mechanism to all 50 states via the bank's compliance-approved matrix. **Caveat encoded in `reference-indices.json`:** spread/fee triggers re-index periodically (APOR/PMMS/Treasury/CPI); values are pinned per pack version and a production build feeds them from a maintained parameter service with legal review.

### 7.1 Rule-schema extensions used by overlays

- `citation` (REQUIRED on every overlay rule — T-SOV-2 lint): statute/regulation authority.
- `applies` (optional predicate): guard evaluated first; when false the rule records outcome **`not_applicable`** (a first-class `RuleEvaluationRecord` outcome — the trace shows the rule was considered and why it didn't bind).
- `on_fail.artifact`: state disclosure/cure artifact synthesized as a condition on failure (§6).
- `artifact_always`: condition synthesized whenever `applies` matches, independent of pass/fail — for unconditional state document sets (e.g., TX-A6-DOCSET, MA-BI-WORKSHEET, CP-NBS-SIGN). Rules that exist only to carry an `artifact_always` use a tautological `when` and `severity: documentation|informational`.

### 7.2 Shipped rules (summary — machine-readable files are normative)

| Rule | State | Effect | Authority |
|---|---|---|---|
| SHC-000 | all | HOEPA §32 baseline: APOR spread > 6.5 ⇒ **ineligible** (high-cost, not GSE-deliverable) | 12 CFR 1026.32 |
| STX-001/002 | TX | a6 (cash-out on homestead): LTV/CLTV > 80 ⇒ **ineligible** + counteroffer hint | Tex. Const. art. XVI §50(a)(6)(B) |
| STX-003 | TX | a6: simultaneous subordinate financing ⇒ **ineligible** | §50(a)(6); FNMA B5-4.1-03 |
| STX-004 | TX | a6: lender-controlled fees > 2% ⇒ **refer + cure condition** | §50(a)(6)(E) |
| STX-005 | TX | a6: prior a6 within 365 days ⇒ **ineligible** | §50(a)(6)(M)(iii) |
| STX-006 | TX | a6: 12-day notice not on file ⇒ **refer + PTD artifact** | §50(a)(6)(M)(i) |
| STX-007 | TX | a6: always-condition — Form 3044.1/3185, T-42/T-42.1, full appraisal | FNMA B5-4.1-03; TDI |
| SNY-001 | NY | §6-l high-cost (Treasury spread > 8.0 or points/fees > 5%) ⇒ **ineligible** | N.Y. Banking Law §6-l |
| SNY-002 | NY | §6-m subprime (rate > PMMS + 1.75) ⇒ **refer + duties artifact** (ATR, escrow, NTB, anti-steering) | N.Y. Banking Law §6-m |
| SNY-003 | NY | refi ⇒ CEMA structure/documents condition (no AUS change) | N.Y. Tax Law §255; FHLMC 4101.11 |
| SMA-001 | MA | c.183C high-cost ⇒ **ineligible** | MGL c.183C |
| SMA-002 | MA | refi ⇒ Borrower's Interest Worksheet artifact (NTB or safe harbor) | MGL c.183 §28C; 209 CMR 53 |
| SGA-001 | GA | GAFLA high-cost (points/fees ≥ 5% or APR trigger) ⇒ **ineligible** | O.C.G.A. §7-6A |
| SFL-001 | FL | wind/hurricane-deductible/flood insurance adequacy artifact (+condo master policy) | Fla. Stat. §627.701 |
| SCO-001 | CO | informational: ADMT explanation/human-review/data-correction duties surface pre-decision | SB 26-189 |
| SCP-001 | CP-9 | non-borrowing spouse signature condition (no conventional DTI impact) | community property law |
| SFN-001 / SAT-001 | flag-driven | dry-funding PTF-timing / attorney-closing document-source conditions | state practice |

### 7.3 ADMT adverse-decision artifacts (CO / CA)

The `adverse_action` node consults `states-index.admt_adverse_artifact`: on decline in a flagged state it appends the required block to the notice package (CO: plain-language explanation + human-review request path + data-correction path; CA: ADMT notice/logic-access references) and emits an `adverse_action_generated` payload naming the artifacts. The decision-provenance endpoint (`12 §3.5`) is the fulfillment source for "logic access"/"explanation" content — provably derived from the actual rule evaluations, consistent with HR-10.

### 7.4 Deliberate negatives (documented so implementers don't over-condition)

- **No usury gate** for first-lien conforming (DIDMCA §501 preemption, 12 CFR Part 190).
- **No earthquake-insurance condition** in CA (`no_earthquake_condition` flag).
- **Fair-lending monitoring flag** (NY/MA/CA/IL retain effects-based regimes post-2026 federal rollback): tags the HMDA monitoring extract (`12 §3.6`) — a monitoring obligation, never a per-loan gate.

## 8. Workbench & data-model touchpoints

- `04` additions: `loan_applications.state_overlay_pack_version` column; rule evaluations already carry pack version per record.
- `13`: rules table gains a **State** badge + citation tooltip for overlay rules; conditions board gains the State requirements group; the decision packet's failed-rules list includes overlay failures identically.
- `14`: archetypes add state coverage (TX 50(a)(6) pass + fail, high-cost fail, CO disclosure artifact); corpus generator assigns states per a fixed distribution and sweeps TX LTV/fee boundaries.
- `15`: T-SOV-* tests (defined in `15 §1`): overlay-pack manifest tamper, citation lint, most-restrictive-wins (overlay failure on base-eligible loan), state-selection correctness (identical loan in two states), TX boundary goldens, snapshot pins overlay version, replay covers overlay rules.
