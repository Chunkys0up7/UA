"""The 15 golden archetypes (specs/14 §4) + corpus families (specs/14 §5).

Each archetype declares TARGETS (ratios/scores the finished package must
exhibit) and FEATURES (deposits, VOE results, state extras). The
generator solves for raw numbers through the real domain calculations,
so internal consistency is by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Archetype:
    name: str
    description: str
    # loan shape
    purpose: str = "purchase"            # purchase | rate_term_refi | cash_out_refi
    occupancy: str = "primary"
    units: int = 1
    state: str = "OH"
    county_high_cost: bool = False
    price: str = "800000.00"
    note_rate: str = "6.125"
    term_months: int = 360
    # targets
    target_ltv: str = "75.00"
    target_back_dti: str = "32.000"
    target_score: int = 780
    target_reserves_months: str = "8.0"
    # income shape
    income_kind: str = "base"            # base | base_bonus | self_employed | base_rental
    bonus_history_months: int = 30
    se_history_months: int = 30
    se_declining: bool = False
    # features
    voe_result: str = "verified"
    large_deposit: dict[str, Any] | None = None      # {"amount","age_days","sourced","round_pattern"}
    hazard_policy_type: str = "owner_occupied"
    employer_distance_miles: int = 12
    ofac_marker: bool = False
    gift_funds: bool = False
    retirement_balance: str = "0.00"
    # state extras
    prior_a6_days: int | None = None
    tx_notice_on_file: bool = True
    lender_fees_pct: str = "1.000"
    apr_spread_treasury: str = "2.150"
    # expectations (asserted by T-DAT-2; families drive the corpus report)
    expected_family: str = "approve"     # approve | conditional | suspend | decline
    expected_failed_rules: tuple[str, ...] = ()
    expected_red_flags: tuple[str, ...] = ()
    loan_amount_override: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


GOLDEN_ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        name="clean-approve",
        description="W-2 borrower, everything clean (specs/14 #1)",
    ),
    Archetype(
        name="conditional-approve",
        description="VOE unavailable + unsourced 26%-of-income deposit (#2)",
        voe_result="unavailable",
        large_deposit={"pct_of_income": "0.26", "age_days": 30, "sourced": False},
        expected_family="suspend",
        expected_red_flags=("RF-DEP-UNSOURCED",),
        expected_failed_rules=("AST-002",),
    ),
    Archetype(
        name="borderline-dti-compensating",
        description="back 48.500 exactly; 3 compensating factors carry it (#3)",
        target_back_dti="48.500", target_score=745,
        target_reserves_months="6.5", target_ltv="74.00",
    ),
    Archetype(
        name="self-employed",
        description="2-yr Schedule C average, 30-mo history (#4)",
        income_kind="self_employed", target_back_dti="41.000",
    ),
    Archetype(
        name="bonus-income-short-history",
        description="14-mo bonus history -> 75% YTD haircut (#5)",
        income_kind="base_bonus", bonus_history_months=14,
        target_back_dti="44.500",
    ),
    Archetype(
        name="rental-investor",
        description="2-unit investment purchase w/ lease at 75% credit (#6)",
        income_kind="base_rental", occupancy="investment", units=2,
        target_ltv="74.00", target_reserves_months="7.0", target_score=760,
    ),
    Archetype(
        name="large-deposit-flag",
        description="$14k round unsourced deposit + round pattern (#7)",
        large_deposit={"amount": "14000.00", "age_days": 20, "sourced": False,
                       "round_pattern": True},
        expected_family="suspend",
        expected_red_flags=("RF-DEP-UNSOURCED", "RF-DEP-PATTERN"),
        expected_failed_rules=("AST-002",),
    ),
    Archetype(
        name="occupancy-fraud-flag",
        description="primary claim, 420 mi from employer, landlord policy (#8)",
        employer_distance_miles=420, hazard_policy_type="landlord_rental",
        expected_family="suspend",
        expected_red_flags=("RF-OCC-DISTANCE", "RF-OCC-INSURANCE"),
    ),
    Archetype(
        name="decline-credit",
        description="rep 585 + open dispute (#9)",
        target_score=585, extras={"open_disputes": 1},
        expected_family="decline",
        expected_failed_rules=("CR-001", "CR-002"),
    ),
    Archetype(
        name="decline-dti-counteroffer",
        description="the specs/06 §3 vector: back 56.438 at 640k (#10)",
        target_back_dti="56.438",
        loan_amount_override="640000.00", target_ltv="80.00",
        expected_family="decline",
        expected_failed_rules=("DTI-001",),
        extras={"expected_counteroffer": "429000.00",
                "fixed_income_monthly": "11195.83",
                "fixed_liabilities_monthly": "1480.00",
                "fixed_taxes_monthly": "800.00",
                "fixed_hazard_monthly": "150.00"},
    ),
    Archetype(
        name="high-ltv-decline",
        description="second home at LTV 93 (max 90) (#11)",
        occupancy="second_home", target_ltv="93.00",
        target_reserves_months="3.0",
        expected_family="decline",
        expected_failed_rules=("LTV-001", "LTV-002"),
    ),
    Archetype(
        name="jumbo-ineligible",
        description="$850k standard county (#12)",
        loan_amount_override="850000.00", price="1100000.00",
        expected_family="decline",
        expected_failed_rules=("LIMIT-001",),
    ),
    Archetype(
        name="tx-a6-approve",
        description="TX homestead cash-out, all a6 gates pass (#13)",
        state="TX", purpose="cash_out_refi", target_ltv="78.00",
        expected_family="approve",
        extras={"expected_artifacts": ("TX-A6-DOCSET",)},
    ),
    Archetype(
        name="tx-a6-seasoning-decline",
        description="TX a6, base-eligible, prior a6 320 days ago (#14)",
        state="TX", purpose="cash_out_refi", target_ltv="79.50",
        prior_a6_days=320,
        expected_family="decline",
        expected_failed_rules=("STX-005",),
    ),
    Archetype(
        name="ny-highcost-decline",
        description="NY purchase, APR spread 8.5 over Treasury (#15)",
        state="NY", apr_spread_treasury="8.500",
        expected_family="decline",
        expected_failed_rules=("SNY-001",),
    ),
)

# Corpus family mix (specs/14 §5): weights sum to 100.
CORPUS_MIX: tuple[tuple[str, int], ...] = (
    ("clean-approve", 35),
    ("conditional-approve", 15),
    ("borderline-dti-compensating", 10),
    ("self-employed", 5),
    ("bonus-income-short-history", 5),
    ("large-deposit-flag", 5),
    ("occupancy-fraud-flag", 5),
    ("decline-credit", 4),
    ("decline-dti-counteroffer", 3),
    ("high-ltv-decline", 3),
    ("jumbo-ineligible", 2),
    ("tx-a6-approve", 3),
    ("tx-a6-seasoning-decline", 2),
    ("ny-highcost-decline", 3),
)

CORPUS_STATES: tuple[tuple[str, int], ...] = (
    ("OH", 20), ("PA", 12), ("MI", 10), ("TX", 14), ("CA", 12),
    ("NY", 8), ("FL", 10), ("MA", 5), ("GA", 5), ("CO", 4),
)


def by_name(name: str) -> Archetype:
    for archetype in GOLDEN_ARCHETYPES:
        if archetype.name == name:
            return archetype
    raise KeyError(name)


__all__ = ["Archetype", "GOLDEN_ARCHETYPES", "CORPUS_MIX", "CORPUS_STATES", "by_name"]
