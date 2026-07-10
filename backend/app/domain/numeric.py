"""Numeric conventions (specs/06 §1, NFR-2).

All money and ratio math uses Decimal. Floats are forbidden in this
package (T-CAL-1 lints for them). Helpers here are the only quantization
sites so rounding modes stay uniform:

- currency: 2 dp, ROUND_HALF_EVEN (banker's)
- DTI ratios: percent scale, 3 dp, ROUND_HALF_EVEN
- LTV/CLTV: percent scale, 2 dp, ROUND_CEILING (conservative)
- reserves months: 1 dp, ROUND_FLOOR (conservative)
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

TWO_DP = Decimal("0.01")
THREE_DP = Decimal("0.001")
ONE_DP = Decimal("0.1")
HUNDRED = Decimal("100")


def D(value: str | int | Decimal) -> Decimal:
    """Parse into Decimal. Floats are deliberately rejected (NFR-2)."""
    if isinstance(value, float):  # pragma: no cover - guarded by tests
        raise TypeError("float is forbidden in domain math (NFR-2); pass str")
    return Decimal(str(value))


def money(value: Decimal) -> Decimal:
    return value.quantize(TWO_DP, rounding=ROUND_HALF_EVEN)


def ratio_pct(value: Decimal) -> Decimal:
    """Percent scale, 3 dp (e.g. Decimal('48.500'))."""
    return value.quantize(THREE_DP, rounding=ROUND_HALF_EVEN)


def ltv_pct(value: Decimal) -> Decimal:
    """Percent scale, 2 dp, rounded UP (conservative)."""
    return value.quantize(TWO_DP, rounding=ROUND_CEILING)


def months_floor(value: Decimal) -> Decimal:
    """Reserves months, 1 dp, rounded DOWN (conservative)."""
    return value.quantize(ONE_DP, rounding=ROUND_FLOOR)


__all__ = ["D", "money", "ratio_pct", "ltv_pct", "months_floor", "HUNDRED"]
