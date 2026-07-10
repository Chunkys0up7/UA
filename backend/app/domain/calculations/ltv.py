"""LTV / CLTV (specs/06 §4, FR-CAL-3). Percent scale, 2 dp, rounded UP."""

from __future__ import annotations

from app.domain.lineage import Lineage, TracedValue
from app.domain.numeric import D, HUNDRED, ltv_pct


def value_basis(
    lineage: Lineage,
    *,
    purpose: str,
    purchase_price: TracedValue | None,
    appraised_value: TracedValue,
) -> TracedValue:
    """Purchase: min(price, appraisal). Refi: appraisal."""
    if purpose == "purchase":
        if purchase_price is None:
            raise ValueError("purchase requires purchase_price (FR-PKG-2)")
        if D(purchase_price.value) <= D(appraised_value.value):
            basis, method = purchase_price, "min_price_vs_appraisal:price"
            parents = (purchase_price.lineage_ref, appraised_value.lineage_ref)
        else:
            basis, method = appraised_value, "min_price_vs_appraisal:appraisal"
            parents = (purchase_price.lineage_ref, appraised_value.lineage_ref)
        return lineage.add("calculation", "ltv.value_basis", basis.value,
                           parents=parents, method=method)
    return lineage.add("calculation", "ltv.value_basis", appraised_value.value,
                       parents=(appraised_value.lineage_ref,), method="refi_appraised")


def ltv(
    lineage: Lineage, *, loan_amount: TracedValue, basis: TracedValue
) -> TracedValue:
    value = ltv_pct(D(loan_amount.value) / D(basis.value) * HUNDRED)
    return lineage.add("calculation", "ltv.ltv", str(value),
                       parents=(loan_amount.lineage_ref, basis.lineage_ref),
                       method="loan_over_basis_pct_ceil")


def cltv(
    lineage: Lineage,
    *,
    loan_amount: TracedValue,
    subordinate_balances: list[TracedValue],
    basis: TracedValue,
) -> TracedValue:
    total = D(loan_amount.value) + sum((D(b.value) for b in subordinate_balances), D("0"))
    value = ltv_pct(total / D(basis.value) * HUNDRED)
    parents = (loan_amount.lineage_ref, basis.lineage_ref,
               *(b.lineage_ref for b in subordinate_balances))
    return lineage.add("calculation", "ltv.cltv", str(value),
                       parents=parents, method="all_liens_over_basis_pct_ceil")


__all__ = ["value_basis", "ltv", "cltv"]
