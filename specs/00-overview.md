# 00 — Overview, Scope, and Hard Rules

**Spec package version:** 1.0.0 · **Date:** 2026-07-10 · **Status:** Authoritative

This directory (`specs/`) is a **complete, self-contained specification** for the UA Underwriting Agent. An implementing agent (human or AI) must be able to build the entire system from these documents alone, with no access to any prior conversation or external design context. Where a document references another, it does so by file name and section. All normative statements use RFC-2119 keywords (MUST / MUST NOT / SHOULD / MAY).

---

## 1. What this system is

The **UA Underwriting Agent** is an AI-assisted mortgage underwriting workbench for a large US national bank, consisting of:

1. A **deterministic underwriting pipeline** (LangGraph, Python) that re-underwrites a fully assembled loan package: verifies documents against stated data, independently recomputes qualifying income / DTI / LTV / reserves, evaluates a versioned policy rule pack, runs a deterministic AUS-style scorer, synthesizes conditions, and **always stops at a human decision gate**.
2. A **visual underwriter workbench** (Next.js + CopilotKit) presenting the 4 Cs analysis with click-through lineage on every number, AUS findings, conditions, red flags, a decision gate, adverse-action preview, and a tamper-evident audit timeline — plus a chat sidebar grounded in the loan's actual state.
3. A **bullet-proof audit and repeatability layer**: append-only hash-chained event ledger, sealed decision snapshots pinning every version (rules, prompts, models, AUS config), and byte-exact replay.

### What this system is NOT (out of scope)

- Application intake, loan-officer or borrower-facing flows, prequalification.
- Processing/document collection, TRID/Loan Estimate/Closing Disclosure timing.
- Condition-clearing loops with borrowers, clear-to-close, closing, funding.
- Post-closing QC, servicing, secondary-market delivery.
- Real integrations with DU/LPA, credit bureaus, or verification vendors (all are **simulated behind adapter interfaces**; see `03-architecture.md §6`).
- Real borrower data. **Synthetic data only.**

The system receives a **complete submitted loan package** (see `05-loan-package-contract.md`) and produces an **underwriting decision with full traceability**.

---

## 2. Hard rules (non-negotiable invariants)

Every implementation decision defers to these. Each has at least one enforcing test (`15-testing-acceptance.md`).

| # | Hard rule | Rationale | Enforced by |
|---|-----------|-----------|-------------|
| HR-1 | **The LLM never makes, gates, or influences the credit decision.** LLMs are used only for: document field extraction, narrative summaries, condition text drafting, and grounded chat Q&A. Eligibility outcomes come exclusively from the deterministic policy engine over persisted, human-verifiable extracted fields. | ECOA/Reg B + CFPB Circular 2023-03: adverse-action reasons must reflect the actual decision basis; LLM free text cannot be that basis. | T-TOP-2, T-LLM-1 |
| HR-2 | **No graph path reaches a final decision without passing the human review interrupt.** Declines additionally require explicit reason-code selection by the human. | GSE AI mandates (Fannie Mae LL-2026-04, Freddie Mac Bulletin 2025-16); industry practice: human before adverse action. | T-TOP-1, T-DEC-2 |
| HR-3 | **Every computed value is a `TracedValue`** carrying a lineage reference that resolves, transitively, to source documents/fields. A number without lineage MUST NOT be displayed or used in rule evaluation. | Auditability; adverse-action accuracy. | T-LIN-1 |
| HR-4 | **The audit ledger is append-only and hash-chained.** No UPDATE or DELETE, ever; corrections are new events. Every decision run ends with a seal event containing the DecisionSnapshot hash. | Tamper evidence; record retention (ECOA 25 months, HMDA 3 years, bank practice 7 years). | T-AUD-1..3 |
| HR-5 | **Every decision is reproducible.** A sealed DecisionSnapshot replayed through the same versions (policy pack, AUS config, calculations) MUST produce the identical outcome, rule-by-rule. | SR 26-2 spirit; exam defense. | T-REP-1 |
| HR-6 | **Demographic (HMDA) data is import-isolated from decisioning.** No module under `agent/`, `policy_engine/`, `aus/`, or `domain/calculations/` may import or read demographic data. | Fair lending (ECOA, FHA); proxy-discrimination avoidance. | T-ISO-1 |
| HR-7 | **All versions are pinned per decision**: policy pack (semver + sha256 manifest), every prompt (id + version), every model (exact model id), AUS simulator config version. "Latest" is never resolved at evaluation time — the pack version is pinned when the run starts. | Model/prompt governance; reproducibility. | T-REP-1, T-LLM-2 |
| HR-8 | **Package-supplied figures are never trusted.** Processor-computed DTI, stated income, etc. are recomputed independently; discrepancies beyond tolerance become findings/conditions, not silent overwrites. | Underwriting integrity (the underwriter re-underwrites). | T-VER-1 |
| HR-9 | **Exactly one file imports the LLM vendor SDK.** All other code depends on the `LLMClient` protocol. The vendor (currently Anthropic) is swappable per the procedure in `10-llm-usage-register.md §6`. | Provider-swap requirement; vendor governance. | T-LLM-3 |
| HR-10 | **Adverse-action reasons come only from failed-rule reason-code bindings.** The LLM may format surrounding prose; it MUST NOT add, remove, or reword a reason. | ECOA/Reg B specificity + accuracy. | T-AAN-1 |

---

## 3. Reading order for implementers

1. `00-overview.md` (this file) — scope, hard rules, glossary.
2. `01-requirements.md` — every FR/NFR with IDs; all other docs cite these.
3. `02-compliance-matrix.md` — why each control exists.
4. `03-architecture.md` — components, wiring, deployment. **Read the CopilotKit wiring section carefully; it encodes workarounds for known SDK defects.**
5. `04-domain-model.md` → `05-loan-package-contract.md` → `06-calculations.md` → `07-policy-engine.md` → `08-aus-simulator.md` → `09-agent-graph.md` — the core engine, in dependency order.
6. `10-llm-usage-register.md`, `11-audit-repeatability.md` — the two governance pillars.
7. `12-api-contracts.md`, `13-frontend-workbench.md` — the surface.
8. `14-synthetic-data.md`, `15-testing-acceptance.md`, `16-implementation-plan.md` — data, proof, and build order. **Follow the phase gates in 16 strictly; Phase 0 must pass before any domain code is written.**

Machine-readable artifacts (normative, not illustrative):
- `policy-pack/conforming-2026.1.0/` — the actual rule pack the system ships with.
- `prompts/` — versioned prompt definitions.
- `schemas/` — JSON Schemas for the loan package, rules, audit events, decision snapshots, interrupt/resume payloads, and agent state.

---

## 4. Glossary

| Term | Definition |
|------|-----------|
| **4 Cs** | Credit, Capacity, Capital, Collateral — the four underwriting analysis dimensions. |
| **Adverse action** | A credit denial (or counteroffer the applicant does not accept). Triggers ECOA/Reg B notice with specific principal reasons and FCRA credit-score disclosure. |
| **ATR** | Ability-to-Repay (12 CFR 1026.43): eight factors a creditor must consider and document. |
| **AUS** | Automated Underwriting System. Real-world: Fannie Mae DU, Freddie Mac LPA. Here: a deterministic simulator (`08-aus-simulator.md`) producing DU-style recommendations. |
| **Compensating factors** | Documented strengths (e.g., reserves ≥ 6 months, credit score ≥ 740, LTV ≤ 75) that permit higher DTI within policy. |
| **Condition** | A requirement attached to an approval. Categories: **PTA** (prior to approval), **PTD** (prior to documents), **PTF** (prior to funding). |
| **Decision packet** | The structured payload presented at the human gate: 4 Cs summaries, rule results, AUS findings, red flags, proposed conditions, eligible reason codes, suggested action. |
| **DecisionSnapshot** | Frozen JSON capturing all inputs, extracted fields, versions (pack/prompts/models/AUS), rule evaluations, and outcome; hash is written into the seal event; replayable. |
| **DTI** | Debt-to-income ratio. Front-end = PITIA ÷ qualifying income; back-end = (PITIA + monthly debts) ÷ qualifying income. |
| **Four-eyes** | Second-reviewer requirement for declines and loans ≥ configured amount threshold. |
| **HMDA action-taken** | Regulation C reporting code for the application outcome (1 = originated … 3 = denied, etc.) with date. |
| **Lineage / `TracedValue`** | `{value, lineage_ref}`; the ref resolves to a lineage node graph: document → extracted field (confidence, prompt+model version) → calculation → rule evaluation. |
| **Loan package** | The complete submitted input: application data, tri-merge credit report, stated income/assets/liabilities, processor-computed figures, and document set. Contract in `05`. |
| **PITIA** | Principal, Interest, Taxes, Insurance, Association dues — the full monthly housing obligation. |
| **Policy pack** | Versioned, immutable directory of declarative rule JSON + reason-code bindings with a sha256 manifest. |
| **Reason code** | Internal code (e.g., `RC-DTI-EXCESSIVE`) bound to a rule's failure, mapping to ECOA notice text + HMDA denial code. |
| **Representative score** | Per-borrower middle of three bureau scores (lower of two if only two); loan-level = lowest representative score among borrowers. |
| **Red flag** | A fraud/misrepresentation indicator from the fraud screen (e.g., occupancy distance, unsourced large deposit). |
| **Seal** | Terminal audit event containing the DecisionSnapshot hash; closes the run's audit chain segment. |
| **TracedValue** | See Lineage. |
| **UnderwritingState** | The LangGraph shared state streamed to the UI: IDs + summaries + progress only (< 32 KB serialized). |

---

## 5. Regulatory context (summary — full detail in `02-compliance-matrix.md`)

This is a **reference implementation on synthetic data**; it is not itself a compliant production system, but it implements the *controls* a production system needs, so the patterns transfer 1:1 onto the bank's internal network:

- **ECOA / Regulation B (12 CFR 1002.9)** + **CFPB Circular 2023-03** — specific, accurate principal reasons for adverse action; complexity of a model is no defense.
- **ATR/QM (12 CFR 1026.43)** — the 8 underwriting factors explicitly evaluated and documented per loan.
- **HMDA / Regulation C** — action-taken codes, denial reasons, milestone dates captured.
- **Fair lending (ECOA, Fair Housing Act)** — demographics isolated from decisioning; uniform rules across applicants.
- **FCRA §609(g)/§615** — credit-score disclosure content on adverse action.
- **GSE AI mandates** — Fannie Mae LL-2026-04 (eff. 2026-08-06), Freddie Mac Bulletin 2025-16 (eff. 2026-03-03): AI governance, inventory, fair-lending testing, decision audit trails, human involvement in significant decisions.
- **Model risk management (SR 26-2 / OCC 2026-13 spirit)** — versioning, validation hooks, monitoring, reproducibility.
- **GLBA (demo-lite)** — PII masking in logs; synthetic data only.
- **Record retention** — ECOA 25 months, Reg Z 3 years, HMDA 3 years, GSE practice 7 years → the ledger and snapshots are designed for ≥ 7-year retention.

---

## 6. Repository layout (target)

See `16-implementation-plan.md §2` for the full tree. Top level:

```
UA/
├── specs/        # this package — source of truth
├── policy/       # runtime copy of specs/policy-pack + specs/prompts (manifest-verified at load)
├── backend/      # FastAPI + LangGraph agent service (Python 3.12)
├── frontend/     # Next.js + CopilotKit workbench
├── scripts/      # dev.ps1, seed.ps1, verify-audit.ps1, generate-corpus.ps1
└── data/         # committed golden archetypes; generated corpus + DBs gitignored
```
