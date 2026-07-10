"""Chain verification (specs/11 §5, FR-AUD-4): recompute every hash from
stored fields; report the exact first broken sequence number on tamper."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.audit.ledger import GENESIS, chain_hash


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    events: int
    first_broken_seq: int | None = None
    expected_hash: str | None = None
    stored_hash: str | None = None


def verify_chain(db_path: Path | str, from_seq: int = 1) -> VerifyResult:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT seq, event_id, event_type, payload_json, prev_hash, hash,"
            " created_at FROM audit_events WHERE seq >= ? ORDER BY seq",
            (from_seq,),
        ).fetchall()
    finally:
        conn.close()

    prev = GENESIS
    for seq, event_id, event_type, payload_json, prev_hash, stored, created_at in rows:
        if prev_hash != prev:
            return VerifyResult(False, len(rows), seq, prev, prev_hash)
        expected = chain_hash(prev_hash, event_id, event_type, payload_json, created_at)
        if expected != stored:
            return VerifyResult(False, len(rows), seq, expected, stored)
        prev = stored
    return VerifyResult(True, len(rows))


__all__ = ["verify_chain", "VerifyResult"]
