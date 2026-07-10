# 02 — Compliance Matrix

Maps each regulatory obligation to the concrete control implemented, where it is specified, and the test that proves it. This is a **reference implementation on synthetic data** — it demonstrates the controls; production deployment on the bank's internal network additionally requires the bank's own legal/compliance validation, model risk management sign-off, and real vendor integrations.

Research basis (July 2026): CFPB circulars 2022-03/2023-03; 12 CFR 1002 (Reg B), 1026.43 (ATR/QM), 1003 (Reg C/HMDA); FCRA §§604/609(g)/615; SR 26-2 / OCC Bulletin 2026-13 (supersedes SR 11-7, 2026-04-17); Fannie Mae LL-2026-04 (AI governance, eff. 2026-08-06); Freddie Mac Guide Bulletin 2025-16 (eff. 2026-03-03); GLBA Safeguards; Colorado AI Act (SB 26-189, eff. 2027-01-01) as forward-looking state baseline.

Columns: **Requirement** (what the regulation demands) → **Control** (what this system does) → **Spec** (where specified) → **Test** (what proves it, per `15-testing-acceptance.md`).

---

## 1. ECOA / Regulation B — adverse action (12 CFR 1002.9) + CFPB Circular 2023-03

| Requirement | Control | Spec | Test |
|---|---|---|---|
| Written adverse-action notice with **specific principal reasons** (not generic; up to 4) | Reasons are exactly the human-selected reason codes bound to **actually-failed rules**; `reason-codes.json` carries the ECOA notice text per code; notice generator assembles from codes only (HR-10) | 07 §6, 09 §5.5 | T-AAN-1 |
| Reasons must reflect the **actual basis** of the decision; "black-box" complexity is no defense | Eligibility decided only by the deterministic policy engine over traced inputs (HR-1); every failed rule's concrete input values are persisted in `RuleEvaluationRecord`; LLM cannot add/remove/reword reasons | 07 §4, 10 §3 | T-TOP-2, T-AAN-1 |
| Human accountability for adverse decisions | All declines pass the human gate with explicit reason-code selection; four-eyes on declines (HR-2) | 09 §5 | T-DEC-2, T-DEC-4 |
| Record retention: 25 months from application | Append-only ledger + snapshots, no expiry path (NFR-8; designed for ≥ 7 years) | 11 §9 | T-AUD-3 |

## 2. ATR / QM — Regulation Z (12 CFR 1026.43)

| Requirement | Control | Spec | Test |
|---|---|---|---|
| Consider and document **all 8 underwriting factors** (income/assets, employment, payment on this loan, simultaneous loans, mortgage-related obligations, current debts/alimony/support, DTI or residual income, credit history) | `AtrEvaluation` — 8 persisted rows per run, each with basis + lineage to verified source data | 06 §8, 04 §4 | T-CAL-7 |
| Verification using reliable third-party records | Verification adapters (simulated) + document cross-check with tolerances; discrepancies become findings (HR-8) | 06 §7, 03 §6 | T-VER-1 |
| Retain evidence of compliance 3 years | Ledger + DecisionSnapshot retention posture | 11 §9 | T-AUD-3 |

## 3. HMDA / Regulation C (12 CFR 1003)

| Requirement | Control | Spec | Test |
|---|---|---|---|
| Report action taken (codes) + action date | Action-taken state machine: approved / approved-not-accepted / denied / withdrawn / incomplete, each with timestamp | 04 §5 | T-HMD-1 |
| Report denial reasons | Selected reason codes carry HMDA denial-code mappings, written to the HMDA record at finalization | 07 §6, 04 §5 | T-HMD-1 |
| Application/decision milestone dates | `received`, `review_started`, `decision_ready`, `decided` timestamps on every application | 04 §5 | T-HMD-2 |
| Demographic data collected for reporting | Isolated demographics table + monitoring-only export | 04 §6, 12 §3.6 | T-HMD-3 |

## 4. Fair lending — ECOA + Fair Housing Act

| Requirement | Control | Spec | Test |
|---|---|---|---|
| No use of protected characteristics (or proxies) in credit decisions | **Import isolation** (HR-6): decisioning modules cannot import demographics; rule pack inputs are exclusively financial/guideline variables (enumerated in 07 §7 — no geography-as-proxy, no behavioral data) | 04 §6, 07 §7 | T-ISO-1 |
| Uniform decision rules across applicants | Single versioned pack per run; no per-applicant rule variation exists in the engine | 07 §5 | T-POL-1 |
| Monitoring for disparate outcomes (GSE/state expectation) | Monitoring-only extract joining decisions↔demographics for out-of-band fair-lending analysis; override patterns queryable by reviewer | 12 §3.6, 11 §3 | T-HMD-3 |

## 5. FCRA (§§604, 609(g), 615)

| Requirement | Control | Spec | Test |
|---|---|---|---|
| Credit-score disclosure with adverse action: score, range, date, up-to-4 key factors, bureau | FCRA block auto-assembled into the adverse-action notice from the package's credit data | 09 §5.5 | T-AAN-1 |
| Permissible-purpose discipline | Simulated bureau adapter logs a `permissible_purpose` field on every pull event | 03 §6 | T-ADP-1 |

## 6. GSE AI mandates — Fannie Mae LL-2026-04, Freddie Mac Bulletin 2025-16

| Requirement | Control | Spec | Test |
|---|---|---|---|
| Human involvement in significant/adverse AI-influenced decisions | Universal human gate; **no graph edge bypasses it** (HR-2) | 09 §5 | T-TOP-1 |
| AI/ML system inventory | `10-llm-usage-register.md` (every LLM call site) + AUS simulator + policy engine versions enumerated in ARCHITECTURE.md AI-inventory section | 10 §3, 03 §8 | T-LLM-1 |
| Decision traceability & audit records for AI-influenced decisions | Hash-chained ledger; every LLM call audited with prompt+model versions; DecisionSnapshot pins all versions | 11, 10 §4 | T-AUD-1, T-LLM-2 |
| Fair-lending testing of AI | Corpus regression run + monitoring extract enable outcome-distribution testing across the synthetic population | 14 §5 | T-DAT-3 |
| Vendor accountability / model documentation | LLM register documents vendor, model ids, swap procedure; prompts version-controlled and code-reviewed | 10 §6 | T-LLM-3 |

## 7. Model risk management — SR 26-2 / OCC 2026-13 (spirit)

| Requirement | Control | Spec | Test |
|---|---|---|---|
| Model inventory with versions, owners, scope | AUS sim config versioned; policy packs semver + manifest; prompts versioned; register documents scope ("extraction/narrative only — never decisions") | 07 §5, 08 §5, 10 §3 | T-REP-1 |
| Reproducibility / effective challenge | `replay()` reproduces any sealed decision byte-exactly from its snapshot (HR-5) | 11 §7 | T-REP-1 |
| Change management: material changes = new version, revalidation | Packs immutable (new semver dir per change + golden-test rerun); prompt changes = new version file + eval rerun | 07 §5, 10 §6 | T-POL-2 |
| Ongoing monitoring hooks | Corpus regression produces decision-distribution reports diffable across pack/prompt versions | 14 §5 | T-DAT-3 |

## 8. GLBA Safeguards (demo-lite; synthetic data)

| Requirement | Control | Spec | Test |
|---|---|---|---|
| Protect NPI confidentiality | PII masking processor in structured logging (SSN/DOB/account numbers); PII never in audit event metadata fields | 11 §8 | T-SEC-1 |
| Access accountability | Every human action in the ledger carries `actor` identity; audit endpoints are read-only | 11 §3, 12 §3.3 | T-AUD-1 |

## 9. UDAAP + SAFE Act + appraisal independence (acknowledged, minimal footprint)

| Requirement | Control | Spec | Test |
|---|---|---|---|
| No deceptive automated outcomes (UDAAP) | Suggested action always shown as *suggested*; the human decides; notices generated from real decision basis | 09 §5, 13 §6 | T-UI-3 |
| Licensed MLO attribution (SAFE Act) | Loan package carries `mlo_nmls_id`; displayed on the workbench summary | 05 §3, 13 §3 | T-PKG-1 |
| Appraisal independence | Appraised value is package input; nothing in the system feeds decisions back into valuation | 05 §3 | T-PKG-2 |

## 10. State AI baseline — Colorado AI Act (forward-looking)

| Requirement | Control | Spec | Test |
|---|---|---|---|
| Disclose ADMT use + how it factored into the decision | Decision detail endpoint exposes pipeline provenance (which automated components ran, versions, outputs) suitable for consumer-facing disclosure assembly | 12 §3.5 | NFR-7 → T-REP-1 |
| Right to human review / appeal | Human gate is inherent; re-run + second-review flows exist (four-eyes, override records) | 09 §5.3 | T-DEC-3 |
| Record retention for ADMT decisions | Ledger + snapshots ≥ 7-year posture | 11 §9 | T-AUD-3 |

---

## 11. State law overlays (per-state regimes — full detail in `17-state-overlays.md`)

| Requirement | Control | Spec | Test |
|---|---|---|---|
| Texas Const. art. XVI §50(a)(6) — home-equity gates (80% LTV/CLTV, fee cap, seasoning, notice, no subordinate financing, document set) | STX-001..007 overlay rules with citations; hard gates ineligible; artifacts as conditions | 17 §7.2 | T-SOV-5 |
| State high-cost / anti-predatory laws (NY §6-l/§6-m, MA c.183C/§28C, GA FLA, HOEPA baseline) | high-cost ⇒ ineligible; covered/subprime tiers ⇒ duty artifacts (NTB worksheet, escrow, ATR docs) | 17 §7.2 | T-SOV-5 |
| State ADMT laws (CO SB 26-189, CA CCPA ADMT) — explanation, human review, data correction on automated adverse decisions | adverse_action node appends state artifact block sourced from decision provenance | 17 §7.3 | T-SOV-6 |
| State effects-based fair lending retained post-2026 (NY/MA/CA/IL) | monitoring flag on the fair-lending extract; never a per-loan gate | 17 §7.4, 12 §3.6 | T-HMD-3 |
| Community property / funding model / attorney closing mechanics | flag-driven condition library (NBS signature, PTF timing, attorney package) | 17 §7.2 | T-SOV-1 |
| Statutory traceability of every state-driven outcome | mandatory `citation` per overlay rule, rendered in UI + audit | 17 §1.3 | T-SOV-2 |
| Reference-rate re-indexing (APOR/PMMS/Treasury/CPI) | pinned per pack version in `reference-indices.json`; production feeds from maintained parameter service | 17 §7 | T-SOV-4 |

## 12. Traceability rule for implementers

When any control above is touched during implementation, the PR/commit description MUST cite the requirement IDs (from `01-requirements.md`) it affects, and `15-testing-acceptance.md` MUST keep the proving test green. If a control cannot be implemented as specified, the implementer MUST NOT silently substitute — record the deviation in `specs/DEVIATIONS.md` (create on first use) with rationale and impact, and keep the compliance row pointing at the deviation entry.
