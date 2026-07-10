# 10 — LLM Usage Register & Provider Abstraction

Requirements covered: FR-LLM-1..5, FR-EXT-1..4, HR-1, HR-9, HR-10. This document is the **exhaustive inventory of every LLM touchpoint** in the system (GSE AI-inventory artifact, `02 §6`) and the contract that makes the provider swappable.

**Current provider: Anthropic** (`anthropic` Python SDK). This choice is explicitly temporary; the bank will substitute its approved provider. Everything Anthropic-specific is confined to one file (§2) and flagged **[ANTHROPIC-SPECIFIC]** throughout this spec.

---

## 1. Division of labor (HR-1 — restated because everything depends on it)

| Task | Who does it | Why |
|---|---|---|
| Eligibility decisions | policy engine (deterministic) | ECOA/Reg B: reasons must reflect actual basis |
| Risk recommendation | AUS simulator (deterministic) | reproducibility |
| Final action | human underwriter | GSE mandates, four-eyes |
| Document field extraction | **LLM** | unstructured→structured is the LLM's legitimate strength; output is persisted, confidence-scored, human-verifiable, and cross-checked (06 §7) before any rule consumes it |
| Narrative summaries (4 Cs) | **LLM** | display prose only; never parsed back into logic |
| Condition text drafting | **LLM** (deterministic template fallback) | wording aid; category/source deterministic; human-editable |
| Chat Q&A | **LLM** with read-only grounded tools | explains persisted state; cannot mutate it |
| Adverse-action reasons | **never LLM** (HR-10) | fixed ECOA texts from reason codes |

## 2. Provider abstraction (`backend/app/llm/`) (FR-LLM-1, HR-9)

```python
class LLMClient(Protocol):
    async def extract(self, req: ExtractionRequest) -> ExtractionResult: ...
    async def narrate(self, req: NarrativeRequest) -> str: ...
    async def draft(self, req: DraftRequest) -> str: ...
    async def chat(self, req: ChatRequest) -> ChatResult: ...   # supports tool-use loop

@dataclass(frozen=True)
class CallRecord:            # produced for EVERY call, feeds the llm_call audit event
    prompt_id: str; prompt_version: str
    model_id: str; params: dict          # temperature, max_tokens
    input_sha256: str; output_sha256: str
    input_tokens: int; output_tokens: int
    latency_ms: int; retries: int
```

Implementations:
- `anthropic_client.py` — **the only module importing `anthropic`** (T-LLM-3 asserts via import-graph scan). **[ANTHROPIC-SPECIFIC]** notes: messages API with `system` prompt from template; tool-use blocks for chat tools; `temperature=0` for extraction; model id from `LLM_MODEL` env (default `claude-sonnet-4-6`), passed through verbatim to `CallRecord.model_id` — never hardcode model ids at call sites.
- `mock_client.py` — deterministic (FR-LLM-4): `extract` returns the document's `ground_truth` sidecar verbatim with `confidence=0.99`; `narrate`/`draft` return template-rendered deterministic text; `chat` executes the tool loop with a scripted planner (keyword→tool mapping) — no network, no keys.

Selection: `LLM_PROVIDER` env (`mock` | `anthropic`) resolved once at startup in `config.py`; injected into nodes via the graph's context — call sites never branch on provider.

## 3. The register (FR-LLM-3 — exhaustive; runtime-enforced)

A call with a `prompt_id` not listed here MUST be rejected by `prompt_registry.py` at runtime. Adding a call site = adding a row here + a prompt file + register entry in `prompts/registry.json`.

| # | Call site (node/tool) | Prompt id | Purpose | Inputs | Output contract | Why an LLM | Failure behavior |
|---|---|---|---|---|---|---|---|
| 1 | `document_extraction` | `extraction/paystub` | field extraction | paystub text | JSON: gross_pay_period, pay_frequency, ytd_gross, employer, pay_date (+confidence each) | unstructured text | retry ×1 → `extraction_failed` + condition (FR-EXT-3) |
| 2 | 〃 | `extraction/w2` | 〃 | W-2 text | wages_box1, employer, tax_year | 〃 | 〃 |
| 3 | 〃 | `extraction/tax-return-1040` | 〃 | 1040 text | wages, agi, tax_year, schedule_c_attached | 〃 | 〃 |
| 4 | 〃 | `extraction/schedule-c` | 〃 | Sched C text | net_profit, depreciation, depletion, home_office, tax_year | 〃 | 〃 |
| 5 | 〃 | `extraction/bank-statement` | 〃 | statement text | ending_balance, period, deposits[] {amount,date,description} | 〃 | 〃 |
| 6 | 〃 | `extraction/appraisal` | 〃 | appraisal text | appraised_value, effective_date, property_type, condition_rating | 〃 | 〃 |
| 7 | 〃 | `extraction/urla-1003` | 〃 | URLA text | declarations{}, stated fields cross-check set | 〃 | 〃 |
| 8 | 〃 | `extraction/gift-letter` | 〃 | gift letter text | donor, amount, relationship, no_repayment_clause | 〃 | 〃 |
| 9 | 〃 | `extraction/lease` | 〃 | lease text | monthly_rent, term, tenant | 〃 | 〃 |
| 10 | `condition_synthesis` | `conditions/draft-condition` | wording of a condition from structured source finding | finding JSON | 1–2 sentence directive text | fluent, borrower-actionable wording | deterministic template fallback (FR-CND-2) |
| 11 | `prepare_decision` node (persisted on the application row; served by `GET /loans/{id}`) | `narrative/four-cs-summary` | 3–5 sentence underwriter-style summary | 4Cs summaries + red flags JSON | prose (display only) | readable synthesis | narrative = null; card shows structured data only |
| 12 | chat node | `chat/workbench-qa` | grounded Q&A + tool orchestration | user msg + tool results | prose + tool calls | conversational interface | chat returns error bubble; pipeline unaffected |

**Never-list (asserted by T-LLM-1):** no LLM call exists in `policy_engine/`, `aus/`, `domain/`, `audit/`, `adverse_action` node, or `human_review` node.

## 4. Per-call governance (FR-LLM-2, FR-EXT-2)

Every call, both providers, emits an `llm_call` audit event from `CallRecord`: prompt id+version, exact model id, params, token counts, input/output sha256 (contents themselves stay in `extracted_fields` / chat transcripts — hashes make the event chain content-addressable without duplicating PII into the ledger). Extraction rows store prompt/model versions directly (FR-EXT-2), so any extracted number's lineage names the exact prompt+model that produced it.

## 5. Prompt registry (`specs/prompts/`, shipped to `policy/prompts/`)

Prompt file shape (YAML):
```yaml
id: extraction/paystub
version: 1              # file name carries it too: paystub.v1.yaml
model_params: {temperature: 0, max_tokens: 1024}
output_schema: {...}    # JSON Schema the response must validate against
template: |
  You are extracting fields from a paystub. Return ONLY JSON matching the schema.
  <document>{{document_text}}</document>
  ...
```
Rules: files are immutable per version (change = new `vN+1` file); `registry.json` lists active versions; the active set is pinned at run start and recorded in the DecisionSnapshot (HR-7). Prompt changes require rerunning extraction goldens (T-EXT-1) before activation.

## 6. Provider swap procedure (the reason this document exists)

To replace Anthropic with provider X:

1. Implement `LLMClient` in a new `x_client.py` (the only file importing X's SDK). Map: system+user prompting, JSON-mode/structured output for extraction, tool-use loop for chat. Register in `config.py` provider table.
2. Grep-audit: `anthropic` must appear **only** in `anthropic_client.py`, `requirements.txt`, and this spec (T-LLM-3 is the automated version).
3. Re-run the eval gates: extraction goldens across all 15 archetypes (field-level exact match on mock-comparable fields; ≥ 98% numeric-field exact match on live provider vs ground truth), condition-draft schema conformance, chat tool-selection smoke set.
4. Update `LLM_MODEL` + this register's **[ANTHROPIC-SPECIFIC]** notes; bump register version header.
5. Decisions are unaffected by construction (HR-1) — but run the corpus regression (T-DAT-3) and diff decision distributions to prove it: **the report must show zero decision-level differences** (only extraction confidence/narrative text may differ).

What does NOT change on swap: prompts' output schemas, the audit event shape, the register structure, all deterministic components, all tests except provider-specific eval baselines.
