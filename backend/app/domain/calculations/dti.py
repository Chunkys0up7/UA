"""P&I, MI, PITIA and DTI ratios (specs/06 §3, FR-CAL-2).

Golden vector (T-CAL-3): $640,000 @ 6.125%/360 -> P&I 3,888.71;
PITIA 4,838.71; income 11,195.83; liabilities 1,480.00 ->
front 43.219 / back 56.438 (percent scale, 3 dp).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.lineage import Lineage, TracedValue
from app.domain.numeric import D, HUNDRED, money, ratio_pct


def principal_interest(
    lineage: Lineage,
    *,
    loan_amount: TracedValue,
    note_rate_pct: TracedValue,
    term_months: int,
) -> TracedValue:
    """Standard annuity: P*r*(1+r)^n / ((1+r)^n - 1), Decimal throughout."""
    p = D(loan_amount.value)
    r = D(note_rate_pct.value) / HUNDRED / D("12")
    n = term_months
    if r == 0:
        value = money(p / D(n))
    else:
        f = (D("1") + r) ** n
        value = money(p * r * f / (f - D("1")))
    return lineage.add(
        "calculation", "pitia.principal_interest", str(value),
        parents=(loan_amount.lineage_ref, note_rate_pct.lineage_ref),
        method=f"annuity_{term_months}mo",
    )


def monthly_mi(
    lineage: Lineage,
    *,
    loan_amount: TracedValue,
    ltv: TracedValue,
    mi_annual_rate: TracedValue,
) -> TracedValue:
    """specs/06 §3 — MI applies above 80.00 LTV; else 0.00."""
    if D(ltv.value) > D("80.00"):
        value = money(D(loan_amount.value) * D(mi_annual_rate.value) / D("12"))
        method = "mi_annual_rate_over_80ltv"
        parents = (loan_amount.lineage_ref, ltv.lineage_ref, mi_annual_rate.lineage_ref)
    else:
        value, method = D("0.00"), "no_mi_le_80ltv"
        parents = (ltv.lineage_ref,)
    return lineage.add("calculation", "pitia.mi", str(money(value)),
                       parents=parents, method=method)


@dataclass(frozen=True)
class PitiaResult:
    total: TracedValue
    principal_interest: TracedValue
    taxes: TracedValue
    hazard: TracedValue
    mi: TracedValue
    hoa: TracedValue


def pitia(
    lineage: Lineage,
    *,
    principal_interest_tv: TracedValue,
    monthly_taxes: TracedValue,
    monthly_hazard: TracedValue,
    mi: TracedValue,
    monthly_hoa: TracedValue,
) -> PitiaResult:
    parts = (principal_interest_tv, monthly_taxes, monthly_hazard, mi, monthly_hoa)
    total = money(sum((D(p.value) for p in parts), D("0")))
    total_tv = lineage.add(
        "calculation", "pitia.total", str(total),
        parents=tuple(p.lineage_ref for p in parts), method="sum_pitia",
    )
    return PitiaResult(total_tv, principal_interest_tv, monthly_taxes,
                       monthly_hazard, mi, monthly_hoa)


@dataclass(frozen=True)
class DtiResult:
    front_ratio: TracedValue  # percent scale, 3 dp
    back_ratio: TracedValue


def dti_ratios(
    lineage: Lineage,
    *,
    pitia_total: TracedValue,
    monthly_liabilities: TracedValue,
    qualifying_income: TracedValue,
) -> DtiResult:
    income = D(qualifying_income.value)
    if income <= 0:
        raise ValueError("qualifying income must be positive for DTI (rule INC-001 gates zero income)")
    front = ratio_pct(D(pitia_total.value) / income * HUNDRED)
    back = ratio_pct((D(pitia_total.value) + D(monthly_liabilities.value)) / income * HUNDRED)
    front_tv = lineage.add(
        "calculation", "dti.front_ratio", str(front),
        parents=(pitia_total.lineage_ref, qualifying_income.lineage_ref),
        method="pitia_over_income_pct",
    )
    back_tv = lineage.add(
        "calculation", "dti.back_ratio", str(back),
        parents=(pitia_total.lineage_ref, monthly_liabilities.lineage_ref,
                 qualifying_income.lineage_ref),
        method="pitia_plus_debts_over_income_pct",
    )
    return DtiResult(front_tv, back_tv)


def monthly_liabilities(
    lineage: Lineage,
    *,
    tradeline_payments: list[tuple[TracedValue, int | None]],  # (payment, payments_remaining)
    court_ordered: list[TracedValue],
    exclusion_max_payments_remaining: int = 10,
) -> TracedValue:
    """specs/06 §3 — sum non-housing debts; <=10-payments installments excluded."""
    total = D("0")
    parents: list[str] = []
    for payment, remaining in tradeline_payments:
        if remaining is not None and remaining <= exclusion_max_payments_remaining:
            continue  # excluded_le_10_payments
        total += D(payment.value)
        parents.append(payment.lineage_ref)
    for obligation in court_ordered:
        total += D(obligation.value)
        parents.append(obligation.lineage_ref)
    return lineage.add(
        "calculation", "liabilities.monthly_total", str(money(total)),
        parents=tuple(parents), method="sum_debts_excl_le_10_payments",
    )


__all__ = [
    "principal_interest", "monthly_mi", "pitia", "PitiaResult",
    "dti_ratios", "DtiResult", "monthly_liabilities",
]
