# 12 — REST API Contracts

Requirements covered: FR-API-1..3, FR-LIN-1, FR-HMD-4, NFR-7. Base URL: `${BACKEND_URL}` (FastAPI, port 8000 dev). All bodies JSON; money/ratios are Decimal strings. The AG-UI agent endpoint (`/agent/underwriter`) and CopilotKit remote endpoint (`/copilotkit_remote`) are specified in `03 §5` and are not REST — this document covers the data plane the workbench reads.

---

## 1. Conventions

- IDs: ULID strings. Timestamps: UTC ISO-8601.
- Pagination: `?limit=` (default 50, max 500) & `?after=` (cursor = last seq/id).
- All endpoints are read-only except `POST /loans` and `POST /loans/{id}/run`.
- Auth is out of scope for the reference implementation (single-tenant dev); every mutating call carries `X-Actor-Id` header (recorded as actor; defaults to `system` — the internal-network build replaces this with the bank's SSO).

## 2. Error envelope (FR-API-3)

```jsonc
// non-2xx
{ "error": {
    "code": "PACKAGE_VALIDATION_FAILED",   // machine-readable, stable
    "message": "human readable",
    "violations": [{"path": "borrowers[0].ssn", "rule": "format", "detail": "..."}]  // optional
} }
```
Codes: `PACKAGE_VALIDATION_FAILED` (422), `NOT_FOUND` (404), `RUN_ALREADY_ACTIVE` (409), `RUN_NOT_INTERRUPTED` (409), `INTERNAL` (500).

## 3. Endpoints

### 3.1 `POST /loans` — submit a package
Body: loan package (`schemas/loan-package.schema.json`). 201 → `{"application_id": "...", "status": "received", "policy_pack_version": "conforming-2026.1.0"}`. 422 on Tier-1/2 validation (FR-PKG-1/-4).

### 3.2 `GET /loans` — queue
`?status=` filter. 200 → `{"items": [{"application_id","status","borrower_name","loan_amount","purpose","occupancy","received_at","decision_ready_at","suggested_action","interrupted": true|false}], "next": cursor}`.

### 3.3 `POST /loans/{id}/run` — start the pipeline
202 → `{"thread_id": id, "status": "in_review"}`. 409 `RUN_ALREADY_ACTIVE` if a run is executing; re-running a `suspended` loan is allowed (new run, same thread, audit-continuous).

### 3.4 `GET /loans/{id}` — deep-dive payload
200 →
```jsonc
{ "application": {...loan/property/borrower summaries...},
  "four_cs": {
    "credit":    {"representative_score": {"value":"742","lineage_ref":"L..."} , "open_disputes":0, "derogatories":[...]},
    "capacity":  {"front_ratio": TV, "back_ratio": TV, "qualifying_income_monthly": TV,
                  "pitia": {"principal_interest": TV, "taxes": TV, "hazard": TV, "mi": TV, "hoa": TV},
                  "income_components": [{"type","monthly_amount": TV,"calc_method","included","borrower_id"}]},
    "capital":   {"reserves_months": TV, "large_deposits": [...], "down_payment": TV},
    "collateral":{"ltv": TV, "cltv": TV, "appraised_value": TV, "property_type": "..."}
  },
  "atr": [8 factor rows], "discrepancies": [...], "red_flags": [...],
  "rules": {"overall","evaluations":[{"rule_id","description","outcome","reason_code","inputs":[{"path","value","lineage_ref"}]}]},
  "aus": {"recommendation","simulator_version","breakdown","messages":[{"message_id","category","text"}]},
  "conditions": [...], "status": "...", "narrative": "..." | null }
```
(`TV` = TracedValue `{value, lineage_ref}` — every displayed number is clickable, FR-LIN-2.)

### 3.5 `GET /loans/{id}/decision` — decision + provenance (NFR-7)
200 → decision row + `versions` block (pack, manifest sha, prompts, model ids, simulator, code git sha, llm_provider) + `snapshot_hash` + override record + adverse-action presence flag. 404 until finalized.

`GET /loans/{id}/adverse-action` → the notice (principal reasons, FCRA block, body_text). 404 unless declined.

`POST /loans/{id}/replay` → runs §11.7 replay on the sealed snapshot; 200 → `{"identical": true}` or the structured diff. (Read-only in effect; POST because it computes.)

### 3.6 HMDA & monitoring (FR-HMD-4)
`GET /hmda/records?from=&to=` → HMDA rows (no demographics).
`GET /hmda/monitoring-extract` → decisions ⨝ demographics for fair-lending analysis. Response header `X-Purpose: fair-lending-monitoring-only`; this endpoint lives in `api/` (allowed importer, `04 §6`) and is the ONLY read path exposing demographics.

### 3.7 `GET /lineage/{ref}` (FR-LIN-1)
200 → `{"node": LineageNode, "ancestors": [LineageNode...]}` breadth-first, depth ≤ 25, deduped. 404 unknown ref.

### 3.8 Audit
`GET /loans/{id}/audit?after=&limit=&event_type=` → `{"items": [AuditEvent], "next": cursor}` (payload_json parsed into `payload`).
`GET /loans/{id}/audit/verify` → `{"chain_ok": bool, "events_total": N, "app_events": M, "first_broken_seq": null|n, "sealed": bool, "snapshot_hash": "..."|null}`.
`GET /loans/{id}/audit/export` → the loan's events + snapshot as a single JSON document (`Content-Disposition: attachment`).

## 4. OpenAPI

FastAPI auto-generates `/openapi.json`; T-API-1 validates the served schema contains every endpoint above with the documented status codes, and exercises each happy path + error envelope against a seeded archetype.
