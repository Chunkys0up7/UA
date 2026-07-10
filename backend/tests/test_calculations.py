"""T-CAL-1..8 — golden calculation vectors from specs/06 (worked examples
are normative) plus purity/determinism checks."""

from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest

from app.domain.atr import build_atr_evaluations
from app.domain.calculations import dti as dti_mod
from app.domain.calculations import income as income_mod
from app.domain.calculations import ltv as ltv_mod
from app.domain.calculations import reserves as reserves_mod
from app.domain.calculations import score as score_mod
from app.domain.lineage import Lineage
from app.domain.numeric import D

APP = "APPTEST0000000000000000000"


def L() -> Lineage:
    return Lineage(application_id=APP)


def tv(lineage: Lineage, label: str, value: str):
    return lineage.add("package_stated", label, value)


# ---------------------------------------------------------------- T-CAL-2 income
class TestIncomeGoldens:
    def test_base_semi_monthly_9200(self):
        lin = L()
        r = income_mod.monthly_base(
            lin, gross_pay_period=tv(lin, "gross", "4600.00"),
            pay_frequency="semi_monthly",
        )
        assert r.monthly.value == "9200.00" and r.included

    def test_bonus_two_year_average_675(self):
        lin = L()
        r = income_mod.variable_income(
            lin, income_type="bonus",
            year1_total=tv(lin, "y1", "8400.00"),
            year2_total=tv(lin, "y2", "7800.00"),
            ytd_annualized=None, history_months=30,
        )
        assert r.monthly.value == "675.00" and r.calc_method == "two_year_average"

    def test_bonus_short_history_75pct_ytd(self):
        lin = L()
        r = income_mod.variable_income(
            lin, income_type="bonus", year1_total=None, year2_total=None,
            ytd_annualized=tv(lin, "ytd", "9600.00"), history_months=14,
        )
        # 9600 * 0.75 / 12 = 600.00
        assert r.monthly.value == "600.00" and r.calc_method == "75pct_ytd"

    def test_bonus_under_12mo_excluded(self):
        lin = L()
        r = income_mod.variable_income(
            lin, income_type="bonus", year1_total=None, year2_total=None,
            ytd_annualized=tv(lin, "ytd", "9600.00"), history_months=11,
        )
        assert not r.included and r.exclusion_reason == "insufficient_history"

    def test_declining_variable_uses_recent_year(self):
        lin = L()
        r = income_mod.variable_income(
            lin, income_type="commission",
            year1_total=tv(lin, "y1", "24000.00"),
            year2_total=tv(lin, "y2", "18000.00"),  # -25% > 20% threshold
            ytd_annualized=None, history_months=30,
        )
        assert r.monthly.value == "1500.00"
        assert r.calc_method == "recent_year_declining" and r.declining

    def test_self_employed_8520_83(self):
        lin = L()
        y1 = income_mod.ScheduleCYear(
            net_profit=tv(lin, "np1", "92000.00"),
            depreciation=tv(lin, "dep1", "6000.00"),
        )
        y2 = income_mod.ScheduleCYear(
            net_profit=tv(lin, "np2", "101000.00"),
            depreciation=tv(lin, "dep2", "5500.00"),
        )
        r = income_mod.self_employed_income(lin, year1=y1, year2=y2, history_months=30)
        assert r.monthly.value == "8520.83" and r.calc_method == "two_year_average"

    def test_self_employed_under_24mo_excluded(self):
        lin = L()
        y = income_mod.ScheduleCYear(net_profit=tv(lin, "np", "50000.00"))
        r = income_mod.self_employed_income(lin, year1=y, year2=y, history_months=20)
        assert not r.included and r.exclusion_reason == "se_history_under_24mo"

    def test_rental_75pct_1800(self):
        lin = L()
        r = income_mod.rental_income(
            lin, gross_monthly_rent=tv(lin, "rent", "2400.00"),
            factor=lin.constant("rental_income_factor", "0.75", "conforming-2026.1.0"),
        )
        assert r.monthly.value == "1800.00"

    def test_nontaxable_grossup(self):
        lin = L()
        r = income_mod.other_income(
            lin, income_type="social_security",
            monthly_amount=tv(lin, "ss", "2000.00"),
            history_months=24, continuance_months=None, taxable=False,
        )
        assert r.monthly.value == "2500.00" and r.calc_method == "grossed_up_125"

    def test_total_sums_only_included(self):
        lin = L()
        base = income_mod.monthly_base(
            lin, gross_pay_period=tv(lin, "g", "4600.00"), pay_frequency="semi_monthly")
        excluded = income_mod.variable_income(
            lin, income_type="bonus", year1_total=None, year2_total=None,
            ytd_annualized=tv(lin, "ytd", "9600.00"), history_months=6)
        total = income_mod.total_qualifying_income(lin, [base, excluded])
        assert total.value == "9200.00"


# ---------------------------------------------------------------- T-CAL-3 DTI
class TestDtiGoldens:
    def test_worked_example_640k(self):
        """The normative specs/06 §3 vector, exactly."""
        lin = L()
        pi = dti_mod.principal_interest(
            lin, loan_amount=tv(lin, "amt", "640000.00"),
            note_rate_pct=tv(lin, "rate", "6.125"), term_months=360,
        )
        assert pi.value == "3888.71"
        mi = dti_mod.monthly_mi(
            lin, loan_amount=tv(lin, "amt", "640000.00"),
            ltv=tv(lin, "ltv", "80.00"),
            mi_annual_rate=lin.constant("mi_annual_rate", "0.0055", "conforming-2026.1.0"),
        )
        assert mi.value == "0.00"
        p = dti_mod.pitia(
            lin, principal_interest_tv=pi,
            monthly_taxes=tv(lin, "tax", "800.00"),
            monthly_hazard=tv(lin, "haz", "150.00"),
            mi=mi, monthly_hoa=tv(lin, "hoa", "0.00"),
        )
        assert p.total.value == "4838.71"
        ratios = dti_mod.dti_ratios(
            lin, pitia_total=p.total,
            monthly_liabilities=tv(lin, "liab", "1480.00"),
            qualifying_income=tv(lin, "inc", "11195.83"),
        )
        assert ratios.front_ratio.value == "43.219"
        assert ratios.back_ratio.value == "56.438"

    def test_mi_applies_above_80(self):
        lin = L()
        mi = dti_mod.monthly_mi(
            lin, loan_amount=tv(lin, "amt", "400000.00"),
            ltv=tv(lin, "ltv", "85.00"),
            mi_annual_rate=lin.constant("mi_annual_rate", "0.0055", "conforming-2026.1.0"),
        )
        assert mi.value == "183.33"  # 400000*0.0055/12

    def test_liabilities_exclude_le_10_payments(self):
        lin = L()
        total = dti_mod.monthly_liabilities(
            lin,
            tradeline_payments=[
                (tv(lin, "auto", "480.00"), 24),
                (tv(lin, "loan", "300.00"), 8),  # excluded
                (tv(lin, "card", "120.00"), None),
            ],
            court_ordered=[tv(lin, "support", "500.00")],
        )
        assert total.value == "1100.00"

    def test_zero_income_raises(self):
        lin = L()
        with pytest.raises(ValueError):
            dti_mod.dti_ratios(
                lin, pitia_total=tv(lin, "p", "1000.00"),
                monthly_liabilities=tv(lin, "l", "0.00"),
                qualifying_income=tv(lin, "i", "0.00"),
            )


# ---------------------------------------------------------------- T-CAL-4 LTV
class TestLtvGoldens:
    def test_purchase_min_basis_80(self):
        lin = L()
        basis = ltv_mod.value_basis(
            lin, purpose="purchase",
            purchase_price=tv(lin, "price", "800000.00"),
            appraised_value=tv(lin, "appr", "805000.00"),
        )
        assert basis.value == "800000.00"
        r = ltv_mod.ltv(lin, loan_amount=tv(lin, "amt", "640000.00"), basis=basis)
        assert r.value == "80.00"

    def test_rounds_up_conservative(self):
        lin = L()
        basis = tv(lin, "basis", "300000.00")
        # 240001/300000 = 80.0003...% -> ceil 2dp -> 80.01
        r = ltv_mod.ltv(lin, loan_amount=tv(lin, "amt", "240001.00"), basis=basis)
        assert r.value == "80.01"

    def test_cltv_includes_subordinates(self):
        lin = L()
        basis = tv(lin, "basis", "800000.00")
        r = ltv_mod.cltv(
            lin, loan_amount=tv(lin, "amt", "640000.00"),
            subordinate_balances=[tv(lin, "heloc", "32000.00")],
            basis=basis,
        )
        assert r.value == "84.00"


# ---------------------------------------------------------------- T-CAL-5 reserves
class TestReservesGoldens:
    def test_worked_example_1_2_months(self):
        lin = L()
        ftc = reserves_mod.funds_to_close(
            lin, down_payment=tv(lin, "down", "160000.00"),
            cost_basis=tv(lin, "price", "800000.00"),
            closing_cost_rate=lin.constant("estimated_closing_cost_rate", "0.02",
                                           "conforming-2026.1.0"),
        )
        assert ftc.value == "176000.00"
        r = reserves_mod.reserves(
            lin, liquid_total=tv(lin, "liq", "92000.00"),
            retirement_vested_total=tv(lin, "ret", "150000.00"),
            retirement_haircut=lin.constant("retirement_asset_haircut", "0.60",
                                            "conforming-2026.1.0"),
            funds_to_close_tv=ftc,
            pitia_total=tv(lin, "pitia", "4838.71"),
        )
        assert r.post_closing_available.value == "6000.00"
        assert r.months.value == "1.2"  # floor, 1 dp

    def test_unseasoned_flag(self):
        lin = L()
        ftc = tv(lin, "ftc", "176000.00")
        flag = reserves_mod.unseasoned_funds_flag(
            lin, liquid_total=tv(lin, "liq", "180000.00"),
            unseasoned_unsourced_deposit_total=tv(lin, "unsea", "10000.00"),
            funds_to_close_tv=ftc,
        )
        assert flag.value == "1"  # 170,000 seasoned < 176,000 needed


# ---------------------------------------------------------------- T-CAL-6 score
class TestScoreGoldens:
    def test_representative_742(self):
        lin = L()
        b1 = score_mod.borrower_representative(
            lin, borrower_id="b1",
            scores=[("equifax", tv(lin, "e1", "761")),
                    ("experian", tv(lin, "x1", "768")),
                    ("transunion", tv(lin, "t1", "755"))],
        )
        assert b1.value == "761"
        b2 = score_mod.borrower_representative(
            lin, borrower_id="b2",
            scores=[("equifax", tv(lin, "e2", "742")),
                    ("experian", tv(lin, "x2", "749")),
                    ("transunion", tv(lin, "t2", "731"))],
        )
        assert b2.value == "742"
        loan = score_mod.loan_representative(lin, borrower_reps=[b1, b2])
        assert loan.value == "742"

    def test_two_scores_lower(self):
        lin = L()
        rep = score_mod.borrower_representative(
            lin, borrower_id="b1",
            scores=[("equifax", tv(lin, "e", "700")), ("experian", tv(lin, "x", "710"))],
        )
        assert rep.value == "700"


# ---------------------------------------------------------------- T-CAL-7 ATR
def test_atr_always_eight_rows():
    rows = build_atr_evaluations(
        income_ref="Lref1", employment_refs=[], principal_interest_ref="Lref3",
        simultaneous_ref="Lref4", pitia_components_ref="Lref5",
        liabilities_ref="Lref6", back_ratio_ref="Lref7", credit_ref=None,
    )
    assert len(rows) == 8
    assert [r.factor_number for r in rows] == list(range(1, 9))
    assert rows[1].basis == "unavailable — condition raised"  # no VOE
    assert rows[7].basis == "unavailable — condition raised"  # no credit ref
    assert all(r.basis for r in rows)


# ---------------------------------------------------------------- T-CAL-8 purity
def test_calculations_are_deterministic():
    """Same inputs twice -> identical values AND identical lineage refs."""
    def run() -> tuple[str, str, dict]:
        lin = L()
        pi = dti_mod.principal_interest(
            lin, loan_amount=tv(lin, "amt", "640000.00"),
            note_rate_pct=tv(lin, "rate", "6.125"), term_months=360)
        return pi.value, pi.lineage_ref, {r: n.value for r, n in lin.nodes.items()}

    a, b = run(), run()
    assert a == b


# ---------------------------------------------------------------- T-CAL-1 no floats
def test_no_float_literals_or_annotations_in_domain():
    """AST lint: no float literals/annotations in money paths (NFR-2)."""
    domain = pathlib.Path(__file__).resolve().parents[1] / "app" / "domain"
    offenders: list[str] = []
    for py in domain.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                offenders.append(f"{py.name}:{node.lineno} float literal {node.value}")
            # numeric.py hosts the isinstance(value, float) rejection guard itself
            if py.name != "numeric.py" and isinstance(node, ast.Name) and node.id == "float":
                offenders.append(f"{py.name}:{node.lineno} float reference")
    assert not offenders, offenders


def test_decimal_string_round_trip():
    for s in ("0.00", "9200.00", "48.500", "80.01", "1.2"):
        assert str(D(s)) == s
