"""Decision reason/history coverage — the key requirement, end to end:
every decision a loan ever receives is sealed with its reasons (codes +
verbatim ECOA texts), underwriter notes, override record, and versions;
suspend -> re-run -> approve produces TWO sealed decisions, both
replayable; the ledger tells the full human story."""

from __future__ import annotations

import asyncio
import json
import pathlib

from app.audit.snapshot import replay
from app.audit.verify import verify_chain
from app.agent.runner import finalize, run_to_gate
from synthetic.generate import BASE_DATE

from tests.test_pipeline import make_services, load_golden

REPO = pathlib.Path(__file__).resolve().parents[2]
PACKS_ROOT = REPO / "policy" / "packs"
APP = "APPHISTORY000000000000000"


def run_gate(services, package):
    return asyncio.run(run_to_gate(
        services, application_id=APP, package=package, as_of=BASE_DATE))


class TestDecisionHistory:
    def test_suspend_then_rerun_then_approve_yields_two_sealed_decisions(
            self, tmp_path):
        services = make_services(tmp_path)
        package = load_golden("clean-approve")

        # Decision 1: suspend with notes (override of suggested approve)
        run1 = run_gate(services, package)
        outcome1 = finalize(services, run1, {
            "action": "suspend", "underwriter_id": "uw-1",
            "justification": "Awaiting employer callback for verbal VOE.",
            "notes": "Borrower notified; expect resolution within 3 days."})
        assert outcome1.action == "suspend"

        # Re-run after suspension (specs/04 §2: suspended is re-runnable)
        run2 = run_gate(services, package)
        outcome2 = finalize(services, run2, {
            "action": "approve_with_conditions", "underwriter_id": "uw-1",
            "notes": "VOE received verbally 7/10; file complete."})
        assert outcome2.action == "approve_with_conditions"

        # BOTH decisions sealed, ordered, distinct
        history = services.ledger.snapshots_for(APP)
        assert len(history) == 2
        first = json.loads(history[0][1])
        second = json.loads(history[1][1])
        assert first["decision"]["action"] == "suspend"
        assert second["decision"]["action"] == "approve_with_conditions"
        assert history[0][2] != history[1][2]  # different snapshot hashes

        # notes + override preserved forever
        assert first["decision"]["notes"].startswith("Borrower notified")
        assert first["decision"]["override"]["justification"].startswith(
            "Awaiting employer")
        assert second["decision"]["notes"].startswith("VOE received")
        assert second["decision"]["override"] is None

        # latest = the approval; chain intact; BOTH replay identically
        latest = services.ledger.get_snapshot(APP)
        assert latest[1] == history[1][2]
        assert verify_chain(tmp_path / "audit.db").ok
        for _, snapshot_json, _, _ in history:
            result = replay(json.loads(snapshot_json), packs_root=PACKS_ROOT)
            assert result.identical, result.diffs

    def test_decline_reasons_detail_frozen_in_snapshot(self, tmp_path):
        services = make_services(tmp_path)
        run = run_gate(services, load_golden("decline-credit"))
        finalize(services, run, {
            "action": "decline", "underwriter_id": "uw-1",
            "second_reviewer_id": "uw-2",
            "reason_codes": ["RC-CREDIT-SCORE", "RC-CREDIT-DISPUTE"],
            "notes": "Score and open dispute both independently disqualifying."})
        snapshot = json.loads(services.ledger.get_snapshot(APP)[0])
        detail = snapshot["decision"]["reasons_detail"]
        assert [d["reason_code"] for d in detail] == [
            "RC-CREDIT-SCORE", "RC-CREDIT-DISPUTE"]
        # exact ECOA texts frozen at seal time (HR-10) with HMDA codes
        assert detail[0]["ecoa_text"] == \
            services.packs.reason_codes["RC-CREDIT-SCORE"]["ecoa_text"]
        assert detail[0]["hmda_denial_code"] == 3
        assert snapshot["decision"]["notes"].startswith("Score and open")

    def test_ledger_tells_full_human_story(self, tmp_path):
        services = make_services(tmp_path)
        run = run_gate(services, load_golden("clean-approve"))
        finalize(services, run, {
            "action": "suspend", "underwriter_id": "uw-9",
            "justification": "Insurance binder outstanding on the file.",
            "notes": "Follow up Monday."})
        events = services.ledger.events(APP)
        human = [json.loads(e.payload_json) for e in events
                 if e.event_type == "human_action"]
        override = [json.loads(e.payload_json) for e in events
                    if e.event_type == "override"]
        assert human[0]["notes"] == "Follow up Monday."
        assert human[0]["underwriter_id"] == "uw-9"
        assert override[0]["suggested_action"] == "approve_with_conditions"
        assert override[0]["actual_action"] == "suspend"
        # actor identity on the events themselves (GLBA accountability)
        actors = {e.actor for e in events if e.event_type in
                  ("human_action", "override")}
        assert actors == {"underwriter:uw-9"}
