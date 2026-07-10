"""T-REP-1 (fixture-first per specs/16 §3 Phase 3) — a sealed snapshot
replays identically through the real packs; corrupting an input yields a
structured diff, and a swapped pack is detected via the manifest pin."""

from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest

from app.audit.canonical import canonical_json, sha256_hex
from app.audit.snapshot import build_snapshot, replay
from app.policy_engine import JsonRulesEngine, load_packs

REPO = pathlib.Path(__file__).resolve().parents[2]
PACKS_ROOT = REPO / "policy" / "packs"

from tests.test_policy_engine import clean_context  # reuse the golden context


@pytest.fixture(scope="module")
def sealed():
    packs = load_packs(PACKS_ROOT / "conforming-2026.1.0",
                       PACKS_ROOT / "state-overlays-2026.1.0")
    ctx = clean_context("TX")
    ctx["loan.purpose"] = ("cash_out_refi", "Lp")
    ctx["loan.is_cash_out"] = (True, "Lc")
    ctx["ltv.ltv"] = (Decimal("79.50"), "Ll")
    ctx["state.prior_a6_days"] = (320, "Ls")   # STX-005 fails -> ineligible
    rules = JsonRulesEngine().evaluate(packs, ctx)
    assert rules.overall == "ineligible"

    snapshot, digest = build_snapshot(
        application_id="APPREPLAYFIXTURE000000000",
        versions={
            "policy_pack": "conforming-2026.1.0",
            "policy_pack_manifest_sha256": packs.base_manifest_sha256,
            "state_overlay_pack": "state-overlays-2026.1.0",
            "state_overlay_manifest_sha256": packs.overlay_manifest_sha256,
            "prompts": {}, "model_ids": [], "aus_simulator": "du-sim.v1",
            "code_git_sha": "fixture", "llm_provider": "mock",
        },
        inputs={"package_sha256": "00" * 32, "extracted_fields": [],
                "adapter_results": []},
        computed={"note": "fixture — full computed block lands in P5"},
        rules=rules,
        aus={"recommendation": "Approve/Ineligible", "breakdown": {}, "messages": []},
        conditions=[],
        decision={"action": "decline", "suggested_action": "decline",
                  "decided_by": "uw-1", "second_reviewer": "uw-2",
                  "reason_codes": ["RC-STATE-TX-50A6-SEASONING"],
                  "hmda_action_taken": 3},
        sealed_at="2026-07-10T00:00:00.000+00:00",
    )
    return snapshot, digest


class TestReplay:
    def test_identical(self, sealed):
        snapshot, _ = sealed
        result = replay(snapshot, packs_root=PACKS_ROOT)
        assert result.identical, result.diffs

    def test_snapshot_hash_stable(self, sealed):
        snapshot, digest = sealed
        assert sha256_hex(canonical_json(snapshot)) == digest

    def test_corrupted_input_yields_structured_diff(self, sealed):
        import copy
        snapshot, _ = sealed
        mutated = copy.deepcopy(snapshot)
        for evaluation in mutated["rules"]["evaluations"]:
            for rule_input in evaluation["inputs"]:
                if rule_input["path"] == "state.prior_a6_days":
                    rule_input["value"] = "400"  # would now pass seasoning
        result = replay(mutated, packs_root=PACKS_ROOT)
        assert not result.identical
        assert any("STX-005" in d for d in result.diffs)

    def test_swapped_pack_detected_by_manifest_pin(self, sealed):
        import copy
        snapshot, _ = sealed
        mutated = copy.deepcopy(snapshot)
        mutated["versions"]["policy_pack_manifest_sha256"] = "00" * 32
        result = replay(mutated, packs_root=PACKS_ROOT)
        assert not result.identical
        assert any("manifest drift" in d for d in result.diffs)
