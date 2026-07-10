"""ATR eight-factor evaluation (specs/06 §8, 12 CFR 1026.43, FR-CAL-6).

Produces exactly 8 rows per run — always. A factor whose evidence is
unavailable still gets a row with basis "unavailable — condition raised":
the regulation requires the factor be CONSIDERED, and the gap surfaced.
"""

from __future__ import annotations

from dataclasses import dataclass

FACTOR_NAMES: dict[int, str] = {
    1: "Current or reasonably expected income or assets",
    2: "Current employment status",
    3: "Monthly payment on the covered transaction",
    4: "Monthly payment on simultaneous loans",
    5: "Monthly payment for mortgage-related obligations",
    6: "Current debt obligations, alimony, and child support",
    7: "Monthly debt-to-income ratio or residual income",
    8: "Credit history",
}


@dataclass(frozen=True)
class AtrEvaluation:
    factor_number: int
    factor_name: str
    basis: str
    evidence_ref: str  # lineage ref (or adapter-result ref)


def build_atr_evaluations(
    *,
    income_ref: str | None,
    employment_refs: list[str],
    principal_interest_ref: str | None,
    simultaneous_ref: str | None,
    pitia_components_ref: str | None,
    liabilities_ref: str | None,
    back_ratio_ref: str | None,
    credit_ref: str | None,
) -> list[AtrEvaluation]:
    def row(n: int, basis: str, ref: str | None) -> AtrEvaluation:
        if ref is None:
            return AtrEvaluation(n, FACTOR_NAMES[n],
                                 "unavailable — condition raised", "")
        return AtrEvaluation(n, FACTOR_NAMES[n], basis, ref)

    employment_basis = (
        f"VOE results for {len(employment_refs)} borrower(s)"
        if employment_refs else "unavailable — condition raised"
    )
    rows = [
        row(1, "qualifying income computation", income_ref),
        AtrEvaluation(2, FACTOR_NAMES[2], employment_basis,
                      employment_refs[0] if employment_refs else ""),
        row(3, "amortized principal & interest", principal_interest_ref),
        row(4, "subordinate lien payments (CLTV inputs)", simultaneous_ref),
        row(5, "taxes, insurance, MI, HOA (PITIA components)", pitia_components_ref),
        row(6, "liability rollup incl. court-ordered obligations", liabilities_ref),
        row(7, "back-end debt-to-income ratio", back_ratio_ref),
        row(8, "representative score and derogatories", credit_ref),
    ]
    assert len(rows) == 8 and [r.factor_number for r in rows] == list(range(1, 9))
    return rows


__all__ = ["AtrEvaluation", "build_atr_evaluations", "FACTOR_NAMES"]
