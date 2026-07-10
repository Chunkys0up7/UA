"""P5 pipeline tests: T-DEC-2/3/4 (gate), T-AAN-1 (exact ECOA strings),
T-SOV-6 (ADMT artifacts), T-HMD-1, T-VER-3 (OFAC halt), T-REP-1 over a
REAL sealed run, and T-DAT-3 (500-package corpus regression)."""

from __future__ import annotations

import asyncio
import json
import pathlib
from decimal import Decimal

import pytest

from app.agent.runner import Services, finalize, run_to_gate
from app.audit.canonical import canonical_json
from app.audit.ledger import AuditLedger
from app.audit.snapshot import replay
from app.audit.verify import verify_chain
from app.aus.du_simulator import load_config
from app.llm.ua_base import PromptRegistry
from app.llm.ua_mock import MockUALLMClient
from app.policy_engine import JsonRulesEngine, load_packs
from synthetic.archetypes import GOLDEN_ARCHETYPES, by_name
from synthetic.generate import BASE_DATE, build_package

REPO = pathlib.Path(__file__).resolve().parents[2]
PACKS_ROOT = REPO / "policy" / "packs"


def make_services(tmp_path) -> Services:
    return Services(
        packs=load_packs(PACKS_ROOT / "conforming-2026.1.0",
                         PACKS_ROOT / "state-overlays-2026.1.0"),
        registry=PromptRegistry(REPO / "policy" / "prompts"),
        llm=MockUALLMClient(),
        ledger=AuditLedger(tmp_path / "audit.db"),
        aus_config=load_config(REPO / "policy" / "aus" / "du-sim.v1.json"),
        engine=JsonRulesEngine(),
        four_eyes_threshold=Decimal("1000000"),
        llm_provider="mock",
        code_git_sha="test",
    )


def load_golden(name: str) -> dict:
    return json.loads(
        (REPO / "data" / "loans" / f"{name}.json").read_text(encoding="utf-8"))


def gate(services: Services, name: str, application_id: str = "APPPIPE000000000000000000"):
    return asyncio.run(run_to_gate(
        services, application_id=application_id,
        package=load_golden(name), as_of=BASE_DATE))


APPROVE_RESUME = {"action": "approve_with_conditions", "underwriter_id": "uw-1"}


# ---------------------------------------------------------------- gate matrix
class TestGateValidation:
    def test_decline_without_reason_codes_rejected(self, tmp_path):  # T-DEC-2
        services = make_services(tmp_path)
        run = gate(services, "decline-credit")
        outcome = finalize(services, run, {
            "action": "decline", "underwriter_id": "uw-1",
            "second_reviewer_id": "uw-2"})
        assert outcome.action == "invalid"
        assert any("1-4 reason codes" in e for e in outcome.validation_errors)

    def test_decline_with_unbound_code_rejected(self, tmp_path):
        services = make_services(tmp_path)
        run = gate(services, "decline-credit")
        outcome = finalize(services, run, {
            "action": "decline", "underwriter_id": "uw-1",
            "second_reviewer_id": "uw-2",
            "reason_codes": ["RC-LTV-EXCESSIVE"]})  # LTV didn't fail here
        assert outcome.action == "invalid"

    def test_decline_same_second_reviewer_rejected(self, tmp_path):  # T-DEC-4
        services = make_services(tmp_path)
        run = gate(services, "decline-credit")
        outcome = finalize(services, run, {
            "action": "decline", "underwriter_id": "uw-1",
            "second_reviewer_id": "uw-1",
            "reason_codes": ["RC-CREDIT-SCORE"]})
        assert outcome.action == "invalid"
        assert any("differ" in e for e in outcome.validation_errors)

    def test_override_requires_justification(self, tmp_path):  # T-DEC-3
        services = make_services(tmp_path)
        run = gate(services, "clean-approve")
        assert run.packet["suggested_action"] == "approve_with_conditions"
        outcome = finalize(services, run, {
            "action": "suspend", "underwriter_id": "uw-1"})  # override, no why
        assert outcome.action == "invalid"
        assert any("justification" in e for e in outcome.validation_errors)

    def test_override_recorded_both_directions(self, tmp_path):
        services = make_services(tmp_path)
        run = gate(services, "clean-approve")
        outcome = finalize(services, run, {
            "action": "suspend", "underwriter_id": "uw-1",
            "justification": "Verbal VOE pending employer callback this week."})
        assert outcome.action == "suspend" and outcome.override
        events = services.ledger.events(run.application_id)
        assert any(e.event_type == "override" for e in events)


# ---------------------------------------------------------------- adverse action
class TestAdverseAction:
    def test_notice_exact_ecoa_strings(self, tmp_path):  # T-AAN-1 / HR-10
        services = make_services(tmp_path)
        run = gate(services, "decline-credit")
        outcome = finalize(services, run, {
            "action": "decline", "underwriter_id": "uw-1",
            "second_reviewer_id": "uw-2",
            "reason_codes": ["RC-CREDIT-SCORE", "RC-CREDIT-DISPUTE"]})
        assert outcome.action == "decline"
        notice = outcome.adverse_action
        bindings = services.packs.reason_codes
        texts = [r["ecoa_text"] for r in notice["principal_reasons"]]
        assert texts == [bindings["RC-CREDIT-SCORE"]["ecoa_text"],
                         bindings["RC-CREDIT-DISPUTE"]["ecoa_text"]]
        for text in texts:
            assert text in notice["body_text"]  # verbatim, no rewording
        fcra = notice["fcra_block"]
        assert fcra["range_low"] == 300 and fcra["range_high"] == 850
        assert 1 <= len(fcra["key_factors"]) <= 4
        assert fcra["bureaus"] == ["equifax", "experian", "transunion"]
        assert notice["admt_block"] is None  # OH: no ADMT duty

    def test_co_admt_artifact_on_decline(self, tmp_path):  # T-SOV-6
        services = make_services(tmp_path)
        package = load_golden("decline-credit")
        package["property"]["address"]["state"] = "CO"
        run = asyncio.run(run_to_gate(
            services, application_id="APPCOADMT0000000000000000",
            package=package, as_of=BASE_DATE))
        outcome = finalize(services, run, {
            "action": "decline", "underwriter_id": "uw-1",
            "second_reviewer_id": "uw-2", "reason_codes": ["RC-CREDIT-SCORE"]})
        admt = outcome.adverse_action["admt_block"]
        assert admt and "SB 26-189" in admt["citation"]
        assert "plain_language_explanation_30d" in admt["duties"]
        assert "Automated decision-making disclosure" in outcome.adverse_action["body_text"]

    def test_hmda_mapping(self, tmp_path):  # T-HMD-1
        services = make_services(tmp_path)
        run = gate(services, "clean-approve")
        outcome = finalize(services, run, dict(APPROVE_RESUME))
        assert outcome.hmda_action_taken == 1
        run2 = gate(services, "decline-credit", "APPHMDA200000000000000000")
        outcome2 = finalize(services, run2, {
            "action": "decline", "underwriter_id": "uw-1",
            "second_reviewer_id": "uw-2", "reason_codes": ["RC-CREDIT-SCORE"]})
        assert outcome2.hmda_action_taken == 3


# ---------------------------------------------------------------- halts & seal
class TestRunLifecycle:
    def test_ofac_halt(self, tmp_path):  # T-VER-3
        services = make_services(tmp_path)
        package = load_golden("clean-approve")
        package["borrowers"][0]["full_name"] = "SANCTIONED TEST PARTY"
        run = asyncio.run(run_to_gate(
            services, application_id="APPOFAC000000000000000000",
            package=package, as_of=BASE_DATE))
        assert run.halted == "ofac" and run.packet == {}
        events = services.ledger.events("APPOFAC000000000000000000")
        assert events[-1].payload_json.find("suspended") != -1

    def test_sealed_run_replays_identically(self, tmp_path):  # T-REP-1 (real)
        services = make_services(tmp_path)
        run = gate(services, "tx-a6-seasoning-decline")
        assert run.packet["suggested_action"] == "decline"
        outcome = finalize(services, run, {
            "action": "decline", "underwriter_id": "uw-1",
            "second_reviewer_id": "uw-2",
            "reason_codes": ["RC-STATE-TX-50A6-SEASONING"]})
        assert outcome.snapshot_sha256
        stored = services.ledger.get_snapshot(run.application_id)
        assert stored and stored[1] == outcome.snapshot_sha256
        result = replay(json.loads(stored[0]), packs_root=PACKS_ROOT)
        assert result.identical, result.diffs
        chain = verify_chain(tmp_path / "audit.db")
        assert chain.ok

    def test_full_event_catalogue_on_decline_path(self, tmp_path):  # T-AUD-1
        services = make_services(tmp_path)
        run = gate(services, "decline-credit")
        finalize(services, run, {
            "action": "decline", "underwriter_id": "uw-1",
            "second_reviewer_id": "uw-2", "reason_codes": ["RC-CREDIT-SCORE"]})
        types = {e.event_type for e in services.ledger.events(run.application_id)}
        assert {"state_change", "llm_call", "adapter_call", "discrepancy_found",
                "rule_eval_batch", "aus_run", "condition_created",
                "decision_packet_ready", "human_action",
                "adverse_action_generated", "hmda_action_taken",
                "seal"} <= types

    def test_state_size_budget(self, tmp_path):  # T-STA-1 (packet side)
        services = make_services(tmp_path)
        for archetype in GOLDEN_ARCHETYPES:
            run = gate(services, archetype.name,
                       f"APPSIZE{archetype.name[:8].upper():0<18}")
            if run.halted:
                continue
            summary = {  # what UnderwritingState carries (specs/09 §2)
                "application_id": run.application_id,
                "four_cs_summary": {
                    "credit": run.case.four_cs["credit"]["representative_score"],
                    "capacity": run.case.four_cs["capacity"]["back_ratio"],
                    "capital": run.case.four_cs["capital"]["reserves_months"],
                    "collateral": run.case.four_cs["collateral"]["ltv"]},
                "red_flags": [f.flag_code for f in run.case.red_flags],
                "aus": run.aus.recommendation,
                "conditions_summary": [
                    {"id": c.id, "category": c.category, "title": c.title}
                    for c in run.conditions],
                "decision_packet": run.packet,
            }
            size = len(canonical_json(summary).encode("utf-8"))
            assert size < 32_768, f"{archetype.name}: state {size}B >= 32KB"


# ---------------------------------------------------------------- corpus (T-DAT-3)
class TestCorpusRegression:
    def test_500_package_corpus(self, tmp_path):
        manifest_path = REPO / "data" / "generated" / "manifest.json"
        if not manifest_path.exists():
            pytest.skip("corpus not generated (scripts/generate-corpus)")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        services = make_services(tmp_path)
        mismatches: list[str] = []
        replay_samples: list[str] = []

        async def run_all():
            for index, entry in enumerate(manifest["packages"]):
                package = json.loads(
                    (REPO / "data" / "generated" / entry["file"])
                    .read_text(encoding="utf-8"))
                application_id = f"APPCORPUS{index:017d}"
                run = await run_to_gate(services, application_id=application_id,
                                        package=package, as_of=BASE_DATE)
                if run.halted:
                    mismatches.append(f"{entry['file']}: unexpected halt")
                    continue
                suggested = run.packet["suggested_action"]
                expected = entry["expected_family"]
                if expected == "approve" and suggested != "approve_with_conditions":
                    mismatches.append(
                        f"{entry['file']}: expected approve, got {suggested}")
                if expected == "decline" and suggested != "decline":
                    mismatches.append(
                        f"{entry['file']}: expected decline, got {suggested}")
                if expected == "suspend" and suggested != "suspend":
                    mismatches.append(
                        f"{entry['file']}: expected suspend, got {suggested}")
                # auto-decide with the suggestion (test-only auto-approver)
                resume: dict = {"action": suggested, "underwriter_id": "uw-auto",
                                "second_reviewer_id": "uw-second"}
                if suggested == "decline":
                    resume["reason_codes"] = list(
                        run.packet["eligible_reason_codes"])[:4] or ["RC-DATA-MISSING"]
                outcome = finalize(services, run, resume)
                if outcome.action == "invalid":
                    mismatches.append(
                        f"{entry['file']}: finalize invalid {outcome.validation_errors}")
                elif index % 50 == 0:
                    replay_samples.append(application_id)

        asyncio.run(run_all())
        assert not mismatches, mismatches[:10]

        chain = verify_chain(tmp_path / "audit.db")
        assert chain.ok and chain.events > 10_000

        for application_id in replay_samples:  # every 50th sealed run replays
            stored = services.ledger.get_snapshot(application_id)
            assert stored, application_id
            result = replay(json.loads(stored[0]), packs_root=PACKS_ROOT)
            assert result.identical, (application_id, result.diffs[:3])
