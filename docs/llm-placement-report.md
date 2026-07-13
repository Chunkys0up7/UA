# LLM Placement in the UA Underwriting Pipeline — Decision Analysis & Rationale

**Status:** Report for the internal build team · 2026-07-13
**Question answered:** For every step of the underwriting pipeline, does it call an LLM, why or why not, and what would change if that placement flipped? Is a ~3-minute pipeline "too simple" against a 15–45-minute agentic alternative?

---

## Executive summary

1. **The runtime difference is architectural, not a rigor difference.** UA makes exactly **one LLM call per document** (~9–10 per loan) and zero LLM calls in the decision path. A 15–45-minute agentic underwriter spends its time on LLM *judgment* — iterative reasoning loops over guidelines. UA spends milliseconds on judgment because judgment is a versioned deterministic rules engine, which is what makes decisions **replayable, reason-attributable, and consistent** — the three properties ECOA/Reg B examination actually tests.
2. **Speed is on-market, not under-market.** Production AUS (Fannie Mae DU, Freddie Mac LPA) return findings in seconds. No US lender waits 45 minutes for an underwriting recommendation.
3. **Where the skepticism is fair:** UA under-uses the LLM in three *advisory* surfaces its own spec defines (grounded chat copilot, 4 Cs narrative, LLM-drafted condition wording) and lacks a fourth high-value pattern (a "second-look" cross-document reviewer). None of these touch the decision path; all four can be added without weakening a single guarantee. Recommendations in §6.
4. **The one place the 15–45-minute system may genuinely be doing harder work:** real-world scanned documents. UA's synthetic corpus is clean text, which flatters the extraction stage. On the internal network with live documents, extraction is where LLM capability (and latency) legitimately concentrates — and it is already the LLM's job in this architecture.

---

## 1. Measured baseline (this repository, mock provider)

| Metric | Value | Source |
|---|---|---|
| LLM calls per loan | 9–10 (1 per extractable document) | measured, audit ledger `llm_call` events |
| Rule evaluations per loan | 26–33 (base pack + state overlay) | measured |
| Pipeline runtime per loan (mock) | ~0.3 s | measured |
| 500-loan corpus regression | 2 m 32 s, 100% families matched, chain verified, replays byte-identical | CI run |
| Estimated runtime per loan (live LLM, serial) | ~20–40 s (9–10 extraction calls × 2–4 s) | model |
| Estimated runtime per loan (live LLM, parallel extraction) | ~5–8 s | model |

**Implication:** even fully live, UA is a ~seconds-to-one-minute system. A 15–45-minute runtime implies hundreds of LLM calls or long sequential reasoning chains — i.e., the LLM is doing orchestration and adjudication, not extraction.

---

## 2. The placement decision, step by step

Every pipeline stage, whether it calls the LLM, and the rationale. "Decision path" = anything whose output changes eligibility, reasons, or the recorded decision.

| # | Stage | LLM? | What it does | Why this placement |
|---|---|---|---|---|
| 1 | `package_validate` | **No** | JSON-Schema + referential integrity on the submitted package | Structural validation must be exact and cheap; an LLM adds failure modes to a solved problem. |
| 2 | `document_extraction` | **YES** (9 prompts) | Unstructured document text → typed fields with per-field confidence | The one task where LLMs are the *best available tool*: reading paystubs, W-2s, Schedule Cs, bank statements. Output is persisted, confidence-scored, human-inspectable, and **never trusted directly** — see stage 3. Prompt id + version + exact model id recorded on every call (audit event + lineage meta). |
| 3 | `data_verification` | **No** | Cross-checks extracted values against stated values under numeric tolerances (±2% paystub↔stated, ±5% W-2↔1040 …); VOE/flood/OFAC/geo adapters | This is the containment layer FOR stage 2: LLM extraction errors and hallucinated numerics surface here as discrepancies/red flags instead of flowing silently into decisions. Making the checker an LLM would remove the independent control on the LLM. |
| 4–7 | `income_calc`, `credit_analysis`, `asset_analysis`, `collateral_analysis` | **No** | Qualifying income (2-yr averaging, 75% YTD haircut, SE add-backs), DTI, LTV/CLTV, reserves, representative score — pure Decimal math with content-addressed lineage | Arithmetic must be exact, reproducible, and lineage-traceable. LLMs are demonstrably unreliable at multi-step arithmetic, and even when right, they can't emit a lineage graph an examiner can walk. Every number here is clickable in the UI down to its source extraction. |
| 8 | `fraud_screen` | **No** (v1) | Deterministic red-flag rules (occupancy distance, deposit patterns, insurance mismatch…) | Flags must fire identically for identically-situated applicants (fair-lending consistency). §6 recommends an *additional* LLM second-look layer beside — not instead of — this screen. |
| 9 | `rules_eval` | **No — hard rule HR-1** | 26–33 versioned policy rules (base + state overlay), each recording consumed inputs, outcome, reason-code binding, statutory citation | **The core of the whole design.** ECOA/Reg B + CFPB Circular 2023-03: stated adverse-action reasons must be the *actual* basis. A deterministic rule that failed IS the actual basis, provably. An LLM's stated reasons are a narrative about its output, not a mechanical property of it. Also: byte-exact replay (HR-5) is only possible over deterministic evaluation. |
| 10 | `aus_simulate` | **No** | DU-style advisory scorer, versioned config | Mirrors the industry: real AUS are deterministic scorecards returning in seconds. Advisory only. |
| 11 | `condition_synthesis` | **Partial by design; deterministic in v1** | Conditions from failed rules / AUS messages / discrepancies / flags | Category, source-link, and *whether* a condition exists are deterministic (they're compliance artifacts). The spec allows LLM-drafted *wording* (register row 10, human-editable, deterministic fallback) — currently the deterministic template is used. §6 rec. 3. |
| 12 | `prepare_decision` | **Spec: narrative only** | Assembles the decision packet + suggested action | Suggested action is a 5-row deterministic ladder — an underwriter must be able to predict it. The display-only 4 Cs narrative (register row 11) is spec'd but unwired. §6 rec. 2. |
| 13 | `human_review` (gate) | **No** | Interrupt; validates the human decision (reason codes ⊆ failed rules, four-eyes, override justification) | The decision-maker is a human — GSE AI-governance expectation (Fannie LL-2026-04 / Freddie 2025-16). Validation of the human's input is a correctness function, not a judgment. |
| 14 | `adverse_action` | **No — hard rule HR-10** | Notice from selected codes' verbatim ECOA texts + FCRA §609(g) block + CO/CA ADMT artifacts | The single most regulator-sensitive artifact in the system. LLM paraphrase of a legal notice is unacceptable risk for zero benefit. |
| 15 | `finalize` + `audit_seal` | **No** | HMDA mapping; hash-chained seal of the replayable snapshot | The audit spine must be boring, exact, and independent of every model. |
| 16 | Chat copilot (workbench) | **YES — spec'd, unbuilt** | Grounded Q&A over persisted loan state via read-only tools | Legitimate, high-value LLM surface with no decision authority. §6 rec. 1. |

**The design rule that falls out of the table:** *the LLM converts unstructured input into auditable structured data and explains things to humans; it never adjudicates.* Every LLM output is either (a) persisted and independently cross-checked before any rule consumes it, or (b) display-only.

---

## 3. What an LLM-heavy (agentic) underwriter buys — and what it costs

An architecture where the LLM orchestrates and adjudicates ("read the file, apply the guidelines, decide") differs on five axes:

| Axis | UA (deterministic core) | Agentic LLM underwriter |
|---|---|---|
| Runtime / loan | seconds–1 min live | 15–45 min (reasoning loops, re-reads, retries) |
| Same file, same answer? | **Always** (T-REP-2 tested) | Not guaranteed — even temperature-0 inference is not bit-deterministic across batches/kernels, and prompts/models drift |
| Replay for an examiner | Byte-exact from the sealed snapshot (T-REP-1) | Effectively impossible; can only re-ask the model and hope |
| Adverse-action reasons | Mechanically = the failed rules | A generated narrative *about* the decision; unverifiable as the actual basis (CFPB 2023-03 exposure) |
| Guideline changes | New pack version, diffable, golden-tested | Prompt edits with emergent, corpus-wide behavior changes |
| Where effort concentrates | Extraction quality + rules authoring | Prompt/agent engineering + eval harnesses to bound variance |

The honest credit to the agentic pattern: it degrades more gracefully on *messy, unanticipated* inputs (weird document formats, novel scenarios) because the LLM improvises. UA's answer to that is different: improvise in the **advisory** layer (second-look reviewer, chat) and let unanticipated situations land as `refer`/`suspend` for a human — never as an improvised approval or decline.

---

## 4. Evidence from industry & regulators

*(Research pass, July 2026; vendor self-reported figures flagged. Full URLs in §7.)*

### 4.1 Production lenders converge on the same split ("LLM at the edges, deterministic core")

- **Rocket Logic** (Rocket Companies): AI auto-identifies **~70% of >1.5M documents/month** and extracts fields, saving 5,000+ underwriter hours in a single month — with underwriter oversight. The AI does classification + extraction; decisioning stays with rules + humans.
- **Zest AI / Upstart** (the two most-cited "AI lenders"): credit decisions come from **supervised, explainable ML scorecards** (SHAP-derived adverse-action reasons), explicitly *not* generative LLMs. Zest's own pitch is that ML "applies the same logic, thresholds, and criteria across every application."
- **Ocrolus** (document AI for lending): reaches its "99%+" extraction accuracy **only with human-in-the-loop review**, and pairs extraction with *deterministic* balance-verification and fraud checks (fraud flagged in 6–7% of bank statements). Extraction is probabilistic; validation is rules.
- **Verification vendors** (Truework, TurboPass, DU Validation Service): the industry's answer to income/employment verification is **deterministic source-of-truth data pulls**, not LLM inference — precisely because verified data of record must be exact.
- The cross-industry name for this pattern in regulated decisioning is the **"safety sandwich"**: LLM converts unstructured input to structured data; deterministic, auditable code decides.

### 4.2 Why no LLM in calculations or rules — measured failure data

- **FAITH benchmark (2025)**: top LLMs drop from **95.6% on simple financial-table lookups to near 0% on multivariate calculations**. Even OpenAI o1 scores only 89.1% on isolated numeric reasoning. Our DTI/income/reserves math cannot ride on that.
- **Multi-agent financial extraction study (10,000 SEC filings, 5 models)**: best field-level F1 0.943, but **document-level strict accuracy only 75.8%** — about 1 in 4 documents has at least one wrong field *in the best configuration*. This is exactly why UA treats extraction output as *proposed* data cross-checked by deterministic tolerances (stage 3) before any rule consumes it.
- Adding an LLM *verification* layer helped that study (64.8% → 75.8% strict accuracy) **at 2.3× cost** — supporting our design where the verifier is deterministic (free, exact) and the LLM spend goes to extraction quality instead.

### 4.3 Latency & cost: the 15–45-minute number, explained

- **Deterministic AUS is the market baseline**: Fannie Mae DU processes files "in mere seconds" — it is a rules/expert system, and always has been.
- A 2026 **agentic underwriting prototype** (Claude Sonnet 4.5, insurance): agent-only ~**15 min/case**, agent+critic ~**20 min**, ~$0.29–0.55/case. Its time goes to chain-of-thought decomposition and fact-by-fact critique — LLM *judgment*, not document reading.
- Per-document LLM extraction runs **21–74s** with p99/p50 tail blowups up to 3.34×, $0.15–0.43/doc. At ~10 documents/loan that supports UA's live-mode estimate (seconds-to-a-minute per loan) and explains where a full agentic loop finds its extra half hour: **hundreds of reasoning calls, not better reading**.

### 4.4 The regulatory record on LLM-in-the-decision-path

- **CFPB Circular 2022-03 + Sept 2023 guidance**: adverse-action requirements "apply equally to all credit decisions, regardless of the technology used"; creditors cannot rely on models that prevent identifying the **specific, accurate principal reasons**. (The 2026 CFPB fair-lending rollback loosened enforcement posture but did **not** repeal the specific-reason requirement — do not treat it as cover.)
- **Fannie Mae LL-2026-04 / Freddie Mac 2025-16**: written AI/ML governance across the full lifecycle, AI inventory, per-decision audit records — and **no carve-out distinguishing generative AI**: an LLM in the pipeline is fully in scope.
- **SR 26-2 / OCC 2026-13** (replacing SR 11-7): generative and agentic AI are **explicitly excluded from current model-risk guidance** ("additional guidance planned") — i.e., there is no examiner-blessed framework for GenAI decisioning today, while ECOA/FCRA/fair-lending all still apply.

### 4.5 Nondeterminism: the finding that settles the argument

- **Temperature 0 is not determinism.** Measured: **1,000 identical temperature-0 requests produced 80 unique completions** (Qwen3-235B); root cause is batch-variant GPU kernels and floating-point non-associativity, not sampling. On hosted APIs a lender does not control this.
- **Financial-task drift study (480 runs)**: at T=0, output consistency ranged **12.5%–100% depending on model**; RAG/document-QA (the extraction-adjacent task) drifted **25–75%**. Regulated-use guidance from the same literature: "a bank using LLMs for automated credit assessment must demonstrate that identical customer profiles produce identical decisions" — which an LLM decision path structurally cannot promise.
- **Replayable-agents research** concludes byte-exact replay of tool-using LLM agents is generally unattainable; the recommended pattern is to keep the deterministic parts deterministic and replay those. **This is precisely UA's replay design**: sealed extraction outputs are replay *inputs*; `replay()` never calls the LLM (specs/11 §7), which is why UA's byte-exact replay claim holds where an agentic system's cannot.

---

## 5. Evidence-backed placement matrix (industry consensus vs UA)

| Pipeline function | Industry consensus | UA today | Verdict |
|---|---|---|---|
| Document classification/routing | LLM/CV | Implicit (doc_type in package); LLM classification relevant for real docs | Add with live-doc intake |
| Field extraction | LLM/vision, **confidence-gated + HITL** | LLM, one call/doc, confidence recorded; cross-checked by stage 3 | Aligned; add confidence-threshold routing (§6.5) |
| Verification/cross-check | Hybrid: LLM flags, deterministic confirms | Deterministic tolerances + adapters | Aligned; LLM flag layer = §6.4 |
| Calculations (income/DTI/LTV) | **Deterministic, never LLM** | Deterministic Decimal + lineage | Aligned (FAITH: LLMs ~0% on multivariate calc) |
| Eligibility rules | **Deterministic rules engine** | Versioned packs, cited, replayable | Aligned |
| Risk scoring | Explainable ML/scorecard, not generative | Deterministic AUS simulator (swap point for bank's model) | Aligned |
| Condition generation | LLM-draft + human-approve | Deterministic templates (LLM draft spec'd, unwired) | **Gap — §6.3** |
| The credit decision | Deterministic/XAI + human of record | Rules rollup + mandatory human gate | Aligned |
| Adverse-action reasons | Deterministic/XAI-derived, never free-form LLM | Verbatim ECOA texts bound to failed rules | Aligned |
| Narrative/appraisal analysis | LLM, advisory | Spec'd, unwired | **Gap — §6.2** |
| Chat over the loan file | LLM, grounded, advisory | Spec'd, unwired | **Gap — §6.1** |
| Second-look/QC review | **LLM critic — highest-value extra spend** (accuracy 92→96%, hallucination 11.3→3.8%, 87% issue catch-rate in the agentic-UW study) | Absent | **Gap — §6.4** |
| Pipeline orchestration | Deterministic workflow; LLM is a step, never the arbiter | LangGraph deterministic graph | Aligned |

**Bottom line:** UA matches the industry-consensus placement on every decision-critical row. The four gaps are all in the *advisory* column — the exact place the evidence says extra LLM spend pays off.

---

## 6. Recommendations — where to use the LLM MORE (safely)

Ranked by value-to-risk for the internal build. None touch the decision path; all inherit the existing audit machinery (registered prompt, `llm_call` event, model id pinned in the snapshot).

1. **Grounded chat copilot** (spec'd: register row 12, `09 §7`). Read-only tools over persisted state: `get_dti_breakdown`, `get_rule_result`, `explain_lineage`, `get_open_conditions`, `draft_condition_text`. This is the biggest visible "LLM depth" win for underwriters: *"why is this file suspended?"* answered from the actual rule trace. Effort: ~1–2 days.
2. **4 Cs narrative** (register row 11, already spec'd into `prepare_decision`): 3–5 sentence underwriter-style file summary, display-only, marked AI-generated. Effort: hours.
3. **LLM-drafted condition wording** (register row 10): fluent, borrower-actionable text; category/source stay deterministic; human-editable at the gate; deterministic fallback already implemented. Effort: hours.
4. **Second-look reviewer (new; recommend adding to the spec as an advisory stage):** one LLM call over the assembled file — cross-document inconsistency spotting, appraisal-comment analysis, "what would a senior underwriter question?" Output = advisory commentary block in the decision packet + red-flag *suggestions* the deterministic screen renders as `info` severity. Never changes rollup or suggested action. This is the legitimate 80% of what agentic systems add, at ~2% of their latency. Effort: ~1 day + eval fixtures.
5. **Live-extraction hardening for real documents** (internal-network priority): keep the one-call-per-document shape but add the production controls the spec anticipates — per-field confidence thresholds routing low-confidence extractions to human verification, cross-field arithmetic checks (deposit lines sum to statement totals), and an extraction eval set built from your real (redacted) document corpus. This is where the FDE system's minutes are legitimately spent, and where your effort should go — **not** into LLM adjudication.

With 1–4 implemented, a live-provider loan makes ~12–13 LLM calls (~10 extraction + narrative + second-look + drafting) and completes in well under two minutes — visibly LLM-rich where it helps, provably LLM-free where it must be.

---

## 7. Sources

Industry systems: [Rocket Logic](https://www.rocketcompanies.com/press-release/rocket-companies-introduces-rocket-logic-ai-platform-to-make-homeownership-faster-and-easier/) · [Zest AI on ML decisioning](https://www.zest.ai/learn/blog/top-five-ways-lenders-are-embracing-machine-learning/) · [Zest explainability](https://www.zest.ai/learn/resources/model-explainability-reexplained/) · [Upstart XAI adverse action](https://www.upstart.com/news/enhancing-fair-lending-in-the-age-of-ai) · [Ocrolus](https://www.ocrolus.com/) ([income](https://www.ocrolus.com/income-verification/), [fraud](https://www.ocrolus.com/fraud-detection/)) · [Blend×Truework](https://blend.com/company/newsroom/truework-partnership-income-employment-verification/) · [Fannie DU Validation Service](https://singlefamily.fanniemae.com/media/9361/display) · [DU as expert system (AAAI)](https://aaai.org/papers/184-iaai97-184-iaai97/) · [Snorkel doc intelligence](https://snorkel.ai/blog/faster-than-ever-document-intelligence-with-new-snorkel-flow-fm-first-workflow/) · ["Safety sandwich" pattern](https://brain.co/blog/llm-generated-rules-engines-executable-if-then-logic-for-llm-explainability-in-regulated-industries)

Accuracy/latency/cost benchmarks: [FAITH — financial-table hallucination](https://arxiv.org/html/2508.05201v1) · [Multi-agent financial extraction, 10k SEC filings](https://arxiv.org/html/2603.22651v1) · [Agentic underwriting w/ adversarial critic](https://arxiv.org/html/2602.13213v2) · [Textract vs Document AI comparison](https://www.braincuber.com/blog/aws-textract-vs-google-document-ai-ocr-comparison) · [Agentic cost-per-query benchmark](https://acecloud.ai/blog/agentic-ai-cost-per-query-benchmark/)

Regulatory: [CFPB Circular 2022-03](https://www.consumerfinance.gov/compliance/circulars/circular-2022-03-adverse-action-notification-requirements-in-connection-with-credit-decisions-based-on-complex-algorithms/) · [CFPB 2023 AI credit-denial guidance](https://www.consumerfinance.gov/about-us/newsroom/cfpb-issues-guidance-on-credit-denials-by-lenders-using-artificial-intelligence/) · [Fannie Mae LL-2026-04](https://singlefamily.fanniemae.com/news-events/lender-letter-ll-2026-04-governance-framework-use-artificial-intelligence-and-machine-learning) ([Cooley analysis](https://finsights.cooley.com/fannie-mae-issues-ai-ml-governance-framework-for-sellers-and-servicers/)) · [Freddie/Fannie AI standards overview](https://www.harrisbeachmurtha.com/insights/fannie-mae-and-freddie-mac-set-new-ai-standards-for-mortgage-lenders/) · [OCC Bulletin 2026-13 (SR 26-2)](https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-13.html) · [FinRegLab explainability research](https://finreglab.org/research/explainability-fairness-in-machine-learning-for-credit-underwriting-policy-empirical-findings-overview/)

Nondeterminism & replay: [Thinking Machines — defeating LLM nondeterminism](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/) · [LLM output-drift study, financial tasks](https://arxiv.org/html/2511.07585v1) · [Replayable financial agents](https://arxiv.org/pdf/2601.15322)

Advisory-layer patterns: [deepset — AI loan underwriter](https://www.deepset.ai/blog/building-an-ai-loan-underwriter) · [Copilot guardrails in mortgage ops](https://mortgageworkspace.com/blog/microsoft-copilot-mortgage-operations-guide) · [LLM fraud/inconsistency detection](https://www.docvu.ai/role-of-ai-in-detecting-fraud-in-mortgage-documents/) · [LLMs in lending (SCNSoft)](https://www.scnsoft.com/lending/large-language-models)

**Evidence caveats:** Ocrolus/Truework/TurboPass accuracy figures are vendor self-reported. The agentic-underwriting quant results come from a commercial-*insurance* prototype — directionally applicable, not mortgage ground truth. LL-2026-04 details are via Fannie's landing page + legal analyses (primary PDF was 403-gated); confirm exact wording before quoting verbatim internally.
