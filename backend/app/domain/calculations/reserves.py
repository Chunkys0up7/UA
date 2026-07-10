"""Funds to close, seasoning inputs, and reserves (specs/06 §5, FR-CAL-4).

Golden (T-CAL-5): liquid 92,000 + retirement 150,000x0.6 = 182,000
available; funds_to_close 160,000 + 16,000 = 176,000; post-closing 6,000;
6,000 / 4,838.71 -> 1.2 months (floor, 1 dp).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.lineage import Lineage, TracedValue
from app.domain.numeric import D, money, months_floor


def funds_to_close(
    lineage: Lineage,
    *,
    down_payment: TracedValue,
    cost_basis: TracedValue,  # purchase price (purchase) or loan amount (refi)
    closing_cost_rate: TracedValue,
) -> TracedValue:
    value = money(D(down_payment.value) + D(cost_basis.value) * D(closing_cost_rate.value))
    return lineage.add(
        "calculation", "assets.funds_to_close", str(value),
        parents=(down_payment.lineage_ref, cost_basis.lineage_ref,
                 closing_cost_rate.lineage_ref),
        method="down_payment_plus_est_closing",
    )


@dataclass(frozen=True)
class ReservesResult:
    months: TracedValue
    post_closing_available: TracedValue


def reserves(
    lineage: Lineage,
    *,
    liquid_total: TracedValue,
    retirement_vested_total: TracedValue,
    retirement_haircut: TracedValue,
    funds_to_close_tv: TracedValue,
    pitia_total: TracedValue,
) -> ReservesResult:
    available = D(liquid_total.value) + D(retirement_vested_total.value) * D(retirement_haircut.value)
    post_closing = money(available - D(funds_to_close_tv.value))
    post_tv = lineage.add(
        "calculation", "assets.post_closing_available", str(post_closing),
        parents=(liquid_total.lineage_ref, retirement_vested_total.lineage_ref,
                 retirement_haircut.lineage_ref, funds_to_close_tv.lineage_ref),
        method="available_minus_funds_to_close",
    )
    months = months_floor(max(post_closing, D("0")) / D(pitia_total.value))
    months_tv = lineage.add(
        "calculation", "assets.reserves_months", str(months),
        parents=(post_tv.lineage_ref, pitia_total.lineage_ref),
        method="post_closing_over_pitia_floor",
    )
    return ReservesResult(months=months_tv, post_closing_available=post_tv)


def unseasoned_funds_flag(
    lineage: Lineage,
    *,
    liquid_total: TracedValue,
    unseasoned_unsourced_deposit_total: TracedValue,
    funds_to_close_tv: TracedValue,
) -> TracedValue:
    """specs/06 §5.1 — 1 if the file NEEDS unseasoned money to close."""
    seasoned = D(liquid_total.value) - D(unseasoned_unsourced_deposit_total.value)
    flag = "1" if seasoned < D(funds_to_close_tv.value) else "0"
    return lineage.add(
        "calculation", "assets.unseasoned_funds", flag,
        parents=(liquid_total.lineage_ref,
                 unseasoned_unsourced_deposit_total.lineage_ref,
                 funds_to_close_tv.lineage_ref),
        method="seasoned_funds_insufficient_to_close",
    )


__all__ = ["funds_to_close", "reserves", "ReservesResult", "unseasoned_funds_flag"]
