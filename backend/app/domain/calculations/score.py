"""Representative credit score (specs/06 §6, FR-CAL-5).

Per borrower: middle of 3 / lower of 2 / the single score.
Loan level: LOWEST representative across borrowers.
Golden (T-CAL-6): (761,768,755)->761; (742,749,731)->742; loan -> 742.
"""

from __future__ import annotations

from app.domain.lineage import Lineage, TracedValue


def borrower_representative(
    lineage: Lineage, *, borrower_id: str, scores: list[tuple[str, TracedValue]]
) -> TracedValue:
    """`scores` = [(bureau, score)] with 1-3 entries."""
    if not scores:
        raise ValueError(f"borrower {borrower_id} has no scores (Tier-2 validation)")
    values = sorted(int(tv.value) for _, tv in scores)
    if len(values) == 3:
        rep, method = values[1], "middle_of_three"
    elif len(values) == 2:
        rep, method = values[0], "lower_of_two"
    else:
        rep, method = values[0], "single_score"
    return lineage.add(
        "calculation", f"credit.representative.{borrower_id}", str(rep),
        parents=tuple(tv.lineage_ref for _, tv in scores), method=method,
    )


def loan_representative(
    lineage: Lineage, *, borrower_reps: list[TracedValue]
) -> TracedValue:
    lowest = min(borrower_reps, key=lambda tv: int(tv.value))
    return lineage.add(
        "calculation", "credit.representative_score", lowest.value,
        parents=tuple(tv.lineage_ref for tv in borrower_reps),
        method="lowest_borrower_representative",
    )


__all__ = ["borrower_representative", "loan_representative"]
