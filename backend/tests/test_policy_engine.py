"""T-POL-1..7 + T-SOV-1/2/3/5 subset — policy engine over the real shipped
packs (policy/packs/*). Golden expectations follow specs/07 §7 and 17 §7.2."""

from __future__ import annotations

import json
import pathlib
import shutil
from decimal import Decimal

import pytest

from app.domain.calculations import dti as dti_mod
from app.domain.lineage import Lineage
from app.domain.numeric import D, HUNDRED, money, ratio_pct
from app.policy_engine import (
    JsonRulesEngine,
    PolicyPackIntegrityError,
    PolicyPackValidationError,
    load_packs,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
BASE = REPO / "policy" / "packs" / "conforming-2026.1.0"
OVERLAY = REPO / "policy" / "packs" / "state-overlays-2026.1.0"


@pytest.fixture(scope="module")
def packs():
    return load_packs(BASE, OVERLAY)


@pytest.fixture(scope="module")
def engine():
    return JsonRulesEngine()


def C(value, ref="Lx"):
    return (value, ref)


def clean_context(state: str = "OH") -> dict:
    """A fully base-eligible 1-unit primary purchase (archetype #1 shape)."""
    return {
        "loan.amount": C(Decimal("600000.00")),
        "loan.purpose": C("purchase"),
        "loan.occupancy": C("primary"),
        "loan.units": C(1),
        "loan.county_high_cost": C(False),
        "loan.is_cash_out": C(False),
        "loan.apr": C(Decimal("6.400")),
        "loan.points_and_fees_pct": C(Decimal("2.100")),
        "loan.lender_fees_pct": C(Decimal("1.000")),
        "ltv.ltv": C(Decimal("75.00")),
        "ltv.cltv": C(Decimal("75.00")),
        "dti.front_ratio": C(Decimal("25.000")),
        "dti.back_ratio": C(Decimal("32.000")),
        "income.qualifying_monthly": C(Decimal("11195.83")),
        "income.residual_monthly": C(Decimal("5000.00")),
        "income.variable_included_under_12mo": C(0),
        "income.discrepancies_exceeded": C(0),
        "credit.representative_score": C(780),
        "credit.open_disputes": C(0),
        "credit.late_mortgage_12mo": C(0),
        "credit.report_age_days": C(12),
        "assets.reserves_months": C(Decimal("8.0")),
        "assets.unsourced_large_deposits": C(0),
        "assets.unseasoned_funds": C(0),
        "assets.gift_funds_undocumented": C(0),
        "compensating.count": C(3),
        "property.type": C("sfr_detached"),
        "property.state": C(state),
        "property.homestead": C(True),
        "appraisal.age_days": C(20),
        "state.flags.community_property": C(False),
        "state.flags.wet_funding": C(True),
        "state.flags.attorney_closing": C(False),
        "state.flags.disparate_impact_monitoring": C(False),
        "state.apr_spread_treasury": C(Decimal("2.150")),
        "state.rate_spread_pmms": C(Decimal("0.500")),
        "apor.spread": C(Decimal("0.300")),
        "state.subordinate_lien_count": C(0),
        "state.tx_notice_on_file": C(True),
        "borrowers.non_borrowing_spouse_present": C(False),
    }


def by_id(result, rule_id):
    return next(e for e in result.evaluations if e.rule_id == rule_id)


# ------------------------------------------------------------- loading gates
class TestLoading:
    def test_loads_shipped_packs(self, packs):
        assert packs.base_version == "conforming-2026.1.0"
        assert packs.overlay_version == "state-overlays-2026.1.0"
        assert "RC-DTI-EXCESSIVE" in packs.reason_codes
        assert "RC-STATE-TX-50A6-LTV" in packs.reason_codes
        assert "TX" in packs.overlay_by_state

    def test_manifest_tamper_rejected(self, tmp_path):  # T-POL-2
        tampered = tmp_path / "conforming-2026.1.0"
        shutil.copytree(BASE, tampered)
        f = tampered / "dti.rules.json"
        f.write_text(f.read_text(encoding="utf-8").replace("45.000", "46.000"),
                     encoding="utf-8")
        with pytest.raises(PolicyPackIntegrityError):
            load_packs(tampered, OVERLAY)

    def test_unbound_reason_code_rejected(self, tmp_path):  # T-POL-3
        broken = tmp_path / "base"
        shutil.copytree(BASE, broken)
        f = broken / "dti.rules.json"
        content = f.read_text(encoding="utf-8").replace(
            "RC-DTI-EXCESSIVE", "RC-NOT-A-CODE")
        f.write_text(content, encoding="utf-8")
        # regenerate manifest so we hit VALIDATION, not integrity
        import hashlib
        pack = json.loads((broken / "pack.json").read_text(encoding="utf-8"))
        pack["files"]["dti.rules.json"] = hashlib.sha256(f.read_bytes()).hexdigest()
        (broken / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
        with pytest.raises(PolicyPackValidationError, match="RC-NOT-A-CODE"):
            load_packs(broken, OVERLAY)

    def test_uncited_overlay_rule_rejected(self, tmp_path):  # T-SOV-2
        broken = tmp_path / "overlay"
        shutil.copytree(OVERLAY, broken)
        f = broken / "tx.rules.json"
        parsed = json.loads(f.read_text(encoding="utf-8"))
        del parsed["rules"][0]["citation"]
        f.write_text(json.dumps(parsed), encoding="utf-8")
        import hashlib
        pack = json.loads((broken / "pack.json").read_text(encoding="utf-8"))
        pack["files"]["tx.rules.json"] = hashlib.sha256(f.read_bytes()).hexdigest()
        (broken / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
        with pytest.raises(PolicyPackValidationError, match="citation"):
            load_packs(BASE, broken)


# ------------------------------------------------------------- golden outcomes
class TestGoldenOutcomes:
    def test_clean_loan_eligible(self, packs, engine):  # T-POL-4 archetype 1
        result = engine.evaluate(packs, clean_context())
        assert result.overall == "eligible"
        eligibility_failures = [
            e for e in result.evaluations
            if e.severity == "eligibility" and e.outcome in ("fail", "refer")
        ]
        assert eligibility_failures == []

    def test_dti_compensating_branch(self, packs, engine):  # archetype 3
        ctx = clean_context()
        ctx["dti.back_ratio"] = C(Decimal("48.500"))
        result = engine.evaluate(packs, ctx)
        assert by_id(result, "DTI-001").outcome == "pass"
        ctx["compensating.count"] = C(1)
        result2 = engine.evaluate(packs, ctx)
        assert by_id(result2, "DTI-001").outcome == "fail"
        assert by_id(result2, "DTI-001").reason_code == "RC-DTI-EXCESSIVE"
        assert result2.overall == "ineligible"

    def test_dti_boundary_exact(self, packs, engine):  # 14 §5 boundary sweep
        for back, comp, expected in [
            ("44.999", 0, "pass"), ("45.000", 0, "pass"), ("45.001", 0, "fail"),
            ("49.999", 2, "pass"), ("50.000", 2, "pass"), ("50.001", 2, "fail"),
        ]:
            ctx = clean_context()
            ctx["dti.back_ratio"] = C(Decimal(back))
            ctx["compensating.count"] = C(comp)
            outcome = by_id(engine.evaluate(packs, ctx), "DTI-001").outcome
            assert outcome == expected, f"back={back} comp={comp}"

    def test_decline_credit(self, packs, engine):  # archetype 9
        ctx = clean_context()
        ctx["credit.representative_score"] = C(585)
        ctx["credit.open_disputes"] = C(1)
        result = engine.evaluate(packs, ctx)
        assert by_id(result, "CR-001").outcome == "fail"
        assert by_id(result, "CR-002").outcome == "fail"
        assert result.overall == "ineligible"
        assert set(result.eligible_reason_codes) >= {
            "RC-CREDIT-SCORE", "RC-CREDIT-DISPUTE"}

    def test_score_boundary(self, packs, engine):
        for score, expected in [(619, "fail"), (620, "pass"), (621, "pass")]:
            ctx = clean_context()
            ctx["credit.representative_score"] = C(score)
            assert by_id(engine.evaluate(packs, ctx), "CR-001").outcome == expected

    def test_jumbo_limit_with_table(self, packs, engine):  # archetype 12
        ctx = clean_context()
        ctx["loan.amount"] = C(Decimal("850000.00"))
        result = engine.evaluate(packs, ctx)
        limit = by_id(result, "LIMIT-001")
        assert limit.outcome == "fail" and limit.reason_code == "RC-LIMIT-EXCEEDED"
        hint = next(h for h in result.counteroffer_hints if h.rule_id == "LIMIT-001")
        assert hint.max_value == "832750.00"  # exact bound (specs/07 §4.3)

    def test_high_cost_county_limit(self, packs, engine):
        ctx = clean_context()
        ctx["loan.amount"] = C(Decimal("850000.00"))
        ctx["loan.county_high_cost"] = C(True)
        assert by_id(engine.evaluate(packs, ctx), "LIMIT-001").outcome == "pass"

    def test_ltv_matrix_second_home(self, packs, engine):  # archetype 11
        ctx = clean_context()
        ctx["loan.occupancy"] = C("second_home")
        ctx["ltv.ltv"] = C(Decimal("93.00"))
        ctx["assets.reserves_months"] = C(Decimal("3.0"))
        result = engine.evaluate(packs, ctx)
        assert by_id(result, "LTV-001").outcome == "fail"
        assert by_id(result, "LTV-001").reason_code == "RC-LTV-EXCESSIVE"

    def test_documentation_refer_does_not_block(self, packs, engine):  # 07 §4.4
        ctx = clean_context()
        ctx["assets.unsourced_large_deposits"] = C(1)  # AST-002 documentation refer
        result = engine.evaluate(packs, ctx)
        assert by_id(result, "AST-002").outcome == "refer"
        assert result.overall == "eligible"  # archetype #2 semantics

    def test_missing_input_refers(self, packs, engine):  # T-POL-7
        ctx = clean_context()
        del ctx["dti.back_ratio"]
        result = engine.evaluate(packs, ctx)
        dti = by_id(result, "DTI-001")
        assert dti.outcome == "refer" and dti.reason_code == "RC-DATA-MISSING"
        assert any(i.value == "<missing>" for i in dti.inputs)

    def test_inputs_carry_values(self, packs, engine):  # T-POL-1
        result = engine.evaluate(packs, clean_context())
        dti = by_id(result, "DTI-001")
        consumed = {i.path: i.value for i in dti.inputs}
        assert consumed["dti.back_ratio"] == "32.000"

    def test_deterministic_repeat(self, packs, engine):  # T-POL-1 uniform
        ctx = clean_context()
        assert engine.evaluate(packs, ctx) == engine.evaluate(packs, ctx)


# ------------------------------------------------------------- state overlays
class TestStateOverlays:
    def test_state_selection_tx_vs_oh(self, packs, engine):  # T-SOV-5
        tx = clean_context("TX")
        oh = clean_context("OH")
        r_tx, r_oh = engine.evaluate(packs, tx), engine.evaluate(packs, oh)
        tx_ids = {e.rule_id for e in r_tx.evaluations}
        oh_ids = {e.rule_id for e in r_oh.evaluations}
        assert "STX-001" in tx_ids and "STX-001" not in oh_ids
        # purchase in TX: a6 guard false -> not_applicable (T-SOV-1)
        assert by_id(r_tx, "STX-001").outcome == "not_applicable"

    def test_tx_a6_seasoning_overlay_only_ineligibility(self, packs, engine):
        """T-SOV-3 most-restrictive-wins — base-eligible loan, overlay declines."""
        ctx = clean_context("TX")
        ctx["loan.purpose"] = C("cash_out_refi")
        ctx["loan.is_cash_out"] = C(True)
        ctx["ltv.ltv"] = C(Decimal("79.50"))
        ctx["ltv.cltv"] = C(Decimal("79.50"))
        ctx["state.prior_a6_days"] = C(320)
        result = engine.evaluate(packs, ctx)
        seasoning = by_id(result, "STX-005")
        assert seasoning.outcome == "fail"
        assert seasoning.reason_code == "RC-STATE-TX-50A6-SEASONING"
        assert result.overall == "ineligible"
        assert seasoning.citation and "50(a)(6)" in seasoning.citation

    def test_tx_a6_boundaries(self, packs, engine):  # T-SOV-5 boundary sweep
        def a6_ctx():
            ctx = clean_context("TX")
            ctx["loan.purpose"] = C("cash_out_refi")
            ctx["loan.is_cash_out"] = C(True)
            return ctx

        for ltv, expected in [("79.99", "pass"), ("80.00", "pass"), ("80.01", "fail")]:
            ctx = a6_ctx()
            ctx["ltv.ltv"] = C(Decimal(ltv))
            assert by_id(engine.evaluate(packs, ctx), "STX-001").outcome == expected
        for fees, expected in [("1.999", "pass"), ("2.000", "pass"), ("2.001", "refer")]:
            ctx = a6_ctx()
            ctx["loan.lender_fees_pct"] = C(Decimal(fees))
            assert by_id(engine.evaluate(packs, ctx), "STX-004").outcome == expected
        for days, expected in [(364, "fail"), (365, "pass"), (366, "pass")]:
            ctx = a6_ctx()
            ctx["state.prior_a6_days"] = C(days)
            assert by_id(engine.evaluate(packs, ctx), "STX-005").outcome == expected

    def test_tx_a6_docset_artifact_always(self, packs, engine):  # 17 §7.1
        ctx = clean_context("TX")
        ctx["loan.purpose"] = C("cash_out_refi")
        ctx["loan.is_cash_out"] = C(True)
        result = engine.evaluate(packs, ctx)
        assert any(a.id == "TX-A6-DOCSET" for a in result.artifacts)
        # and NOT for a TX purchase (guard false)
        purchase = engine.evaluate(packs, clean_context("TX"))
        assert not any(a.id == "TX-A6-DOCSET" for a in purchase.artifacts)

    def test_ny_high_cost_decline(self, packs, engine):  # archetype 15
        ctx = clean_context("NY")
        ctx["state.apr_spread_treasury"] = C(Decimal("8.500"))
        result = engine.evaluate(packs, ctx)
        sny = by_id(result, "SNY-001")
        assert sny.outcome == "fail" and sny.reason_code == "RC-STATE-HIGHCOST"
        assert result.overall == "ineligible"
        # CEMA rule not applicable on a purchase
        assert by_id(result, "SNY-003").outcome == "not_applicable"

    def test_hoepa_baseline_everywhere(self, packs, engine):
        ctx = clean_context("OH")
        ctx["apor.spread"] = C(Decimal("6.600"))
        result = engine.evaluate(packs, ctx)
        assert by_id(result, "SHC-000").outcome == "fail"
        assert result.overall == "ineligible"

    def test_community_property_artifact(self, packs, engine):
        ctx = clean_context("CA")
        ctx["state.flags.community_property"] = C(True)
        ctx["borrowers.non_borrowing_spouse_present"] = C(True)
        result = engine.evaluate(packs, ctx)
        assert any(a.id == "CP-NBS-SIGN" for a in result.artifacts)


# ------------------------------------------------------------- counteroffer
class TestCounteroffer:
    def test_dti_binary_search_429000(self, packs, engine):  # T-POL-5
        """The specs/06 §3 worked vector: max amount at back<=45.000 is 429,000."""
        lin = Lineage(application_id="APPCOUNTEROFFER0000000000")

        taxes, hazard = D("800.00"), D("150.00")
        income, liabilities = D("11195.83"), D("1480.00")
        rate, term = "6.125", 360

        def recompute(ctx, amount):
            pi = dti_mod.principal_interest(
                lin,
                loan_amount=lin.add("package_stated", "co.amount", str(money(amount))),
                note_rate_pct=lin.add("package_stated", "co.rate", rate),
                term_months=term,
            )
            back = ratio_pct((D(pi.value) + taxes + hazard + liabilities) / income * HUNDRED)
            new_ctx = dict(ctx)
            new_ctx["loan.amount"] = (money(amount), None)
            new_ctx["dti.back_ratio"] = (back, None)
            return new_ctx

        ctx = clean_context()
        ctx["loan.amount"] = C(Decimal("640000.00"))
        ctx["dti.back_ratio"] = C(Decimal("56.438"))
        ctx["compensating.count"] = C(0)
        result = engine.evaluate(packs, ctx, recompute=recompute)
        hint = next(h for h in result.counteroffer_hints if h.rule_id == "DTI-001")
        assert hint.max_value == "429000.00"
        assert hint.achieved_ratio == "44.987"
