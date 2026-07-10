"""Decision-side pure helpers (specs/09 §3.8–§3.12, §5):
conditions synthesis, suggested action, decision packet, resume
validation (FR-DEC-2/3/4/7), adverse-action notice (FR-AAN-1/2, HR-10),
HMDA action-taken mapping (FR-HMD-1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.agent.assembly import AssembledCase
from app.aus.du_simulator import AusFindings
from app.policy_engine.result import RulesResult

VALID_ACTIONS = ("approve_with_conditions", "suspend", "decline", "counteroffer")


# --------------------------------------------------------------- conditions
@dataclass(frozen=True)
class Condition:
    id: str
    category: str            # PTA | PTD | PTF
    title: str
    text: str
    source_kind: str         # rule | aus_message | discrepancy | red_flag | state_rule
    source_id: str
    drafted_by_llm: bool = False


def synthesize_conditions(
    case: AssembledCase, rules: RulesResult, aus: AusFindings,
) -> list[Condition]:
    """specs/09 §3.8 — sources: documentation rule failures + artifacts,
    AUS messages, exceeded discrepancies, red flags. Dedup by (source_kind,
    source_id) (FR-CND-3)."""
    conditions: list[Condition] = []
    seen: set[tuple[str, str]] = set()

    def add(condition: Condition) -> None:
        key = (condition.source_kind, condition.source_id)
        if key not in seen:
            seen.add(key)
            conditions.append(condition)

    for artifact in rules.artifacts:  # incl. state artifacts (specs/17 §6)
        source_kind = ("state_rule" if artifact.rule_id.startswith("S")
                       else "rule")
        add(Condition(
            id=f"cond-{artifact.id.lower()}", category=artifact.category,
            title=artifact.id.replace("-", " ").title(),
            text=artifact.text_template, source_kind=source_kind,
            source_id=artifact.rule_id))

    for evaluation in rules.evaluations:
        if evaluation.severity == "documentation" and evaluation.outcome == "refer":
            add(Condition(
                id=f"cond-{evaluation.rule_id.lower()}", category="PTA",
                title=f"Resolve {evaluation.rule_id}",
                text=evaluation.description, source_kind="rule",
                source_id=evaluation.rule_id))

    for message in aus.messages:
        add(Condition(
            id=f"cond-{message.message_id.lower()}", category=message.category,
            title=message.message_id, text=message.text,
            source_kind="aus_message", source_id=message.message_id))

    for discrepancy in case.discrepancies:
        if discrepancy.exceeded:
            add(Condition(
                id=f"cond-disc-{discrepancy.field.replace('.', '-')}",
                category="PTA", title=f"Reconcile {discrepancy.field}",
                text=(f"Documented {discrepancy.field} of "
                      f"{discrepancy.documented_value} differs from stated "
                      f"{discrepancy.stated_value} beyond {discrepancy.tolerance}."),
                source_kind="discrepancy", source_id=discrepancy.field))

    for flag in case.red_flags:
        if flag.severity in ("elevated", "critical"):
            add(Condition(
                id=f"cond-{flag.flag_code.lower()}", category="PTA",
                title=flag.flag_code, text=flag.description,
                source_kind="red_flag", source_id=flag.flag_code))

    return conditions


# --------------------------------------------------------------- suggestion
def suggested_action(case: AssembledCase, rules: RulesResult,
                     voe_result: str) -> str:
    """specs/09 §3.9 — first matching row."""
    if any(f.severity == "critical" for f in case.red_flags):
        return "suspend"
    if rules.overall == "ineligible":
        return "decline"
    if rules.overall == "refer":
        return "suspend"
    if any(f.severity == "elevated" for f in case.red_flags) or \
            voe_result != "verified":
        return "suspend"
    return "approve_with_conditions"


# --------------------------------------------------------------- packet
def build_decision_packet(
    *, application_id: str, case: AssembledCase, rules: RulesResult,
    aus: AusFindings, conditions: list[Condition], suggested: str,
    four_eyes_threshold: Decimal, loan_amount: Decimal,
    validation_errors: list[str] | None = None,
) -> dict[str, Any]:
    messages_by_category: dict[str, list[dict]] = {"PTA": [], "PTD": [], "PTF": []}
    for message in aus.messages:
        messages_by_category[message.category].append(
            {"message_id": message.message_id, "text": message.text})
    failed = [
        {"rule_id": e.rule_id, "reason_code": e.reason_code or "",
         "description": e.description,
         "citation": e.citation,
         "inputs": [{"path": i.path, "value": i.value,
                     "lineage_ref": i.lineage_ref} for i in e.inputs]}
        for e in rules.evaluations if e.outcome in ("fail", "refer")
    ]
    return {
        "application_id": application_id,
        "suggested_action": suggested,
        "four_cs": case.four_cs,
        "rules": {"overall": rules.overall, "failed": failed},
        "eligible_reason_codes": list(rules.eligible_reason_codes),
        "aus": {"recommendation": aus.recommendation,
                "messages_by_category": messages_by_category},
        "red_flags": [f.__dict__ for f in case.red_flags],
        "conditions": [c.__dict__ for c in conditions],
        "counteroffer_hints": [
            {"rule_id": h.rule_id, "parameter": h.parameter,
             "max_value": h.max_value, "achieved_ratio": h.achieved_ratio}
            for h in rules.counteroffer_hints],
        "four_eyes_required": loan_amount >= four_eyes_threshold,
        "atr_complete": len(case.atr) == 8,
        "validation_errors": validation_errors or [],
    }


# --------------------------------------------------------------- resume gate
@dataclass(frozen=True)
class GateDecision:
    action: str
    underwriter_id: str
    second_reviewer_id: str | None
    reason_codes: tuple[str, ...]
    justification: str | None
    notes: str | None            # underwriter rationale on ANY action
    condition_edits: tuple[dict, ...]
    counteroffer_terms: dict | None
    is_override: bool


def validate_resume(
    resume: dict[str, Any], packet: dict[str, Any],
) -> tuple[GateDecision | None, list[str]]:
    """FR-DEC-2/3/4/7 — invalid resumes re-present the gate with errors."""
    errors: list[str] = []
    action = resume.get("action")
    if action not in VALID_ACTIONS:
        errors.append(f"action must be one of {VALID_ACTIONS}")
    underwriter = (resume.get("underwriter_id") or "").strip()
    if not underwriter:
        errors.append("underwriter_id is required")

    reason_codes = tuple(resume.get("reason_codes") or ())
    second = (resume.get("second_reviewer_id") or "").strip() or None
    justification = (resume.get("justification") or "").strip() or None
    counteroffer_terms = resume.get("counteroffer_terms")

    if action == "decline":
        eligible = set(packet["eligible_reason_codes"])
        if not 1 <= len(reason_codes) <= 4:
            errors.append("decline requires 1-4 reason codes (FR-DEC-2)")
        if not set(reason_codes) <= eligible:
            errors.append("reason codes must be bound to actually-failed rules")
        if not second:
            errors.append("decline requires a second reviewer (four-eyes)")
    if action == "counteroffer" and not (
            counteroffer_terms and counteroffer_terms.get("loan_amount")):
        errors.append("counteroffer requires counteroffer_terms.loan_amount")

    is_override = bool(action) and action != packet["suggested_action"]
    if is_override and (not justification or len(justification) < 20):
        errors.append("override requires a justification of at least 20 characters (FR-DEC-3)")
    if packet.get("four_eyes_required") and not second:
        errors.append("second reviewer required for this loan amount (FR-DEC-4)")
    if second and second == underwriter:
        errors.append("second reviewer must differ from the deciding underwriter")

    if errors:
        return None, errors
    return GateDecision(
        action=action, underwriter_id=underwriter, second_reviewer_id=second,
        reason_codes=reason_codes, justification=justification,
        notes=(resume.get("notes") or "").strip() or None,
        condition_edits=tuple(resume.get("condition_edits") or ()),
        counteroffer_terms=counteroffer_terms, is_override=is_override,
    ), []


# --------------------------------------------------------------- adverse action
ECOA_STATEMENT = (
    "NOTICE: The federal Equal Credit Opportunity Act prohibits creditors "
    "from discriminating against credit applicants on the basis of race, "
    "color, religion, national origin, sex, marital status, age (provided "
    "the applicant has the capacity to enter into a binding contract); "
    "because all or part of the applicant's income derives from any public "
    "assistance program; or because the applicant has in good faith "
    "exercised any right under the Consumer Credit Protection Act."
)


def build_adverse_action_notice(
    *, reason_codes: tuple[str, ...], reason_bindings: dict[str, dict],
    credit: dict[str, Any], states_index: dict, property_state: str,
) -> dict[str, Any]:
    """FR-AAN-1/2 (HR-10): principal reasons are EXACTLY the selected
    codes' ecoa_text strings; FCRA §609(g) block; CO/CA ADMT artifacts
    appended per states-index (FR-STA-7, specs/17 §7.3). No LLM here."""
    principal_reasons = [
        {"reason_code": code,
         "ecoa_text": reason_bindings[code]["ecoa_text"],
         "hmda_code": reason_bindings[code]["hmda_denial_code"]}
        for code in reason_codes
    ]
    scores = credit["scores"][0]
    bureau_scores = {b: scores[b] for b in ("equifax", "experian", "transunion")
                     if b in scores}
    fcra_block = {
        "score": sorted(bureau_scores.values())[len(bureau_scores) // 2]
        if len(bureau_scores) == 3 else min(bureau_scores.values()),
        "range_low": credit["score_range"]["low"],
        "range_high": credit["score_range"]["high"],
        "score_date": credit["report_date"],
        "key_factors": credit["key_factors"][:4],
        "bureaus": sorted(bureau_scores),
    }
    admt = (states_index.get("admt_adverse_artifact") or {}).get(property_state)
    admt_block = None
    if admt:
        admt_block = {"citation": admt["citation"], "duties": admt["duties"],
                      "provenance_source": "GET /loans/{id}/decision"}
    body_lines = [
        "STATEMENT OF CREDIT DENIAL", "",
        "Principal reason(s) for this action:",
        *[f"  - {r['ecoa_text']}" for r in principal_reasons],
        "",
        f"Credit score: {fcra_block['score']} "
        f"(range {fcra_block['range_low']}-{fcra_block['range_high']}, "
        f"as of {fcra_block['score_date']})",
        "Key factors adversely affecting the score:",
        *[f"  - {factor}" for factor in fcra_block["key_factors"]],
        "",
        ECOA_STATEMENT,
    ]
    if admt_block:
        body_lines += ["", f"Automated decision-making disclosure ({admt_block['citation']}):",
                       *[f"  - {duty}" for duty in admt_block["duties"]]]
    return {
        "principal_reasons": principal_reasons,
        "fcra_block": fcra_block,
        "admt_block": admt_block,
        "body_text": "\n".join(body_lines),
    }


# --------------------------------------------------------------- HMDA
def hmda_action_taken(action: str) -> int | None:
    """specs/04 §5 mapping."""
    return {
        "approve_with_conditions": 1,
        "counteroffer": 3,   # unaccepted counteroffer reports as denial
        "decline": 3,
        "suspend": None,     # pending
    }[action]


__all__ = [
    "Condition", "synthesize_conditions", "suggested_action",
    "build_decision_packet", "GateDecision", "validate_resume",
    "build_adverse_action_notice", "hmda_action_taken", "VALID_ACTIONS",
]
