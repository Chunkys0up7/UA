"""Seeded synthetic package factory + CLI (specs/14, FR-DAT-1..4).

Backwards construction: targets -> raw numbers through the REAL domain
calculations -> documents whose text contains exactly those numbers ->
ground-truth sidecars. Determinism: the only entropy is the seed; all
dates anchor to BASE_DATE; output serialized sorted-keys + LF.

CLI:
    python -m synthetic.generate --archetypes --out ../data/loans
    python -m synthetic.generate --corpus --count 500 --seed 1337 --out ../data/generated
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from decimal import Decimal
from pathlib import Path

from app.domain.calculations.dti import monthly_mi as calc_mi
from app.domain.calculations.dti import principal_interest as calc_pi
from app.domain.lineage import Lineage
from app.domain.numeric import D, HUNDRED, money, ratio_pct
from synthetic import renderers
from synthetic.archetypes import (
    Archetype, CORPUS_MIX, CORPUS_STATES, GOLDEN_ARCHETYPES, by_name,
)

BASE_DATE = dt.date(2026, 6, 30)
TREASURY_REF = D("4.250")          # matches reference-indices.json
FIRST_NAMES = ["Avery", "Jordan", "Riley", "Morgan", "Casey", "Quinn",
               "Rowan", "Skyler", "Emerson", "Finley"]
LAST_NAMES = ["Calder", "Whitfield", "Nakamura", "Osei", "Lindqvist",
              "Marchetti", "Delacroix", "Okafor", "Petrov", "Hale"]
EMPLOYERS = ["Acme Logistics LLC", "Bluefield Systems Inc", "Cardinal Health Partners",
             "Dunmore Analytics", "Evergreen Manufacturing Co"]
BANKS = ["First Meridian Bank", "Lakeside Federal CU"]
CITIES = {"OH": ("Columbus", "Franklin", "43004"), "PA": ("Pittsburgh", "Allegheny", "15201"),
          "MI": ("Ann Arbor", "Washtenaw", "48103"), "TX": ("Austin", "Travis", "78701"),
          "CA": ("Sacramento", "Sacramento", "95814"), "NY": ("Albany", "Albany", "12207"),
          "FL": ("Orlando", "Orange", "32801"), "MA": ("Worcester", "Worcester", "01601"),
          "GA": ("Atlanta", "Fulton", "30301"), "CO": ("Denver", "Denver", "80201")}


def _iso(date: dt.date) -> str:
    return date.isoformat()


def _pi_amount(loan: str, rate: str, term: int) -> Decimal:
    lineage = Lineage(application_id="SYNTHSOLVER00000000000000")
    tv = calc_pi(lineage,
                 loan_amount=lineage.add("package_stated", "amt", loan),
                 note_rate_pct=lineage.add("package_stated", "rate", rate),
                 term_months=term)
    return D(tv.value)


def solve_income_for_back_ratio(
    pitia: Decimal, target_back: Decimal, alpha: Decimal = D("0.13"),
) -> tuple[Decimal, Decimal, Decimal]:
    """Find (income, liabilities, actual_back) with back ratio == target
    exactly at 3 dp where reachable; otherwise the closest cent."""
    start = money(pitia / (target_back / HUNDRED - alpha))
    best = (D("999"), start, money(alpha * start))
    for cents in range(-60, 61):
        income = start + D(cents) / 100
        liabilities = money(alpha * income)
        back = ratio_pct((pitia + liabilities) / income * HUNDRED)
        error = abs(back - target_back)
        if error < best[0]:
            best = (error, income, liabilities)
            if error == 0:
                break
    _, income, liabilities = best
    back = ratio_pct((pitia + liabilities) / income * HUNDRED)
    return income, liabilities, back


def build_package(archetype: Archetype, rng: random.Random,
                  state: str | None = None) -> dict:
    state = state or archetype.state
    city, county, zip_code = CITIES.get(state, CITIES["OH"])
    borrower_name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
    employer = rng.choice(EMPLOYERS)
    bank = rng.choice(BANKS)
    ssn = f"900-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"

    purpose = archetype.purpose
    price = D(archetype.price)
    if archetype.loan_amount_override:
        loan = D(archetype.loan_amount_override)
    else:
        loan = money(price * D(archetype.target_ltv) / HUNDRED)
    appraised = money(price + D("5000"))

    # --- housing expense -------------------------------------------------
    extras = archetype.extras
    pi = _pi_amount(str(loan), archetype.note_rate, archetype.term_months)
    taxes = D(extras.get("fixed_taxes_monthly") or money(price * D("0.012") / D("12")))
    hazard = D(extras.get("fixed_hazard_monthly") or money(price * D("0.00225") / D("12")))
    ltv_actual = ratio_pct(loan / min(price, appraised) * HUNDRED).quantize(D("0.01"))
    mi = (money(loan * D("0.0055") / D("12"))
          if ltv_actual > D("80.00") else D("0.00"))
    pitia = money(pi + taxes + hazard + mi)

    # --- income & liabilities solved for the DTI target ------------------
    if extras.get("fixed_income_monthly"):
        income = D(extras["fixed_income_monthly"])
        liabilities = D(extras["fixed_liabilities_monthly"])
    else:
        income, liabilities, _ = solve_income_for_back_ratio(
            pitia, D(archetype.target_back_dti))

    # decompose income by kind
    bonus_monthly = D("0.00")
    rental_monthly = D("0.00")
    if archetype.income_kind == "base_bonus":
        bonus_monthly = money(income * D("0.10"))
        base_monthly = money(income - bonus_monthly)
    elif archetype.income_kind == "base_rental":
        rental_monthly = money(income * D("0.15"))
        base_monthly = money(income - rental_monthly)
    elif archetype.income_kind == "self_employed":
        base_monthly = D("0.00")
    else:
        base_monthly = income

    # --- assets solved for the reserves target ---------------------------
    down = money(price - loan) if purpose == "purchase" else D("0.00")
    closing_basis = price if purpose == "purchase" else loan
    funds_to_close = money(down + closing_basis * D("0.02"))
    retirement = D(archetype.retirement_balance)
    post_closing_target = money(D(archetype.target_reserves_months) * pitia + D("30"))
    liquid_total = money(funds_to_close + post_closing_target - retirement * D("0.60"))
    checking = money(liquid_total * D("0.6"))
    savings = money(liquid_total - checking)

    # --- credit -----------------------------------------------------------
    rep = archetype.target_score
    scores = {"equifax": rep, "experian": min(850, rep + 7),
              "transunion": max(300, rep - 6)}
    open_disputes = int(extras.get("open_disputes", 0))
    auto_payment = money(liabilities * D("0.35"))
    card_payment = money(liabilities - auto_payment)

    # --- documents ---------------------------------------------------------
    documents: list[dict] = []
    gross_semi = money(base_monthly / D("2")) if base_monthly else D("0.00")
    pay_date = BASE_DATE - dt.timedelta(days=5)
    periods_ytd = 12  # through June, semi-monthly
    borrower_id = "b1"

    def add_doc(doc_id: str, doc_type: str, text: str, truth: dict,
                period: str | None = None, borrower: str | None = borrower_id):
        doc = {"doc_id": doc_id, "doc_type": doc_type, "text_rendering": text}
        if borrower:
            doc["borrower_id"] = borrower
        if period:
            doc["period_label"] = period
        if truth:
            doc["ground_truth"] = truth
        documents.append(doc)

    if base_monthly > 0:
        ytd = money(gross_semi * periods_ytd)
        text, truth = renderers.paystub(
            employer=employer, borrower=borrower_name, gross=str(gross_semi),
            frequency="semi_monthly", ytd=str(ytd), pay_date=_iso(pay_date))
        add_doc("d1", "paystub", text, truth, "2026-06")
        for i, year in enumerate((2025, 2024)):
            wages = money(base_monthly * 12)
            text, truth = renderers.w2(employer=employer, borrower=borrower_name,
                                       wages=str(wages), tax_year=year)
            add_doc(f"d2{i}", "w2", text, truth, str(year))

    if archetype.income_kind == "self_employed":
        annual_avg = income * 12
        a1 = money(annual_avg * D("0.96"))
        a2 = money(annual_avg * 2 - a1)
        if archetype.se_declining:
            a1, a2 = money(annual_avg * D("1.3")), money(annual_avg * D("0.7"))
        dep1, dep2 = D("6000.00"), D("5500.00")
        for i, (year, annual, dep) in enumerate(
                ((2024, a1, dep1), (2025, a2, dep2))):
            net = money(annual - dep)
            text, truth = renderers.schedule_c(
                borrower=borrower_name, net_profit=str(net),
                depreciation=str(dep), tax_year=year)
            add_doc(f"d3{i}", "schedule_c", text, truth, str(year))
            text, truth = renderers.tax_return_1040(
                borrower=borrower_name, wages="0.00", agi=str(net),
                tax_year=year, schedule_c=True)
            add_doc(f"d4{i}", "tax_return_1040", text, truth, str(year))

    # bank statements: 2 months per account
    accounts = [("a1", "checking", checking), ("a2", "savings", savings)]
    statement_doc_ids: dict[str, list[str]] = {"a1": [], "a2": []}
    deposit_feature = archetype.large_deposit
    for month_index, (month_start, month_end) in enumerate((
        (BASE_DATE.replace(day=1) - dt.timedelta(days=31), BASE_DATE.replace(day=1) - dt.timedelta(days=1)),
        (BASE_DATE.replace(day=1), BASE_DATE),
    )):
        for account_id, kind, balance in accounts:
            deposits = []
            if kind == "checking" and base_monthly > 0:
                for day in (5, 20):
                    deposits.append({
                        "amount": str(gross_semi),
                        "date": _iso(month_start.replace(day=day)),
                        "description": f"PAYROLL {employer[:16].upper()}",
                    })
            if kind == "checking" and month_index == 1 and deposit_feature:
                amount = deposit_feature.get("amount") or str(
                    money(income * D(str(deposit_feature["pct_of_income"]))))
                deposits.append({
                    "amount": str(D(amount)),
                    "date": _iso(BASE_DATE - dt.timedelta(
                        days=deposit_feature["age_days"])),
                    "description": "TRANSFER IN",
                })
                if deposit_feature.get("round_pattern"):
                    for offset in (32, 40):
                        deposits.append({
                            "amount": "2500.00",
                            "date": _iso(BASE_DATE - dt.timedelta(days=offset)),
                            "description": "TRANSFER IN",
                        })
            doc_id = f"d5{account_id}{month_index}"
            text, truth = renderers.bank_statement(
                bank=bank, account_last4=f"77{account_id[-1]}1",
                period_start=_iso(month_start), period_end=_iso(month_end),
                ending_balance=str(balance), deposits=deposits)
            add_doc(doc_id, "bank_statement", text, truth,
                    f"{month_start:%Y-%m}", borrower=None)
            statement_doc_ids[account_id].append(doc_id)

    address = f"{rng.randint(100, 9999)} Synthetic Way, {city}, {state} {zip_code}"
    hazard_hint = ("Landlord/rental policy noted on site."
                   if archetype.hazard_policy_type == "landlord_rental"
                   else "Owner-occupied; standard hazard policy noted.")
    text, truth = renderers.appraisal(
        address=address, value=str(appraised),
        effective_date=_iso(BASE_DATE - dt.timedelta(days=10)),
        property_type="two_to_four_unit" if archetype.units > 1 else "sfr_detached",
        hazard_hint=hazard_hint)
    add_doc("d6", "appraisal", text, truth, borrower=None)

    text, truth = renderers.urla_1003(
        borrower=borrower_name, stated_income=str(income),
        stated_liabilities=str(liabilities), employers=[employer],
        occupancy_primary=archetype.occupancy == "primary")
    add_doc("d7", "urla_1003", text, truth)

    text, truth = renderers.tri_merge_stub(
        report_date=_iso(BASE_DATE - dt.timedelta(days=12)), rep_score=rep)
    add_doc("d8", "tri_merge_credit", text, {}, borrower=None)

    rent = D("0.00")
    if archetype.income_kind == "base_rental":
        rent = money(rental_monthly / D("0.75"))
        text, truth = renderers.lease(
            tenant="Unit B Tenant", monthly_rent=str(rent), term_months=12,
            start_date=_iso(BASE_DATE - dt.timedelta(days=200)))
        add_doc("d9", "lease", text, truth, borrower=None)

    # --- assemble package ---------------------------------------------------
    stated_other_income = []
    if bonus_monthly > 0:
        stated_other_income.append({
            "type": "bonus", "monthly_amount": str(bonus_monthly),
            "history_months": archetype.bonus_history_months})
    if rental_monthly > 0:
        stated_other_income.append({
            "type": "rental", "monthly_amount": str(rental_monthly),
            "history_months": 24})

    apr = str((TREASURY_REF + D(archetype.apr_spread_treasury)).quantize(D("0.001")))
    package: dict = {
        "package_version": "1.0",
        "loan": {
            "amount": str(loan), "purpose": purpose,
            "occupancy": archetype.occupancy,
            "loan_type": "conventional_conforming",
            "note_rate": archetype.note_rate, "apr": apr,
            "total_points_and_fees": str(money(loan * D("0.021"))),
            "lender_controlled_fees": str(money(loan * D(archetype.lender_fees_pct) / HUNDRED)),
            "term_months": archetype.term_months,
            "mlo_nmls_id": str(1000000 + rng.randint(0, 899999)),
            "county_high_cost": archetype.county_high_cost,
        },
        "property": {
            "address": {"street": address.split(",")[0], "city": city,
                        "state": state, "zip": zip_code, "county": county},
            "property_type": ("two_to_four_unit" if archetype.units > 1
                              else "sfr_detached"),
            "units": archetype.units,
            **({"purchase_price": str(price)} if purpose == "purchase" else {}),
            "appraised_value": str(appraised),
            "appraisal_effective_date": _iso(BASE_DATE - dt.timedelta(days=10)),
            "subordinate_liens": [],
            "annual_taxes": str(money(taxes * 12)),
            "annual_hazard_insurance": str(money(hazard * 12)),
            "hazard_policy_type": archetype.hazard_policy_type,
            "monthly_hoa": "0.00",
            "flood_zone_sidecar": "X",
        },
        "borrowers": [{
            "borrower_id": borrower_id, "full_name": borrower_name,
            "ssn": ssn, "dob": "1988-04-02", "is_primary": True,
            "self_employed": archetype.income_kind == "self_employed",
            "employment": [{
                "employer": employer, "position": "Operations Manager",
                "start_date": "2019-03-01",
                "monthly_base_income_stated": str(base_monthly),
                "distance_to_property_miles_sidecar": archetype.employer_distance_miles,
            }],
            "stated_other_income": stated_other_income,
            "voe_sidecar": {"result": archetype.voe_result},
        }],
        "credit": {
            "report_date": _iso(BASE_DATE - dt.timedelta(days=12)),
            "permissible_purpose": "credit_transaction",
            "scores": [{"borrower_id": borrower_id, **scores}],
            "tradelines": [
                {"kind": "auto_loan", "monthly_payment": str(auto_payment),
                 "balance": str(money(auto_payment * 30)), "dispute": False,
                 "payments_remaining": 30, "late_30_count_12mo": 0, "derog": None},
                {"kind": "credit_card", "monthly_payment": str(card_payment),
                 "balance": str(money(card_payment * 20)), "dispute": open_disputes > 0,
                 "late_30_count_12mo": 0, "derog": None},
            ],
            "derogatories": [],
            "open_disputes": open_disputes,
            "score_range": {"low": 300, "high": 850},
            "key_factors": ["Proportion of balances to credit limits",
                            "Length of revolving credit history"],
        },
        "assets": {
            "accounts": [
                {"account_id": "a1", "kind": "checking", "balance": str(checking),
                 "statements_doc_ids": statement_doc_ids["a1"]},
                {"account_id": "a2", "kind": "savings", "balance": str(savings),
                 "statements_doc_ids": statement_doc_ids["a2"]},
            ],
            "retirement_accounts": (
                [{"kind": "401k", "vested_balance": str(retirement)}]
                if retirement > 0 else []),
            "down_payment_source": "checking a1",
            "gift_funds": [],
        },
        "liabilities_stated_monthly_total": str(liabilities),
        "processor_computed": {
            # deliberately +0.2pp on back DTI: exercises the discrepancy
            # path without exceeding tolerance (specs/14 §2)
            "front_dti": str((ratio_pct(pitia / income * HUNDRED) + D("0.2"))
                             .quantize(D("0.1"))),
            "back_dti": str((ratio_pct((pitia + liabilities) / income * HUNDRED)
                             + D("0.2")).quantize(D("0.1"))),
            "qualifying_income_monthly": str(income),
        },
        "documents": documents,
        "hmda_demographics": {
            borrower_id: {
                "ethnicity": rng.choice(["hispanic", "not_hispanic"]),
                "race": rng.choice(["white", "black", "asian", "two_or_more"]),
                "sex": rng.choice(["female", "male"]),
                "age_band": rng.choice(["25-34", "35-44", "45-54"]),
            },
        },
    }

    if archetype.prior_a6_days is not None:
        package["property"]["prior_home_equity_loan_date"] = _iso(
            BASE_DATE - dt.timedelta(days=archetype.prior_a6_days))
    if state == "TX" and purpose == "cash_out_refi" and archetype.tx_notice_on_file:
        package["property"]["tx_a6_notice_date"] = _iso(
            BASE_DATE - dt.timedelta(days=15))
    if archetype.ofac_marker:
        package["borrowers"][0]["full_name"] = "SANCTIONED TEST PARTY"

    return package


def _dump(path: Path, obj: dict) -> None:
    path.write_text(
        json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")


def generate_archetypes(out_dir: Path, seed: int = 42) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for archetype in GOLDEN_ARCHETYPES:
        rng = random.Random(f"{seed}:{archetype.name}")
        package = build_package(archetype, rng)
        path = out_dir / f"{archetype.name}.json"
        _dump(path, package)
        written.append(path)
    return written


def generate_corpus(out_dir: Path, count: int, seed: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    names = [name for name, weight in CORPUS_MIX for _ in range(weight)]
    states = [state for state, weight in CORPUS_STATES for _ in range(weight)]
    manifest: dict = {"seed": seed, "count": count, "packages": []}
    for index in range(count):
        archetype = by_name(rng.choice(names))
        state = archetype.state if archetype.state != "OH" else rng.choice(states)
        package_rng = random.Random(f"{seed}:{index}")
        package = build_package(archetype, package_rng, state=state)
        filename = f"pkg-{index:04d}-{archetype.name}.json"
        _dump(out_dir / filename, package)
        manifest["packages"].append({
            "file": filename, "archetype": archetype.name, "state": state,
            "expected_family": archetype.expected_family, "boundary": False,
        })
    _dump(out_dir / "manifest.json", manifest)
    return out_dir / "manifest.json"


def main() -> None:  # pragma: no cover - CLI shell
    parser = argparse.ArgumentParser()
    parser.add_argument("--archetypes", action="store_true")
    parser.add_argument("--corpus", action="store_true")
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.archetypes:
        paths = generate_archetypes(args.out, seed=args.seed)
        print(f"wrote {len(paths)} archetypes to {args.out}")
    if args.corpus:
        manifest = generate_corpus(args.out, args.count, args.seed)
        print(f"wrote corpus manifest {manifest}")


if __name__ == "__main__":
    main()


__all__ = ["build_package", "generate_archetypes", "generate_corpus", "BASE_DATE"]
