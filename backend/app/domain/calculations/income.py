"""Qualifying income per component type (specs/06 §2, FR-CAL-1).

Every function returns TracedValues via the caller's Lineage accumulator.
Worked examples in specs/06 §2 are golden-test vectors (T-CAL-2).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.lineage import Lineage, TracedValue
from app.domain.numeric import D, money

FREQUENCY_FACTOR: dict[str, Decimal] = {
    "weekly": D("52") / D("12"),
    "biweekly": D("26") / D("12"),
    "semi_monthly": D("2"),
    "monthly": D("1"),
}


@dataclass(frozen=True)
class IncomeResult:
    monthly: TracedValue
    calc_method: str
    included: bool
    exclusion_reason: str | None = None
    declining: bool = False  # feeds RF-INC-DECLINING


def monthly_base(
    lineage: Lineage,
    *,
    gross_pay_period: TracedValue,
    pay_frequency: str,
) -> IncomeResult:
    """specs/06 §2.1 — base salary from paystub. 4600 semi_monthly -> 9200.00."""
    factor = FREQUENCY_FACTOR[pay_frequency]
    value = money(D(gross_pay_period.value) * factor)
    tv = lineage.add(
        "calculation",
        "income.base_monthly",
        str(value),
        parents=(gross_pay_period.lineage_ref,),
        method=f"paystub_{pay_frequency}",
    )
    return IncomeResult(monthly=tv, calc_method=f"paystub_{pay_frequency}", included=True)


def variable_income(
    lineage: Lineage,
    *,
    income_type: str,  # overtime | bonus | commission
    year1_total: TracedValue | None,
    year2_total: TracedValue | None,
    ytd_annualized: TracedValue | None,
    history_months: int,
    min_history_months: int = 12,
    full_history_months: int = 24,
    short_history_haircut: Decimal = D("0.75"),
    declining_threshold: Decimal = D("0.20"),
) -> IncomeResult:
    """specs/06 §2.2 — 2-yr average / 75% YTD haircut / exclusion ladder."""
    label = f"income.{income_type}_monthly"
    if history_months < min_history_months:
        tv = lineage.add("calculation", label, "0.00", method="excluded_insufficient_history")
        return IncomeResult(tv, "excluded_insufficient_history", False, "insufficient_history")

    if history_months >= full_history_months and year1_total and year2_total:
        y1, y2 = D(year1_total.value), D(year2_total.value)
        declining = y2 < y1 * (D("1") - declining_threshold)
        if declining:
            value = money(y2 / D("12"))
            tv = lineage.add(
                "calculation", label, str(value),
                parents=(year2_total.lineage_ref,), method="recent_year_declining",
            )
            return IncomeResult(tv, "recent_year_declining", True, declining=True)
        value = money((y1 + y2) / D("24"))
        tv = lineage.add(
            "calculation", label, str(value),
            parents=(year1_total.lineage_ref, year2_total.lineage_ref),
            method="two_year_average",
        )
        return IncomeResult(tv, "two_year_average", True)

    if ytd_annualized is None:
        tv = lineage.add("calculation", label, "0.00", method="excluded_undocumented")
        return IncomeResult(tv, "excluded_undocumented", False, "undocumented")
    value = money(D(ytd_annualized.value) * short_history_haircut / D("12"))
    tv = lineage.add(
        "calculation", label, str(value),
        parents=(ytd_annualized.lineage_ref,), method="75pct_ytd",
    )
    return IncomeResult(tv, "75pct_ytd", True)


@dataclass(frozen=True)
class ScheduleCYear:
    net_profit: TracedValue
    depreciation: TracedValue | None = None
    depletion: TracedValue | None = None
    home_office: TracedValue | None = None
    amortization_casualty: TracedValue | None = None

    def annual(self) -> Decimal:
        total = D(self.net_profit.value)
        for addback in (self.depreciation, self.depletion, self.home_office,
                        self.amortization_casualty):
            if addback is not None:
                total += D(addback.value)
        return total

    def parents(self) -> tuple[str, ...]:
        return tuple(
            tv.lineage_ref
            for tv in (self.net_profit, self.depreciation, self.depletion,
                       self.home_office, self.amortization_casualty)
            if tv is not None
        )


def self_employed_income(
    lineage: Lineage,
    *,
    year1: ScheduleCYear,
    year2: ScheduleCYear,
    history_months: int,
    min_history_months: int = 24,
    declining_threshold: Decimal = D("0.20"),
) -> IncomeResult:
    """specs/06 §2.3 — (98,000 + 106,500) / 24 = 8,520.83/mo golden."""
    if history_months < min_history_months:
        tv = lineage.add("calculation", "income.self_employed_monthly", "0.00",
                         method="excluded_se_history")
        return IncomeResult(tv, "excluded_se_history", False, "se_history_under_24mo")

    a1, a2 = year1.annual(), year2.annual()
    parents = year1.parents() + year2.parents()
    if a2 < a1 * (D("1") - declining_threshold):
        value = money(a2 / D("12"))
        tv = lineage.add("calculation", "income.self_employed_monthly", str(value),
                         parents=year2.parents(), method="recent_year_declining")
        return IncomeResult(tv, "recent_year_declining", True, declining=True)
    value = money((a1 + a2) / D("24"))
    tv = lineage.add("calculation", "income.self_employed_monthly", str(value),
                     parents=parents, method="two_year_average")
    return IncomeResult(tv, "two_year_average", True)


def rental_income(
    lineage: Lineage,
    *,
    gross_monthly_rent: TracedValue,
    factor: TracedValue,
) -> IncomeResult:
    """specs/06 §2.4 — subject-property rent x 0.75. 2,400 -> 1,800.00."""
    value = money(D(gross_monthly_rent.value) * D(factor.value))
    tv = lineage.add(
        "calculation", "income.rental_monthly", str(value),
        parents=(gross_monthly_rent.lineage_ref, factor.lineage_ref),
        method="rental_75pct",
    )
    return IncomeResult(tv, "rental_75pct", True)


def other_income(
    lineage: Lineage,
    *,
    income_type: str,
    monthly_amount: TracedValue,
    history_months: int,
    continuance_months: int | None,
    taxable: bool,
    grossup_factor: Decimal = D("1.25"),
) -> IncomeResult:
    """specs/06 §2.5 — support/pension/SS; non-taxable grossed up x1.25."""
    label = f"income.{income_type}_monthly"
    if income_type in ("alimony", "child_support") and (
        history_months < 3 or (continuance_months or 0) < 36
    ):
        tv = lineage.add("calculation", label, "0.00", method="excluded_continuance")
        return IncomeResult(tv, "excluded_continuance", False, "history_or_continuance")
    amount = D(monthly_amount.value)
    method = "documented"
    if not taxable:
        amount = amount * grossup_factor
        method = "grossed_up_125"
    value = money(amount)
    tv = lineage.add("calculation", label, str(value),
                     parents=(monthly_amount.lineage_ref,), method=method)
    return IncomeResult(tv, method, True)


def total_qualifying_income(
    lineage: Lineage, components: list[IncomeResult]
) -> TracedValue:
    """Loan-level sum of included components (specs/06 §2)."""
    total = sum((D(c.monthly.value) for c in components if c.included), D("0"))
    parents = tuple(c.monthly.lineage_ref for c in components if c.included)
    return lineage.add(
        "calculation", "income.qualifying_monthly", str(money(total)),
        parents=parents, method="sum_included_components",
    )


__all__ = [
    "IncomeResult", "ScheduleCYear", "monthly_base", "variable_income",
    "self_employed_income", "rental_income", "other_income",
    "total_qualifying_income", "FREQUENCY_FACTOR",
]
