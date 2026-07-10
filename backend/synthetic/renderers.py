"""Document text renderers (specs/14 §1). Every number the extractor must
find appears verbatim in the text; ground_truth mirrors it exactly
(mock-provider contract, FR-EXT-4). Amounts render with thousands
separators in the text for extraction realism; ground_truth stays plain.
"""

from __future__ import annotations

from decimal import Decimal


def fmt(amount: str) -> str:
    return f"{Decimal(amount):,.2f}"


def paystub(*, employer: str, borrower: str, gross: str, frequency: str,
            ytd: str, pay_date: str) -> tuple[str, dict]:
    freq_label = {"semi_monthly": "Semi-Monthly", "biweekly": "Bi-Weekly",
                  "weekly": "Weekly", "monthly": "Monthly"}[frequency]
    text = (
        f"{employer.upper()} — EARNINGS STATEMENT\n"
        f"Employee: {borrower}    Pay Date: {pay_date}\n"
        f"Pay Frequency: {freq_label}\n"
        f"----------------------------------------\n"
        f"  Gross Pay (this period):   ${fmt(gross)}\n"
        f"  YTD Gross:                 ${fmt(ytd)}\n"
        f"----------------------------------------\n"
        f"Direct deposit to account on file.\n"
    )
    truth = {"gross_pay_period": gross, "pay_frequency": frequency,
             "ytd_gross": ytd, "employer": employer, "pay_date": pay_date}
    return text, truth


def w2(*, employer: str, borrower: str, wages: str, tax_year: int) -> tuple[str, dict]:
    text = (
        f"FORM W-2 — WAGE AND TAX STATEMENT — {tax_year}\n"
        f"Employer: {employer}\nEmployee: {borrower}\n"
        f"Box 1 Wages, tips, other compensation: ${fmt(wages)}\n"
    )
    return text, {"wages_box1": wages, "employer": employer, "tax_year": tax_year}


def tax_return_1040(*, borrower: str, wages: str, agi: str, tax_year: int,
                    schedule_c: bool) -> tuple[str, dict]:
    text = (
        f"FORM 1040 — U.S. INDIVIDUAL INCOME TAX RETURN — {tax_year}\n"
        f"Taxpayer: {borrower}\n"
        f"Line 1a Wages: ${fmt(wages)}\n"
        f"Adjusted Gross Income: ${fmt(agi)}\n"
        f"{'Schedule C attached.' if schedule_c else 'No schedules attached.'}\n"
    )
    return text, {"wages": wages, "agi": agi, "tax_year": tax_year,
                  "schedule_c_attached": schedule_c}


def schedule_c(*, borrower: str, net_profit: str, depreciation: str,
               tax_year: int) -> tuple[str, dict]:
    text = (
        f"SCHEDULE C — PROFIT OR LOSS FROM BUSINESS — {tax_year}\n"
        f"Proprietor: {borrower}\n"
        f"Line 13 Depreciation: ${fmt(depreciation)}\n"
        f"Line 31 Net profit: ${fmt(net_profit)}\n"
    )
    return text, {"net_profit": net_profit, "depreciation": depreciation,
                  "tax_year": tax_year}


def bank_statement(*, bank: str, account_last4: str, period_start: str,
                   period_end: str, ending_balance: str,
                   deposits: list[dict]) -> tuple[str, dict]:
    lines = "\n".join(
        f"  {d['date']}  DEPOSIT {d['description']:<28} ${fmt(d['amount'])}"
        for d in deposits
    )
    text = (
        f"{bank.upper()} — ACCOUNT STATEMENT (...{account_last4})\n"
        f"Statement Period: {period_start} through {period_end}\n"
        f"DEPOSITS AND CREDITS\n{lines}\n"
        f"ENDING BALANCE: ${fmt(ending_balance)}\n"
    )
    truth = {"ending_balance": ending_balance, "period_start": period_start,
             "period_end": period_end,
             "deposits": [{"amount": d["amount"], "date": d["date"],
                           "description": d["description"]} for d in deposits]}
    return text, truth


def appraisal(*, address: str, value: str, effective_date: str,
              property_type: str, hazard_hint: str) -> tuple[str, dict]:
    text = (
        f"UNIFORM RESIDENTIAL APPRAISAL REPORT\n"
        f"Subject Property: {address}\n"
        f"Property Type: {property_type}\n"
        f"Opinion of Market Value: ${fmt(value)}\n"
        f"Effective Date of Appraisal: {effective_date}\n"
        f"Condition Rating: C3\n"
        f"Remarks: {hazard_hint}\n"
    )
    return text, {"appraised_value": value, "effective_date": effective_date,
                  "property_type": property_type, "condition_rating": "C3",
                  "hazard_policy_type_hint": hazard_hint}


def urla_1003(*, borrower: str, stated_income: str, stated_liabilities: str,
              employers: list[str], occupancy_primary: bool) -> tuple[str, dict]:
    text = (
        f"UNIFORM RESIDENTIAL LOAN APPLICATION (FORM 1003)\n"
        f"Borrower: {borrower}\n"
        f"Employers: {', '.join(employers)}\n"
        f"Total Monthly Income: ${fmt(stated_income)}\n"
        f"Total Monthly Liabilities: ${fmt(stated_liabilities)}\n"
        f"Declarations: [X] No outstanding judgments  [X] No bankruptcy (7yr)\n"
        f"[X] No foreclosure (7yr)  [{'X' if occupancy_primary else ' '}] "
        f"Will occupy as primary residence\n"
        f"[X] No undisclosed borrowed funds\n"
    )
    truth = {
        "declarations": {
            "outstanding_judgments": False, "bankruptcy_7yr": False,
            "foreclosure_7yr": False, "party_to_lawsuit": False,
            "delinquent_federal_debt": False,
            "occupancy_intent_primary": occupancy_primary,
            "undisclosed_borrowed_funds": False,
        },
        "stated_income_monthly": stated_income,
        "stated_liabilities_monthly": stated_liabilities,
        "employer_names": employers,
    }
    return text, truth


def gift_letter(*, donor: str, amount: str, relationship: str) -> tuple[str, dict]:
    text = (
        f"GIFT LETTER\n"
        f"I, {donor} ({relationship} of the borrower), certify a gift of "
        f"${fmt(amount)}.\nNo repayment is expected or implied.\n"
    )
    return text, {"donor": donor, "amount": amount, "relationship": relationship,
                  "no_repayment_clause": True}


def lease(*, tenant: str, monthly_rent: str, term_months: int,
          start_date: str) -> tuple[str, dict]:
    text = (
        f"RESIDENTIAL LEASE AGREEMENT\n"
        f"Tenant: {tenant}\nMonthly Rent: ${fmt(monthly_rent)}\n"
        f"Term: {term_months} months beginning {start_date}\n"
    )
    return text, {"monthly_rent": monthly_rent, "term_months": term_months,
                  "tenant": tenant, "start_date": start_date}


def tri_merge_stub(*, report_date: str, rep_score: int) -> tuple[str, dict]:
    # Structured credit data lives in the package credit block; this document
    # is a pass-through (extraction skips it — specs/09 §3.2).
    text = (
        f"TRI-MERGE CREDIT REPORT — {report_date}\n"
        f"Representative score data delivered in structured feed.\n"
        f"Reference score: {rep_score}\n"
    )
    return text, {}


__all__ = [
    "paystub", "w2", "tax_return_1040", "schedule_c", "bank_statement",
    "appraisal", "urla_1003", "gift_letter", "lease", "tri_merge_stub", "fmt",
]
