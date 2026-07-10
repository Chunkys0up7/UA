"""Case assembly (specs/06 §2–§9, specs/07 §3, specs/17 §4).

THE shared derivation: (package, extracted fields, adapter results) ->
computed TracedValues + discrepancies + red flags + the rules-engine
evaluation context. The pipeline nodes AND snapshot replay both call
this module, so production and replay can never drift (HR-5).

Deterministic: pure Decimal math over its arguments; the as-of anchor is
the application's received date (specs/06 §1) — never the wall clock.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.adapters.base import AdapterResult
from app.domain.atr import AtrEvaluation, build_atr_evaluations
from app.domain.calculations import dti as dti_mod
from app.domain.calculations import income as income_mod
from app.domain.calculations import ltv as ltv_mod
from app.domain.calculations import reserves as reserves_mod
from app.domain.calculations import score as score_mod
from app.domain.lineage import Lineage, TracedValue
from app.domain.numeric import D, HUNDRED, money, ratio_pct

Context = dict[str, tuple[Any, str | None]]


@dataclass(frozen=True)
class Discrepancy:
    field: str
    stated_value: str
    documented_value: str
    tolerance: str
    exceeded: bool
    lineage_ref: str


@dataclass(frozen=True)
class RedFlag:
    flag_code: str
    severity: str  # info | elevated | critical
    description: str
    evidence_ref: str
    recommended_action: str


@dataclass
class AssembledCase:
    application_id: str
    lineage: Lineage
    context: Context
    four_cs: dict[str, Any]
    atr: list[AtrEvaluation]
    discrepancies: list[Discrepancy]
    red_flags: list[RedFlag]
    income_components: list[dict[str, Any]]
    computed: dict[str, Any] = field(default_factory=dict)


def _extracted(lineage: Lineage, doc_id: str, fields: dict, confidence: dict,
               field_name: str, *, prompt: str, model: str) -> TracedValue | None:
    if field_name not in fields:
        return None
    return lineage.add(
        "extracted_field", f"{doc_id}.{field_name}", str(fields[field_name]),
        source_id=doc_id,
        meta={"confidence": str(confidence.get(field_name, "0")),
              "prompt": prompt, "model": model},
    )


def assemble_case(
    *,
    application_id: str,
    package: dict,
    extractions: dict[str, dict],   # doc_id -> {"fields", "confidence", "prompt", "model"}
    adapter_results: dict[str, AdapterResult],  # name -> result
    constants: dict[str, Any],      # base pack constants.json
    states_index: dict[str, Any],
    reference_indices: dict[str, Any],
    compensating_factors: list[dict],
    pack_version: str,
    as_of: dt.date,
) -> AssembledCase:
    lineage = Lineage(application_id=application_id)
    discrepancies: list[Discrepancy] = []
    red_flags: list[RedFlag] = []
    loan = package["loan"]
    prop = package["property"]
    borrower = package["borrowers"][0]

    def stated(label: str, value: Any) -> TracedValue:
        return lineage.add("package_stated", label, str(value))

    def constant(name: str) -> TracedValue:
        return lineage.constant(name, str(constants[name]), pack_version)

    def ex(doc_id: str, field_name: str) -> TracedValue | None:
        entry = extractions.get(doc_id)
        if not entry:
            return None
        return _extracted(lineage, doc_id, entry["fields"], entry["confidence"],
                          field_name, prompt=entry["prompt"], model=entry["model"])

    documents = {d["doc_id"]: d for d in package["documents"]}
    docs_by_type: dict[str, list[dict]] = {}
    for doc in package["documents"]:
        docs_by_type.setdefault(doc["doc_type"], []).append(doc)

    # ---------------- income (specs/06 §2) --------------------------------
    components: list[income_mod.IncomeResult] = []
    component_rows: list[dict[str, Any]] = []
    variable_included_under_12mo = 0

    paystubs = docs_by_type.get("paystub", [])
    base_result = None
    if paystubs:
        doc_id = paystubs[0]["doc_id"]
        gross = ex(doc_id, "gross_pay_period")
        entry = extractions.get(doc_id, {})
        frequency = entry.get("fields", {}).get("pay_frequency", "semi_monthly")
        if gross:
            base_result = income_mod.monthly_base(
                lineage, gross_pay_period=gross, pay_frequency=frequency)
            components.append(base_result)
            component_rows.append({"type": "base", "monthly": base_result.monthly.value,
                                   "method": base_result.calc_method, "included": True})

    for other in borrower.get("stated_other_income", []):
        kind = other["type"]
        history = int(other["history_months"])
        if kind in ("bonus", "overtime", "commission"):
            annualized = money(D(other["monthly_amount"]) * 12 / D(str(constants["variable_income_short_history_haircut"])))
            result = income_mod.variable_income(
                lineage, income_type=kind,
                year1_total=None, year2_total=None,
                ytd_annualized=stated(f"income.{kind}.ytd_annualized", annualized)
                if history < int(constants["variable_income_full_history_months"]) else None,
                history_months=history,
                min_history_months=int(constants["variable_income_min_history_months"]),
                full_history_months=int(constants["variable_income_full_history_months"]),
                short_history_haircut=D(str(constants["variable_income_short_history_haircut"])),
            ) if history < int(constants["variable_income_full_history_months"]) else \
                income_mod.variable_income(
                    lineage, income_type=kind,
                    year1_total=stated(f"income.{kind}.y1", money(D(other["monthly_amount"]) * 12)),
                    year2_total=stated(f"income.{kind}.y2", money(D(other["monthly_amount"]) * 12)),
                    ytd_annualized=None, history_months=history,
                )
            components.append(result)
            component_rows.append({"type": kind, "monthly": result.monthly.value,
                                   "method": result.calc_method,
                                   "included": result.included})
            if result.included and history < 12:
                variable_included_under_12mo += 1
        elif kind == "rental":
            lease_docs = docs_by_type.get("lease", [])
            rent_tv = ex(lease_docs[0]["doc_id"], "monthly_rent") if lease_docs else None
            if rent_tv:
                result = income_mod.rental_income(
                    lineage, gross_monthly_rent=rent_tv,
                    factor=constant("rental_income_factor"))
                components.append(result)
                component_rows.append({"type": "rental", "monthly": result.monthly.value,
                                       "method": result.calc_method, "included": True})

    se_history_months: int | None = None
    if borrower.get("self_employed"):
        start = dt.date.fromisoformat(borrower["employment"][0]["start_date"])
        se_history_months = (as_of.year - start.year) * 12 + (as_of.month - start.month)
        sched_docs = sorted(docs_by_type.get("schedule_c", []),
                            key=lambda d: d.get("period_label", ""))
        if len(sched_docs) >= 2:
            def year_of(doc):
                doc_id = doc["doc_id"]
                return income_mod.ScheduleCYear(
                    net_profit=ex(doc_id, "net_profit"),
                    depreciation=ex(doc_id, "depreciation"),
                )
            result = income_mod.self_employed_income(
                lineage, year1=year_of(sched_docs[0]), year2=year_of(sched_docs[1]),
                history_months=se_history_months,
                min_history_months=int(constants["se_min_history_months"]),
            )
            components.append(result)
            component_rows.append({"type": "self_employed",
                                   "monthly": result.monthly.value,
                                   "method": result.calc_method,
                                   "included": result.included})
            if result.declining:
                red_flags.append(RedFlag(
                    "RF-INC-DECLINING", "info",
                    "Year-over-year self-employment income decline exceeds 20%",
                    result.monthly.lineage_ref, "review income trend"))

    qualifying = income_mod.total_qualifying_income(lineage, components)

    # stated-vs-documented income check (specs/06 §7 row 1)
    stated_base = D(borrower["employment"][0]["monthly_base_income_stated"])
    if base_result is not None and stated_base > 0:
        documented = D(base_result.monthly.value)
        tolerance = D(str(constants["income_paystub_w2_tolerance_pct"]))
        exceeded = abs(documented - stated_base) > stated_base * tolerance
        discrepancies.append(Discrepancy(
            "income.base_monthly", str(stated_base), str(documented),
            f"±{tolerance * 100}%", exceeded, base_result.monthly.lineage_ref))

    # W-2 vs 1040 (row 2) -> RF-INC-MISMATCH only when VOE unverified (06 §9)
    voe_result = adapter_results["voe"].result.get("result", "unavailable")
    w2_docs, t1040_docs = docs_by_type.get("w2", []), docs_by_type.get("tax_return_1040", [])
    if w2_docs and t1040_docs:
        w2_wages = ex(w2_docs[0]["doc_id"], "wages_box1")
        t_wages = ex(t1040_docs[0]["doc_id"], "wages")
        if w2_wages and t_wages and D(t_wages.value) > 0:
            tolerance = D(str(constants["income_w2_1040_tolerance_pct"]))
            exceeded = abs(D(w2_wages.value) - D(t_wages.value)) > D(t_wages.value) * tolerance
            discrepancies.append(Discrepancy(
                "income.w2_vs_1040", t_wages.value, w2_wages.value,
                f"±{tolerance * 100}%", exceeded, w2_wages.lineage_ref))
            if exceeded and voe_result != "verified":
                red_flags.append(RedFlag(
                    "RF-INC-MISMATCH", "critical",
                    "W-2/tax-return wage variance above 5% with unverified employment",
                    w2_wages.lineage_ref, "suspend"))

    income_discrepancies_exceeded = sum(
        1 for d in discrepancies if d.field.startswith("income.") and d.exceeded)

    # ---------------- housing expense & DTI (specs/06 §3–§4) --------------
    loan_amount = stated("loan.amount", loan["amount"])
    appraisals = docs_by_type.get("appraisal", [])
    appraised = (ex(appraisals[0]["doc_id"], "appraised_value")
                 if appraisals else stated("property.appraised_value",
                                           prop["appraised_value"]))
    purchase_price = (stated("property.purchase_price", prop["purchase_price"])
                      if prop.get("purchase_price") else None)
    basis = ltv_mod.value_basis(
        lineage, purpose=loan["purpose"], purchase_price=purchase_price,
        appraised_value=appraised)
    ltv_tv = ltv_mod.ltv(lineage, loan_amount=loan_amount, basis=basis)
    subordinate = [stated(f"lien.{i}", l["balance"])
                   for i, l in enumerate(prop.get("subordinate_liens", []))]
    cltv_tv = ltv_mod.cltv(lineage, loan_amount=loan_amount,
                           subordinate_balances=subordinate, basis=basis)

    pi_tv = dti_mod.principal_interest(
        lineage, loan_amount=loan_amount,
        note_rate_pct=stated("loan.note_rate", loan["note_rate"]),
        term_months=int(loan["term_months"]))
    mi_tv = dti_mod.monthly_mi(
        lineage, loan_amount=loan_amount, ltv=ltv_tv,
        mi_annual_rate=constant("mi_annual_rate"))
    taxes_tv = lineage.add("calculation", "pitia.taxes",
                           str(money(D(prop["annual_taxes"]) / 12)),
                           parents=(stated("property.annual_taxes",
                                           prop["annual_taxes"]).lineage_ref,),
                           method="annual_over_12")
    hazard_tv = lineage.add("calculation", "pitia.hazard",
                            str(money(D(prop["annual_hazard_insurance"]) / 12)),
                            parents=(stated("property.annual_hazard",
                                            prop["annual_hazard_insurance"]).lineage_ref,),
                            method="annual_over_12")
    pitia_result = dti_mod.pitia(
        lineage, principal_interest_tv=pi_tv, monthly_taxes=taxes_tv,
        monthly_hazard=hazard_tv, mi=mi_tv,
        monthly_hoa=stated("property.monthly_hoa", prop["monthly_hoa"]))

    tradelines = [
        (stated(f"tradeline.{i}", t["monthly_payment"]), t.get("payments_remaining"))
        for i, t in enumerate(package["credit"]["tradelines"])
    ]
    liabilities_tv = dti_mod.monthly_liabilities(
        lineage, tradeline_payments=tradelines, court_ordered=[],
        exclusion_max_payments_remaining=int(
            constants["installment_exclusion_max_payments_remaining"]))
    ratios = dti_mod.dti_ratios(
        lineage, pitia_total=pitia_result.total,
        monthly_liabilities=liabilities_tv, qualifying_income=qualifying)

    # processor DTI cross-check (specs/06 §7 row 5 — informational)
    processor_back = D(package["processor_computed"]["back_dti"])
    recomputed_back = D(ratios.back_ratio.value)
    processor_tolerance = D(str(constants["processor_dti_tolerance_pp"]))
    discrepancies.append(Discrepancy(
        "dti.back_ratio", str(processor_back), str(recomputed_back),
        f"±{processor_tolerance}pp",
        abs(recomputed_back - processor_back) > processor_tolerance,
        ratios.back_ratio.lineage_ref))

    # ---------------- credit (specs/06 §6) --------------------------------
    credit = package["credit"]
    borrower_reps = []
    for entry in credit["scores"]:
        scores = [(bureau, stated(f"score.{entry['borrower_id']}.{bureau}",
                                  entry[bureau]))
                  for bureau in ("equifax", "experian", "transunion")
                  if bureau in entry]
        borrower_reps.append(score_mod.borrower_representative(
            lineage, borrower_id=entry["borrower_id"], scores=scores))
    rep_tv = score_mod.loan_representative(lineage, borrower_reps=borrower_reps)

    derogs = {d["kind"]: d["months_since"] for d in credit.get("derogatories", [])}
    late_mortgage = sum(t.get("late_30_count_12mo", 0)
                        for t in credit["tradelines"] if t["kind"] == "mortgage")
    report_age = (as_of - dt.date.fromisoformat(credit["report_date"])).days
    appraisal_age = (as_of - dt.date.fromisoformat(
        prop["appraisal_effective_date"])).days

    # ---------------- assets (specs/06 §5) --------------------------------
    assets = package["assets"]
    liquid_total = money(sum((D(a["balance"]) for a in assets["accounts"]), D("0")))
    liquid_tv = stated("assets.liquid_total", liquid_total)
    retirement_total = money(sum(
        (D(r["vested_balance"]) for r in assets.get("retirement_accounts", [])),
        D("0")))
    down_payment = (money(D(prop["purchase_price"]) - D(loan["amount"]))
                    if loan["purpose"] == "purchase" and prop.get("purchase_price")
                    else D("0.00"))
    ftc_tv = reserves_mod.funds_to_close(
        lineage, down_payment=stated("assets.down_payment", down_payment),
        cost_basis=stated("assets.cost_basis",
                          prop.get("purchase_price") or loan["amount"]),
        closing_cost_rate=constant("estimated_closing_cost_rate"))
    reserves_result = reserves_mod.reserves(
        lineage, liquid_total=liquid_tv,
        retirement_vested_total=stated("assets.retirement_total", retirement_total),
        retirement_haircut=constant("retirement_asset_haircut"),
        funds_to_close_tv=ftc_tv, pitia_total=pitia_result.total)

    # deposit analysis (specs/06 §5.1/§9)
    large_pct = D(str(constants["large_deposit_income_pct"]))
    seasoning_days = int(constants["asset_seasoning_days"])
    monthly_income_value = D(qualifying.value)
    unsourced_large, unseasoned_total = 0, D("0")
    round_amount = D(str(constants["deposit_pattern_round_amount"]))
    round_recent = 0
    payroll_markers = ("PAYROLL",)
    for doc in docs_by_type.get("bank_statement", []):
        entry = extractions.get(doc["doc_id"])
        if not entry:
            continue
        for deposit in entry["fields"].get("deposits", []):
            amount = D(str(deposit["amount"]))
            age = (as_of - dt.date.fromisoformat(deposit["date"])).days
            is_payroll = any(m in deposit.get("description", "").upper()
                             for m in payroll_markers)
            if is_payroll:
                continue
            if age < seasoning_days:
                unseasoned_total += amount
                if amount % round_amount == 0 and age <= int(
                        constants["deposit_pattern_window_days"]):
                    round_recent += 1
            if amount > monthly_income_value * large_pct and age < seasoning_days:
                unsourced_large += 1
                ref = lineage.add(
                    "extracted_field", f"{doc['doc_id']}.deposit.{deposit['date']}",
                    str(amount), source_id=doc["doc_id"],
                    meta={"prompt": entry["prompt"], "model": entry["model"]})
                red_flags.append(RedFlag(
                    "RF-DEP-UNSOURCED", "elevated",
                    f"Unsourced deposit of {amount} ({(amount / monthly_income_value * 100).quantize(D('0.1'))}% "
                    f"of monthly income), {age} days old",
                    ref.lineage_ref, "source the deposit"))
    if round_recent >= int(constants["deposit_pattern_count"]):
        red_flags.append(RedFlag(
            "RF-DEP-PATTERN", "elevated",
            f"{round_recent} round-amount deposits within "
            f"{constants['deposit_pattern_window_days']} days",
            reserves_result.months.lineage_ref, "review deposit pattern"))

    unseasoned_flag = reserves_mod.unseasoned_funds_flag(
        lineage, liquid_total=liquid_tv,
        unseasoned_unsourced_deposit_total=stated(
            "assets.unseasoned_total", money(unseasoned_total)),
        funds_to_close_tv=ftc_tv)

    # ---------------- fraud screen (specs/06 §9) ---------------------------
    geo = adapter_results["geo"].result
    if (loan["occupancy"] == "primary"
            and int(geo.get("miles") or 0) > int(constants["occupancy_distance_miles_flag"])):
        red_flags.append(RedFlag(
            "RF-OCC-DISTANCE", "elevated",
            f"Primary-occupancy claim with employer {geo['miles']} miles away",
            lineage.add("adapter_result", "geo.miles", str(geo["miles"]),
                        source_id=adapter_results["geo"].adapter_name).lineage_ref,
            "verify occupancy intent"))
    if (loan["occupancy"] == "primary"
            and prop.get("hazard_policy_type") == "landlord_rental"):
        red_flags.append(RedFlag(
            "RF-OCC-INSURANCE", "critical",
            "Hazard policy is landlord/rental while occupancy is primary",
            stated("property.hazard_policy_type",
                   prop["hazard_policy_type"]).lineage_ref,
            "suspend"))
    stated_liab_total = D(package["liabilities_stated_monthly_total"])
    if D(liabilities_tv.value) - stated_liab_total > D(
            str(constants["undisclosed_liability_tolerance"])):
        red_flags.append(RedFlag(
            "RF-LIAB-UNDISCLOSED", "elevated",
            "Credit-report obligations exceed stated liabilities beyond tolerance",
            liabilities_tv.lineage_ref, "reconcile liabilities"))
    if report_age > int(constants["document_staleness_days"]) or \
            appraisal_age > int(constants["document_staleness_days"]):
        red_flags.append(RedFlag(
            "RF-DOC-STALE", "info", "Credit report or appraisal exceeds 120 days",
            rep_tv.lineage_ref, "refresh documentation"))

    # ---------------- compensating factors (specs/07 §7.6) ----------------
    residual = money(monthly_income_value - D(pitia_result.total.value)
                     - D(liabilities_tv.value))
    residual_tv = lineage.add(
        "calculation", "income.residual_monthly", str(residual),
        parents=(qualifying.lineage_ref, pitia_result.total.lineage_ref,
                 liabilities_tv.lineage_ref),
        method="income_minus_pitia_minus_debts")
    factor_context: Context = {
        "credit.representative_score": (int(rep_tv.value), rep_tv.lineage_ref),
        "assets.reserves_months": (D(reserves_result.months.value),
                                   reserves_result.months.lineage_ref),
        "ltv.ltv": (D(ltv_tv.value), ltv_tv.lineage_ref),
        "income.residual_monthly": (residual, residual_tv.lineage_ref),
    }
    from app.policy_engine.ast import Evaluator, MissingInput
    satisfied = []
    for factor in compensating_factors:
        try:
            if Evaluator(factor_context).evaluate(factor["when"]):
                satisfied.append(factor["id"])
        except MissingInput:
            pass

    # ---------------- state derivations (specs/17 §4) ----------------------
    state = prop["address"]["state"]
    flags = {
        "community_property": state in states_index["community_property"],
        "wet_funding": state not in states_index["dry_funding"],
        "attorney_closing": state in states_index["attorney_closing"],
        "disparate_impact_monitoring": state in states_index[
            "disparate_impact_monitoring"],
    }
    apr = D(loan.get("apr") or "0")
    treasury = D(str(reference_indices["treasury_comparable_maturity"]))
    pmms = D(str(reference_indices["pmms_northeast"]))
    apor = D(str(reference_indices["apor_30yr_fixed"]))
    points_fees_pct = (
        ratio_pct(D(loan["total_points_and_fees"]) / D(loan["amount"]) * HUNDRED)
        if loan.get("total_points_and_fees") else None)
    lender_fees_pct = (
        ratio_pct(D(loan["lender_controlled_fees"]) / D(loan["amount"]) * HUNDRED)
        if loan.get("lender_controlled_fees") else None)
    prior_a6_days = None
    if prop.get("prior_home_equity_loan_date"):
        prior_a6_days = (as_of - dt.date.fromisoformat(
            prop["prior_home_equity_loan_date"])).days
    nbs_present = any(b.get("non_borrowing_spouse") for b in package["borrowers"])

    # ---------------- ATR (specs/06 §8) ------------------------------------
    voe_ref = lineage.add("adapter_result", "voe.result", voe_result,
                          source_id=adapter_results["voe"].adapter_name)
    atr = build_atr_evaluations(
        income_ref=qualifying.lineage_ref,
        employment_refs=[voe_ref.lineage_ref] if voe_result == "verified" else [],
        principal_interest_ref=pi_tv.lineage_ref,
        simultaneous_ref=cltv_tv.lineage_ref,
        pitia_components_ref=pitia_result.total.lineage_ref,
        liabilities_ref=liabilities_tv.lineage_ref,
        back_ratio_ref=ratios.back_ratio.lineage_ref,
        credit_ref=rep_tv.lineage_ref,
    )

    # ---------------- evaluation context (specs/07 §3 + 17 §4) -------------
    def put(context: Context, key: str, value: Any, ref: str | None) -> None:
        context[key] = (value, ref)

    context: Context = {}
    put(context, "loan.amount", D(loan["amount"]), loan_amount.lineage_ref)
    put(context, "loan.purpose", loan["purpose"], None)
    put(context, "loan.occupancy", loan["occupancy"], None)
    put(context, "loan.units", int(prop["units"]), None)
    put(context, "loan.county_high_cost", bool(loan["county_high_cost"]), None)
    put(context, "loan.is_cash_out", loan["purpose"] == "cash_out_refi", None)
    if loan.get("apr"):
        put(context, "loan.apr", apr, None)
    if points_fees_pct is not None:
        put(context, "loan.points_and_fees_pct", points_fees_pct, None)
    if lender_fees_pct is not None:
        put(context, "loan.lender_fees_pct", lender_fees_pct, None)
    put(context, "ltv.ltv", D(ltv_tv.value), ltv_tv.lineage_ref)
    put(context, "ltv.cltv", D(cltv_tv.value), cltv_tv.lineage_ref)
    put(context, "dti.front_ratio", D(ratios.front_ratio.value),
        ratios.front_ratio.lineage_ref)
    put(context, "dti.back_ratio", D(ratios.back_ratio.value),
        ratios.back_ratio.lineage_ref)
    put(context, "income.qualifying_monthly", monthly_income_value,
        qualifying.lineage_ref)
    put(context, "income.residual_monthly", residual, residual_tv.lineage_ref)
    put(context, "income.variable_included_under_12mo",
        variable_included_under_12mo, None)
    put(context, "income.discrepancies_exceeded", income_discrepancies_exceeded, None)
    if se_history_months is not None:
        put(context, "income.se_history_months", se_history_months, None)
    put(context, "credit.representative_score", int(rep_tv.value), rep_tv.lineage_ref)
    put(context, "credit.open_disputes", int(credit["open_disputes"]), None)
    if "bk7_discharge" in derogs:
        put(context, "credit.bk7_months_since", derogs["bk7_discharge"], None)
    if "foreclosure" in derogs:
        put(context, "credit.fc_months_since", derogs["foreclosure"], None)
    put(context, "credit.late_mortgage_12mo", late_mortgage, None)
    put(context, "credit.report_age_days", report_age, None)
    put(context, "assets.reserves_months", D(reserves_result.months.value),
        reserves_result.months.lineage_ref)
    put(context, "assets.unsourced_large_deposits", unsourced_large, None)
    put(context, "assets.unseasoned_funds", int(unseasoned_flag.value),
        unseasoned_flag.lineage_ref)
    put(context, "assets.gift_funds_undocumented",
        sum(1 for g in assets.get("gift_funds", [])
            if not g.get("transfer_evidenced")), None)
    put(context, "compensating.count", len(satisfied), None)
    put(context, "property.type", prop["property_type"], None)
    put(context, "property.state", state, None)
    put(context, "property.homestead", loan["occupancy"] == "primary", None)
    put(context, "appraisal.age_days", appraisal_age, None)
    for flag_name, flag_value in flags.items():
        put(context, f"state.flags.{flag_name}", flag_value, None)
    put(context, "state.apr_spread_treasury",
        ratio_pct(apr - treasury) if loan.get("apr") else D("0"), None)
    put(context, "state.rate_spread_pmms",
        ratio_pct(D(loan["note_rate"]) - pmms), None)
    put(context, "apor.spread", ratio_pct(apr - apor) if loan.get("apr") else D("0"), None)
    put(context, "state.subordinate_lien_count",
        len(prop.get("subordinate_liens", [])), None)
    if prior_a6_days is not None:
        put(context, "state.prior_a6_days", prior_a6_days, None)
    put(context, "state.tx_notice_on_file",
        bool(prop.get("tx_a6_notice_date")), None)
    put(context, "borrowers.non_borrowing_spouse_present", nbs_present, None)

    four_cs = {
        "credit": {"representative_score": int(rep_tv.value),
                   "representative_score_ref": rep_tv.lineage_ref,
                   "open_disputes": int(credit["open_disputes"]),
                   "flags": [f.flag_code for f in red_flags]},
        "capacity": {"front_ratio": ratios.front_ratio.value,
                     "front_ratio_ref": ratios.front_ratio.lineage_ref,
                     "back_ratio": ratios.back_ratio.value,
                     "back_ratio_ref": ratios.back_ratio.lineage_ref,
                     "qualifying_income_monthly": qualifying.value,
                     "qualifying_income_ref": qualifying.lineage_ref,
                     "pitia": {
                         "total": pitia_result.total.value,
                         "principal_interest": pi_tv.value,
                         "taxes": taxes_tv.value, "hazard": hazard_tv.value,
                         "mi": mi_tv.value, "hoa": prop["monthly_hoa"],
                         "total_ref": pitia_result.total.lineage_ref}},
        "capital": {"reserves_months": reserves_result.months.value,
                    "reserves_ref": reserves_result.months.lineage_ref,
                    "unsourced_deposits": unsourced_large,
                    "funds_to_close": ftc_tv.value},
        "collateral": {"ltv": ltv_tv.value, "ltv_ref": ltv_tv.lineage_ref,
                       "cltv": cltv_tv.value, "cltv_ref": cltv_tv.lineage_ref,
                       "appraised_value": appraised.value},
    }
    computed = {
        "income_components": component_rows,
        "dti": {"front": ratios.front_ratio.value, "back": ratios.back_ratio.value,
                "pitia": pitia_result.total.value,
                "liabilities": liabilities_tv.value},
        "ltv": {"ltv": ltv_tv.value, "cltv": cltv_tv.value},
        "reserves": {"months": reserves_result.months.value,
                     "post_closing": reserves_result.post_closing_available.value},
        "representative_score": int(rep_tv.value),
        "compensating_factors": satisfied,
        "atr": [{"factor_number": a.factor_number, "factor_name": a.factor_name,
                 "basis": a.basis, "evidence_ref": a.evidence_ref} for a in atr],
        "red_flags": [f.__dict__ for f in red_flags],
        "discrepancies": [d.__dict__ for d in discrepancies],
    }
    return AssembledCase(
        application_id=application_id, lineage=lineage, context=context,
        four_cs=four_cs, atr=atr, discrepancies=discrepancies,
        red_flags=red_flags, income_components=component_rows, computed=computed,
    )


__all__ = ["assemble_case", "AssembledCase", "Discrepancy", "RedFlag", "Context"]
