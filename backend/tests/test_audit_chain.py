"""T-AUD-1..3 — ledger completeness, hash-chain tamper evidence at the
exact seq, and storage-level append-only enforcement."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from app.audit.canonical import canonical_json
from app.audit.ledger import AuditLedger
from app.audit.verify import verify_chain


@pytest.fixture()
def ledger(tmp_path):
    return AuditLedger(tmp_path / "audit.db"), tmp_path / "audit.db"


def fill(ledger: AuditLedger, n: int = 100, app: str = "APP1") -> None:
    for i in range(n):
        ledger.append(
            application_id=app, event_type="state_change", actor="system",
            payload={"from": f"s{i}", "to": f"s{i + 1}"},
        )


class TestChain:
    def test_append_and_verify_ok(self, ledger):  # T-AUD-2 happy path
        led, path = ledger
        fill(led, 100)
        result = verify_chain(path)
        assert result.ok and result.events == 100

    def test_interleaved_applications_one_chain(self, ledger):
        led, path = ledger
        for i in range(30):
            led.append(application_id=f"APP{i % 3}", event_type="red_flag",
                       actor="agent", payload={"flag_code": f"RF-{i}"})
        assert verify_chain(path).ok
        assert len(led.events("APP0")) == 10

    def test_byte_flip_detected_at_exact_seq(self, ledger, tmp_path):  # T-AUD-2
        led, path = ledger
        fill(led, 50)
        copy = tmp_path / "tampered.db"
        shutil.copy(path, copy)
        conn = sqlite3.connect(copy)
        conn.execute("DROP TRIGGER audit_no_update")  # attacker with raw access
        conn.execute(
            "UPDATE audit_events SET payload_json = ? WHERE seq = 23",
            (canonical_json({"from": "s22", "to": "EVIL"}),),
        )
        conn.commit(); conn.close()
        result = verify_chain(copy)
        assert not result.ok
        assert result.first_broken_seq == 23
        assert result.expected_hash != result.stored_hash

    def test_deleted_row_breaks_chain(self, ledger, tmp_path):
        led, path = ledger
        fill(led, 20)
        copy = tmp_path / "gap.db"
        shutil.copy(path, copy)
        conn = sqlite3.connect(copy)
        conn.execute("DROP TRIGGER audit_no_delete")
        conn.execute("DELETE FROM audit_events WHERE seq = 10")
        conn.commit(); conn.close()
        result = verify_chain(copy)
        assert not result.ok and result.first_broken_seq == 11

    def test_unknown_event_type_rejected(self, ledger):  # specs/11 §3 catalogue
        led, _ = ledger
        with pytest.raises(ValueError):
            led.append(application_id="A", event_type="made_up",
                       actor="system", payload={})


class TestAppendOnlyStorage:  # T-AUD-3
    def test_update_rejected_by_trigger(self, ledger):
        led, path = ledger
        fill(led, 5)
        conn = sqlite3.connect(path)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE audit_events SET actor = 'evil' WHERE seq = 1")
        conn.close()

    def test_delete_rejected_by_trigger(self, ledger):
        led, path = ledger
        fill(led, 5)
        conn = sqlite3.connect(path)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM audit_events WHERE seq = 1")
        conn.close()

    def test_no_mutation_methods_exist(self, ledger):
        led, _ = ledger
        mutators = [m for m in dir(led)
                    if any(v in m.lower() for v in ("update", "delete", "remove"))]
        assert mutators == []

    def test_snapshot_immutable(self, ledger):
        led, path = ledger
        led.store_snapshot("APP1", '{"snapshot_version":"1"}', "ab" * 32, "t")
        conn = sqlite3.connect(path)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE decision_snapshots SET sha256 = 'x'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM decision_snapshots")
        conn.close()


class TestCanonicalJson:  # FR-AUD-7
    def test_sorted_keys_compact(self):
        from decimal import Decimal
        out = canonical_json({"b": Decimal("48.500"), "a": [1, {"z": "TX", "y": None}]})
        assert out == '{"a":[1,{"y":null,"z":"TX"}],"b":"48.500"}'

    def test_float_rejected(self):
        with pytest.raises(TypeError):
            canonical_json({"x": 1.5})
