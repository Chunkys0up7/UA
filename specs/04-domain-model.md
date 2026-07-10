# 04 — Domain Model & Persistence

Requirements covered: FR-CAL-7, FR-LIN-1, FR-HMD-1..3, FR-AAN-3, FR-PKG-5. Storage: SQLite (WAL) via SQLAlchemy 2.0 async; Postgres dialect noted where it differs. All timestamps UTC ISO-8601 strings; all money/ratios stored as TEXT holding `Decimal` canonical strings; IDs are ULIDs (26-char Crockford base32).

---

## 1. Entity map

```
LoanApplication 1─* Borrower 1─* EmploymentRecord
LoanApplication 1─1 PropertyAppraisal
LoanApplication 1─* DocumentRecord 1─* ExtractedField
LoanApplication 1─* IncomeComponent (per borrower)      ─┐
LoanApplication 1─1 CreditProfile (loan-level rollup)    │ every computed number
LoanApplication 1─1 AssetProfile 1─* LargeDeposit        ├─ is a TracedValue with
LoanApplication 1─1 DtiCalculation                       │ a LineageNode row
LoanApplication 1─8 AtrEvaluation                        ─┘
LoanApplication 1─* RuleEvaluationRecord
LoanApplication 1─1 AusFindings 1─* AusMessage
LoanApplication 1─* Condition
LoanApplication 1─* RedFlag
LoanApplication 1─* Discrepancy
LoanApplication 0─1 UnderwritingDecision 0─1 OverrideRecord
LoanApplication 0─1 AdverseActionNotice
LoanApplication 1─1 HmdaRecord          (hmda/ module)
LoanApplication 0─1 HmdaDemographics    (ISOLATED — see §6)
LoanApplication 1─* AuditEvent          (audit.db, append-only)
LoanApplication 0─1 DecisionSnapshot    (audit.db)
```

## 2. Status machine (LoanApplication.status)

```
received ──► in_review ──► ready_for_decision ──► approved_with_conditions
                 │                      │───────► suspended        (re-runnable)
                 │                      │───────► declined         (terminal)
                 │                      └───────► counteroffer     (revalidated, then terminal or re-gated)
                 └────────► suspended   (pipeline halt, e.g. OFAC hit — 09 §3.3; re-runnable)
```
Transitions happen only in graph nodes (`09 §4`) and each emits a `state_change` audit event. Timestamps for `received`, `review_started` (first node), `decision_ready` (interrupt raised), `decided` (finalize) are stored on the row (FR-HMD-2).

## 3. Lineage model (HR-3)

```python
class TracedValue(BaseModel):
    value: str            # Decimal canonical string (or scalar as string)
    lineage_ref: str      # ULID of a LineageNode

class LineageNode(BaseModel):
    ref: str              # ULID
    application_id: str
    kind: Literal["extracted_field", "package_stated", "calculation",
                  "rule_input", "adapter_result", "constant_policy"]
    label: str            # e.g. "qualifying_monthly_income", "dti_back"
    value: str
    method: str | None    # e.g. "two_year_average", "banker_round_3dp"
    parents: list[str]    # lineage refs of operands (empty for leaves)
    source_id: str | None # extracted_field.id | document.id | rule_id | adapter name
    meta: dict            # e.g. {"confidence": 0.94, "prompt": "extraction/paystub@v1", "model": "claude-sonnet-4-6"}
```

Resolution contract (FR-LIN-1): `GET /lineage/{ref}` returns the node plus ancestors, breadth-first, depth-capped at 25, deduplicated. Leaves are always `extracted_field`, `package_stated`, `adapter_result`, or `constant_policy` (policy thresholds cite pack version in `meta`).

## 4. Table definitions (normative DDL — loans.db)

```sql
CREATE TABLE loan_applications (
  id TEXT PRIMARY KEY, status TEXT NOT NULL,
  loan_amount TEXT NOT NULL, loan_purpose TEXT NOT NULL,       -- purchase|rate_term_refi|cash_out_refi
  occupancy TEXT NOT NULL,                                     -- primary|second_home|investment
  loan_type TEXT NOT NULL DEFAULT 'conventional_conforming',
  note_rate TEXT NOT NULL, term_months INTEGER NOT NULL,
  mlo_nmls_id TEXT NOT NULL,
  policy_pack_version TEXT NOT NULL,                           -- pinned at acceptance (FR-PKG-3)
  county_high_cost INTEGER NOT NULL DEFAULT 0,
  received_at TEXT NOT NULL, review_started_at TEXT, decision_ready_at TEXT, decided_at TEXT,
  package_json TEXT NOT NULL                                   -- the accepted raw package (immutable copy)
);

CREATE TABLE borrowers (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES loan_applications(id),
  full_name TEXT NOT NULL, ssn_last4 TEXT NOT NULL,            -- full SSN never stored outside package_json
  is_primary INTEGER NOT NULL, self_employed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE documents (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL, borrower_id TEXT,
  doc_type TEXT NOT NULL,        -- paystub|w2|tax_return_1040|schedule_c|bank_statement|tri_merge_credit|appraisal|urla_1003|voe|gift_letter|lease
  period_label TEXT,             -- e.g. "2025-12", "2024 tax year"
  text_rendering TEXT NOT NULL, sha256 TEXT NOT NULL,
  ground_truth_json TEXT         -- synthetic sidecar (mock provider + goldens)
);

CREATE TABLE extracted_fields (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL, document_id TEXT NOT NULL REFERENCES documents(id),
  field_name TEXT NOT NULL, value TEXT NOT NULL, confidence REAL NOT NULL,
  prompt_id TEXT NOT NULL, prompt_version TEXT NOT NULL, model_id TEXT NOT NULL,
  llm_call_event_id TEXT NOT NULL,                             -- FK into audit event (cross-db by id)
  status TEXT NOT NULL DEFAULT 'ok'                            -- ok|extraction_failed
);

CREATE TABLE lineage_nodes (
  ref TEXT PRIMARY KEY, application_id TEXT NOT NULL,
  kind TEXT NOT NULL, label TEXT NOT NULL, value TEXT NOT NULL,
  method TEXT, parents_json TEXT NOT NULL DEFAULT '[]',
  source_id TEXT, meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_lineage_app ON lineage_nodes(application_id);

CREATE TABLE income_components (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL, borrower_id TEXT NOT NULL,
  income_type TEXT NOT NULL,     -- base|overtime|bonus|commission|self_employed|rental|other
  monthly_amount TEXT NOT NULL, monthly_amount_ref TEXT NOT NULL,   -- TracedValue
  calc_method TEXT NOT NULL, included INTEGER NOT NULL DEFAULT 1,
  exclusion_reason TEXT
);

CREATE TABLE credit_profiles (
  application_id TEXT PRIMARY KEY,
  scores_json TEXT NOT NULL,     -- per borrower per bureau
  representative_score INTEGER NOT NULL, representative_score_ref TEXT NOT NULL,
  open_disputes INTEGER NOT NULL, derogatories_json TEXT NOT NULL,
  monthly_liabilities TEXT NOT NULL, monthly_liabilities_ref TEXT NOT NULL
);

CREATE TABLE asset_profiles (
  application_id TEXT PRIMARY KEY,
  liquid_total TEXT NOT NULL, liquid_total_ref TEXT NOT NULL,
  retirement_total TEXT NOT NULL, down_payment TEXT NOT NULL,
  reserves_months TEXT NOT NULL, reserves_months_ref TEXT NOT NULL
);

CREATE TABLE large_deposits (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
  account_ref TEXT NOT NULL, amount TEXT NOT NULL, deposit_date TEXT NOT NULL,
  pct_of_monthly_income TEXT NOT NULL, sourced INTEGER NOT NULL, source_doc_id TEXT
);

CREATE TABLE dti_calculations (
  application_id TEXT PRIMARY KEY,
  pitia_json TEXT NOT NULL,      -- {principal_interest, taxes, hazard_ins, mi, hoa} each a TracedValue
  qualifying_monthly_income TEXT NOT NULL, qualifying_monthly_income_ref TEXT NOT NULL,
  monthly_liabilities TEXT NOT NULL,
  front_ratio TEXT NOT NULL, front_ratio_ref TEXT NOT NULL,
  back_ratio TEXT NOT NULL, back_ratio_ref TEXT NOT NULL
);

CREATE TABLE atr_evaluations (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
  factor_number INTEGER NOT NULL CHECK(factor_number BETWEEN 1 AND 8),
  factor_name TEXT NOT NULL, basis TEXT NOT NULL, evidence_ref TEXT NOT NULL,   -- lineage ref
  UNIQUE(application_id, factor_number)
);

CREATE TABLE rule_evaluations (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL, run_seq INTEGER NOT NULL,
  rule_id TEXT NOT NULL, ruleset TEXT NOT NULL, pack_version TEXT NOT NULL,
  inputs_json TEXT NOT NULL,     -- [{path, value, lineage_ref}]
  outcome TEXT NOT NULL,         -- pass|fail|refer
  reason_code TEXT,              -- required when outcome != pass (FR-POL-4)
  counteroffer_hint_json TEXT
);

CREATE TABLE aus_findings (
  application_id TEXT PRIMARY KEY, recommendation TEXT NOT NULL,
  simulator_version TEXT NOT NULL, score_breakdown_json TEXT NOT NULL
);
CREATE TABLE aus_messages (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL, message_id TEXT NOT NULL,
  category TEXT NOT NULL CHECK(category IN ('PTA','PTD','PTF')), text TEXT NOT NULL
);

CREATE TABLE conditions (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
  category TEXT NOT NULL CHECK(category IN ('PTA','PTD','PTF')),
  title TEXT NOT NULL, text TEXT NOT NULL,
  source_kind TEXT NOT NULL,     -- rule|aus_message|discrepancy|red_flag|manual
  source_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',   -- open|waived (clearing is out of scope)
  drafted_by_llm INTEGER NOT NULL DEFAULT 0, human_edited INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE red_flags (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
  flag_code TEXT NOT NULL, severity TEXT NOT NULL CHECK(severity IN ('info','elevated','critical')),
  description TEXT NOT NULL, evidence_ref TEXT NOT NULL, recommended_action TEXT NOT NULL
);

CREATE TABLE discrepancies (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
  field TEXT NOT NULL, stated_value TEXT NOT NULL, documented_value TEXT NOT NULL,
  tolerance TEXT NOT NULL, exceeded INTEGER NOT NULL, lineage_ref TEXT NOT NULL
);

CREATE TABLE underwriting_decisions (
  application_id TEXT PRIMARY KEY,
  action TEXT NOT NULL,          -- approve_with_conditions|suspend|decline|counteroffer
  suggested_action TEXT NOT NULL,
  decided_by TEXT NOT NULL, second_reviewer TEXT, decided_at TEXT NOT NULL,
  reason_codes_json TEXT NOT NULL DEFAULT '[]',
  counteroffer_terms_json TEXT,
  hmda_action_taken INTEGER,                -- NULL while suspended/pending (04 §5)
  snapshot_hash TEXT             -- filled by audit_seal
);

CREATE TABLE override_records (
  id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
  suggested_action TEXT NOT NULL, actual_action TEXT NOT NULL,
  justification TEXT NOT NULL, decided_by TEXT NOT NULL,
  second_reviewer TEXT, created_at TEXT NOT NULL
);

CREATE TABLE adverse_action_notices (
  application_id TEXT PRIMARY KEY, generated_at TEXT NOT NULL,
  principal_reasons_json TEXT NOT NULL,     -- [{reason_code, ecoa_text, hmda_code}]
  fcra_block_json TEXT NOT NULL,            -- {score, range_low, range_high, score_date, key_factors[], bureaus[]}
  body_text TEXT NOT NULL                   -- assembled notice (template + fixed reason texts)
);
```

`hmda_records` and `hmda_demographics` are defined in §5/§6. Audit tables are defined in `11-audit-repeatability.md §2` (they live in `audit.db`).

Postgres dialect deltas: `TEXT`→`text`, `INTEGER` booleans→`boolean`, triggers per 11 §2.2; otherwise identical.

## 5. HMDA record (FR-HMD-1..2, FR-AAN-3)

```sql
CREATE TABLE hmda_records (
  application_id TEXT PRIMARY KEY,
  action_taken INTEGER,          -- 1 approved/originated-proxy, 2 approved-not-accepted, 3 denied, 4 withdrawn, 5 incomplete
  action_date TEXT,
  denial_reasons_json TEXT NOT NULL DEFAULT '[]',   -- HMDA codes from selected reason codes
  loan_amount TEXT NOT NULL, loan_purpose TEXT NOT NULL, occupancy TEXT NOT NULL,
  property_state TEXT NOT NULL, property_county TEXT NOT NULL
);
```

Mapping from decision → action_taken: `approve_with_conditions → 1` (proxy for approved; origination out of scope), `counteroffer accepted-equivalent → 1`, `counteroffer (not accepted) → 3 with counteroffer flag`, `decline → 3`, `suspend → NULL (pending)`. The state machine module `hmda/action_taken.py` owns this mapping; nodes call it, never set codes directly.

## 6. Demographics isolation (HR-6, FR-HMD-3)

```sql
CREATE TABLE hmda_demographics (          -- populated from package intake ONLY
  application_id TEXT PRIMARY KEY,
  ethnicity TEXT, race TEXT, sex TEXT, age_band TEXT,
  collection_method TEXT NOT NULL DEFAULT 'applicant_provided'
);
```

- Lives in module `backend/app/hmda/demographics.py`; the ONLY importers allowed are `api/` (intake write + monitoring export read) and tests.
- **T-ISO-1** walks the import graph (AST-based) of `agent/`, `policy_engine/`, `aus/`, `domain/` and fails if any module imports `hmda.demographics` or references its table name.
- The loan-package schema places demographics in a top-level `hmda_demographics` block that the intake handler strips before the package is passed to the pipeline (the pipeline receives a package object with no demographics attribute at the type level).

## 7. Repository layer

`persistence/repositories.py` exposes: `LoanRepo`, `LineageRepo`, `AnalysisRepo` (income/credit/assets/DTI/ATR), `RulesRepo`, `ConditionsRepo`, `DecisionRepo`, `HmdaRepo` — async, one class per aggregate; **`AuditRepo` is append-only by construction** (no update/delete methods exist) and is the only writer to `audit.db` besides snapshot storage. Sessions: one per graph node execution; commits at node end so each node is atomic (a crashed node re-executes cleanly from the checkpoint).
