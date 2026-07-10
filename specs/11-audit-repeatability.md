# 11 — Audit Ledger & Repeatability

Requirements covered: FR-AUD-1..8, HR-4, HR-5, HR-7, NFR-7, NFR-8. This is the system's spine of trust: an append-only, hash-chained event ledger plus sealed, replayable decision snapshots. If any other component conflicts with this spec, **this spec wins**.

---

## 1. Principles

1. **Append-only, forever.** Corrections are new events referencing the corrected event id. Nothing is updated or deleted, enforced *below* the application layer (§2).
2. **Hash-chained.** Every event commits to its predecessor; tampering breaks the chain at a provable sequence number.
3. **Content-complete.** Reading the ledger alone tells the full story of a decision: what ran, in what order, with which versions, who acted, what they saw, and why.
4. **Replayable.** The seal event + snapshot reproduce the decision byte-exactly.

## 2. Storage (`data/db/audit.db` — physically separate file)

```sql
CREATE TABLE audit_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,      -- global monotonic
  event_id TEXT NOT NULL UNIQUE,              -- ULID
  application_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  actor TEXT NOT NULL,                        -- 'system' | 'agent' | 'underwriter:<id>'
  payload_json TEXT NOT NULL,                 -- canonical JSON (§4.1)
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL,
  created_at TEXT NOT NULL                    -- UTC ISO-8601 with ms
);
CREATE INDEX idx_audit_app ON audit_events(application_id, seq);

CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

CREATE TABLE decision_snapshots (
  application_id TEXT PRIMARY KEY,
  snapshot_json TEXT NOT NULL,                -- canonical JSON (§6)
  sha256 TEXT NOT NULL,
  sealed_at TEXT NOT NULL
);
CREATE TRIGGER snap_no_update BEFORE UPDATE ON decision_snapshots
BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
CREATE TRIGGER snap_no_delete BEFORE DELETE ON decision_snapshots
BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
```

**§2.2 Postgres dialect:** same shape; triggers `BEFORE UPDATE OR DELETE ... EXECUTE FUNCTION raise_append_only()` with a one-line plpgsql raiser; `seq BIGSERIAL`.

The chain is **global** (one chain per database, not per application) — interleaved events from concurrent runs strengthen tamper evidence (an attacker must recompute everyone's suffix). `idx_audit_app` serves per-loan timelines.

## 3. Event catalogue (FR-AUD-1)

| event_type | Emitted by | Payload (canonical keys) |
|---|---|---|
| `package_accepted` | API intake | package_sha256, document_count, pack_version |
| `state_change` | nodes | from, to |
| `llm_call` | LLMClient wrapper | prompt_id, prompt_version, model_id, params, input_sha256, output_sha256, input_tokens, output_tokens, latency_ms, retries, call_site |
| `adapter_call` | adapters | adapter_name, adapter_version, request_summary, result_summary, permissible_purpose? |
| `calculation_set` | analysis nodes | dimension, labels→lineage_refs map |
| `discrepancy_found` | data_verification | field, stated, documented, tolerance, exceeded |
| `red_flag` | fraud_screen | flag_code, severity, evidence_ref |
| `rule_eval_batch` | rules_eval | pack_version, pack_manifest_sha256, results[] {rule_id, outcome, reason_code} |
| `aus_run` | aus_simulate | simulator_version, recommendation, breakdown |
| `condition_created` | condition_synthesis | condition_id, category, source_kind, source_id, drafted_by_llm |
| `decision_packet_ready` | prepare_decision | suggested_action, failed_rule_ids, four_eyes_required, packet_sha256 |
| `human_action` | human_review | action, underwriter_id, second_reviewer_id?, reason_codes[], condition_edits_count |
| `override` | human_review | suggested_action, actual_action, justification, underwriter_id, second_reviewer_id? |
| `adverse_action_generated` | adverse_action | reason_codes[], fcra_score, notice_sha256 |
| `hmda_action_taken` | finalize | action_taken, denial_reasons[] |
| `tool_call` | chat node | tool, args_sha256, result_sha256 |
| `node_error` | any node | node, error_class, message (PII-masked) |
| `seal` | audit_seal | snapshot_sha256, decision_action, pack_version, prompt_versions{}, model_ids[], simulator_version, code_git_sha |

## 4. Hash chain (FR-AUD-2)

```
hash = SHA256( prev_hash || event_id || event_type || payload_json || created_at )
```
concatenation with `\x1f` (unit separator) between fields; hex-lowercase digests; first event in a database has `prev_hash = "GENESIS"`.

### 4.1 Canonical JSON (FR-AUD-7)
`canonical(obj)`: UTF-8; object keys sorted lexicographically at every level; no insignificant whitespace (`,`/`:` separators); `Decimal` serialized as its `str()` canonical form (no float round-trip, no exponent normalization surprises — quantized as stored); no NaN/Inf; arrays order-preserving. One shared implementation `audit/canonical.py` used for hashing, snapshots, and packet checksums (divergent implementations are the classic hash-mismatch bug — there must be exactly one).

### 4.2 Write protocol
`audit/ledger.py.append(event)` is the sole writer: acquires a process-wide asyncio lock → reads `(seq, hash)` of the last row → computes the new hash → inserts → returns the event. The lock serializes the chain; SQLite WAL keeps readers unblocked. Multi-process deployment (Postgres profile) replaces the lock with `SELECT ... FOR UPDATE` on a chain-head row.

## 5. Verification (FR-AUD-4)

`audit/verify.py.verify_chain(db, from_seq=1) -> VerifyResult`:
walks rows in seq order, recomputes each hash from stored fields + previous stored hash, and reports `{ok: true, events: N}` or `{ok: false, first_broken_seq, expected_hash, stored_hash}`. Exposed as `GET /loans/{id}/audit/verify` (verifies the whole chain, reports app-relevant summary + global integrity) and CLI `scripts/verify-audit.ps1`. T-AUD-2 flips one byte via raw connection with triggers disabled on a **copy** and asserts the exact break seq is reported.

## 6. DecisionSnapshot (FR-AUD-5, NFR-7; schema `schemas/decision-snapshot.schema.json`)

Frozen at `audit_seal`, canonical JSON, SHA-256 stored in the seal event and on the decision row:

```jsonc
{
  "snapshot_version": "1",
  "application_id": "...",
  "sealed_at": "...",
  "versions": {
    "policy_pack": "conforming-2026.1.0", "policy_pack_manifest_sha256": "...",
    "prompts": {"extraction/paystub": 1, "conditions/draft-condition": 1, ...},
    "model_ids": ["claude-sonnet-4-6"],           // every distinct model used in the run
    "aus_simulator": "du-sim.v1",
    "code_git_sha": "...", "llm_provider": "mock|anthropic"
  },
  "inputs": {
    "package_sha256": "...",
    "extracted_fields": [{"id","document_id","field_name","value","confidence","prompt","model"}],
    "adapter_results": [{"adapter","version","result"}]
  },
  "computed": {
    "income_components": [...], "dti": {...}, "ltv": {...}, "reserves": {...},
    "representative_score": ..., "atr": [8 rows], "red_flags": [...], "discrepancies": [...]
  },
  "rules": {"evaluations": [every RuleEvaluationRecord], "overall": "...", "counteroffer_hints": [...]},
  "aus": {"recommendation": "...", "breakdown": {...}, "messages": [...]},
  "conditions": [...],
  "decision": {"action","suggested_action","decided_by","second_reviewer","reason_codes",
               "override": {...}|null, "counteroffer_terms": {...}|null, "hmda_action_taken": n},
  "adverse_action_notice_sha256": "..."|null
}
```

## 7. Replay (FR-AUD-6, HR-5)

`audit/snapshot.py.replay(snapshot) -> ReplayResult`:
1. Load the **pinned** pack version from disk; verify its manifest hash equals `versions.policy_pack_manifest_sha256` (a replaced pack file is detected, not silently used).
2. Rebuild the evaluation context **from the snapshot's inputs and computed values' inputs** — i.e., re-run the pure calculations (income → DTI → LTV → reserves → score → compensating factors) from `inputs.extracted_fields` + package facts.
3. Re-run `RulesEngine.evaluate` and the AUS simulator (pinned config version).
4. Compare, field-by-field: every recomputed value equals the snapshot's `computed` value; every rule evaluation equals (id, outcome, reason_code); AUS recommendation equals.
5. Return `{identical: true}` or a structured diff. **Acceptance: identical, for every sealed decision, always** (T-REP-1). The human decision itself is not "replayed" — it is attested by the `human_action` event inside the sealed chain.

Replay never calls the LLM: extraction outputs are snapshot inputs. This is deliberate — repeatability is defined over the deterministic core, with the human-verifiable extraction layer as recorded evidence (HR-1 makes this sound).

## 8. PII handling in observability (FR-AUD-8)

- structlog processor masks `ssn`, `dob`, `account_number` patterns (regex + known field names) in **all application logs**.
- Ledger payloads carry hashes or last-4 forms where identification is needed (`ssn_last4`); full PII lives only in `package_json` and `extracted_fields` (loans.db), which is the encryptable-at-rest surface.
- `event_type`, `actor`, and all payload **keys** are PII-free by catalogue construction (§3).

## 9. Retention (NFR-8)

No code path deletes, expires, truncates, or compacts `audit.db` content. Backup/retention procedure documented in README (copy the .db files; verify chain post-copy). Design posture: ≥ 7 years (GSE practice) — exceeds ECOA 25 months / Reg Z & HMDA 3 years (`02 §1–3`).
