"""Append-only, hash-chained audit ledger (specs/11 §2–§4, HR-4).

Storage enforces immutability BELOW the application layer: SQLite
triggers RAISE(ABORT) on UPDATE/DELETE (T-AUD-3). The chain is global
per database (specs/11 §2): hash = SHA-256(prev_hash 0x1F event_id 0x1F
event_type 0x1F canonical_payload 0x1F created_at), GENESIS-rooted.

Writes are serialized under a lock so the chain stays linear; SQLite WAL
keeps readers unblocked. Sync sqlite3 by design — the ledger is
low-throughput and a sync implementation is simpler to prove correct;
async callers wrap `append` in asyncio.to_thread.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import ulid

from app.audit.canonical import canonical_json

_SEP = "\x1f"
GENESIS = "GENESIS"

DDL = """
CREATE TABLE IF NOT EXISTS audit_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  application_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  actor TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_app ON audit_events(application_id, seq);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

CREATE TABLE IF NOT EXISTS decision_snapshots (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,   -- multiple decisions per loan over
  application_id TEXT NOT NULL,            -- its life (suspend -> re-run -> decide)
  snapshot_json TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  sealed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_app ON decision_snapshots(application_id, seq);
CREATE TRIGGER IF NOT EXISTS snap_no_update BEFORE UPDATE ON decision_snapshots
BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS snap_no_delete BEFORE DELETE ON decision_snapshots
BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
"""

EVENT_TYPES = frozenset({
    "package_accepted", "state_change", "llm_call", "adapter_call",
    "calculation_set", "discrepancy_found", "red_flag", "rule_eval_batch",
    "aus_run", "condition_created", "decision_packet_ready", "human_action",
    "override", "adverse_action_generated", "hmda_action_taken", "tool_call",
    "node_error", "seal",
})


def chain_hash(prev_hash: str, event_id: str, event_type: str,
               payload_json: str, created_at: str) -> str:
    material = _SEP.join([prev_hash, event_id, event_type, payload_json, created_at])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEvent:
    seq: int
    event_id: str
    application_id: str
    event_type: str
    actor: str
    payload_json: str
    prev_hash: str
    hash: str
    created_at: str


class AuditLedger:
    """The sole writer to audit.db (specs/11 §4.2)."""

    def __init__(self, db_path: Path | str):
        self._path = str(db_path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(DDL)
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # NB: sqlite3's own context manager commits but never CLOSES —
        # leaked connections keep the WAL from checkpointing. Close always.
        with closing(sqlite3.connect(self._path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn

    def append(
        self,
        *,
        application_id: str,
        event_type: str,
        actor: str,
        payload: dict[str, Any],
        created_at: str | None = None,
    ) -> AuditEvent:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event_type {event_type!r} (specs/11 §3)")
        payload_json = canonical_json(payload)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev_hash = row[0] if row else GENESIS
            event_id = str(ulid.new())
            ts = created_at or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            digest = chain_hash(prev_hash, event_id, event_type, payload_json, ts)
            cursor = conn.execute(
                "INSERT INTO audit_events (event_id, application_id, event_type,"
                " actor, payload_json, prev_hash, hash, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, application_id, event_type, actor, payload_json,
                 prev_hash, digest, ts),
            )
            conn.commit()
            return AuditEvent(cursor.lastrowid, event_id, application_id,
                              event_type, actor, payload_json, prev_hash,
                              digest, ts)

    def events(self, application_id: str | None = None) -> list[AuditEvent]:
        with self._connect() as conn:
            if application_id:
                rows = conn.execute(
                    "SELECT seq, event_id, application_id, event_type, actor,"
                    " payload_json, prev_hash, hash, created_at FROM audit_events"
                    " WHERE application_id = ? ORDER BY seq", (application_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT seq, event_id, application_id, event_type, actor,"
                    " payload_json, prev_hash, hash, created_at FROM audit_events"
                    " ORDER BY seq",
                ).fetchall()
        return [AuditEvent(*row) for row in rows]

    # ------------------------------------------------------------ snapshots
    def store_snapshot(self, application_id: str, snapshot_json: str,
                       sha256: str, sealed_at: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO decision_snapshots (application_id, snapshot_json,"
                " sha256, sealed_at) VALUES (?, ?, ?, ?)",
                (application_id, snapshot_json, sha256, sealed_at),
            )
            conn.commit()

    def get_snapshot(self, application_id: str) -> tuple[str, str] | None:
        """Latest sealed decision (decision HISTORY via snapshots_for)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT snapshot_json, sha256 FROM decision_snapshots"
                " WHERE application_id = ? ORDER BY seq DESC LIMIT 1",
                (application_id,),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def snapshots_for(self, application_id: str) -> list[tuple[int, str, str, str]]:
        """Full decision history, oldest first: (seq, snapshot_json, sha256,
        sealed_at). Every decision a loan has ever received (FR-AUD-5)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, snapshot_json, sha256, sealed_at"
                " FROM decision_snapshots WHERE application_id = ?"
                " ORDER BY seq", (application_id,),
            ).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]


__all__ = ["AuditLedger", "AuditEvent", "chain_hash", "GENESIS", "EVENT_TYPES", "DDL"]
