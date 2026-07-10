"""Underwriting run orchestration (specs/09 §3) — the ONE path from
package to decision packet and from human decision to sealed snapshot.
LangGraph nodes call these functions; the corpus runner calls them
directly. Every step appends its audit events (FR-AUD-1).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.adapters import (
    SimCreditBureau, SimEmploymentVerifier, SimFloodZone, SimGeoDistance,
    SimOfacScreen,
)
from app.agent.assembly import AssembledCase, assemble_case
from app.agent.decisioning import (
    Condition,
    GateDecision,
    build_adverse_action_notice,
    build_decision_packet,
    hmda_action_taken,
    suggested_action,
    synthesize_conditions,
    validate_resume,
)
from app.audit.canonical import canonical_json, sha256_hex
from app.audit.ledger import AuditLedger
from app.audit.snapshot import build_snapshot
from app.aus.du_simulator import AusFindings, load_config, run_simulator
from app.domain.calculations.dti import principal_interest
from app.domain.lineage import Lineage
from app.domain.numeric import D, HUNDRED, money, ratio_pct
from app.llm.ua_base import PromptRegistry, UALLMClient
from app.policy_engine import JsonRulesEngine, LoadedPacks
from app.policy_engine.result import RulesResult

EXTRACTION_PROMPTS = {
    "paystub": "extraction/paystub", "w2": "extraction/w2",
    "tax_return_1040": "extraction/tax-return-1040",
    "schedule_c": "extraction/schedule-c",
    "bank_statement": "extraction/bank-statement",
    "appraisal": "extraction/appraisal", "urla_1003": "extraction/urla-1003",
    "gift_letter": "extraction/gift-letter", "lease": "extraction/lease",
}


@dataclass
class Services:
    packs: LoadedPacks
    registry: PromptRegistry
    llm: UALLMClient
    ledger: AuditLedger
    aus_config: dict
    engine: JsonRulesEngine
    four_eyes_threshold: Decimal
    llm_provider: str
    code_git_sha: str = "dev"

    @property
    def reason_bindings(self) -> dict[str, dict]:
        return self.packs.reason_codes


@dataclass
class CaseRun:
    application_id: str
    package: dict
    as_of: dt.date
    case: AssembledCase
    rules: RulesResult
    aus: AusFindings
    conditions: list[Condition]
    packet: dict[str, Any]
    extractions: dict[str, dict]
    adapter_results: dict[str, Any]
    halted: str | None = None   # "ofac" halt (FR-VER-5)


async def run_to_gate(services: Services, *, application_id: str,
                      package: dict, as_of: dt.date) -> CaseRun:
    ledger = services.ledger
    ledger.append(application_id=application_id, event_type="state_change",
                  actor="system", payload={"from": "received", "to": "in_review"})

    # -- document extraction (specs/09 §3.2) --------------------------------
    extractions: dict[str, dict] = {}
    for doc in package["documents"]:
        prompt_id = EXTRACTION_PROMPTS.get(doc["doc_type"])
        if prompt_id is None:
            continue  # tri_merge_credit / voe: structured pass-through
        prompt = services.registry.get(prompt_id)
        result = await services.llm.extract(
            prompt=prompt, document_text=doc["text_rendering"],
            ground_truth=doc.get("ground_truth"),
            call_site="document_extraction")
        extractions[doc["doc_id"]] = {
            "fields": result.fields, "confidence": result.confidence,
            "prompt": f"{prompt_id}@v{prompt.version}",
            "model": result.record.model_id}
        ledger.append(application_id=application_id, event_type="llm_call",
                      actor="agent", payload=result.record.audit_payload())

    # -- adapters (specs/09 §3.3) -------------------------------------------
    borrower = package["borrowers"][0]
    adapter_results = {
        "bureau": SimCreditBureau().pull(
            package=package, permissible_purpose="credit_transaction"),
        "voe": SimEmploymentVerifier().verify(borrower=borrower),
        "flood": SimFloodZone().lookup(property_data=package["property"]),
        "ofac": SimOfacScreen().screen(
            parties=[b["full_name"] for b in package["borrowers"]]),
        "geo": SimGeoDistance().distance(
            property_data=package["property"],
            employment=borrower["employment"][0]),
    }
    for name, result in adapter_results.items():
        ledger.append(application_id=application_id, event_type="adapter_call",
                      actor="agent",
                      payload=result.audit_payload({"adapter": name}))

    if adapter_results["ofac"].result["hit"]:  # FR-VER-5 hard stop
        ledger.append(application_id=application_id, event_type="state_change",
                      actor="system",
                      payload={"from": "in_review", "to": "suspended",
                               "reason": "ofac_hit_mandatory_review"})
        empty_case = None
        return CaseRun(application_id, package, as_of, empty_case, None, None,
                       [], {}, extractions, adapter_results, halted="ofac")

    # -- assembly + rules + AUS ----------------------------------------------
    case = assemble_case(
        application_id=application_id, package=package, extractions=extractions,
        adapter_results=adapter_results, constants=services.packs.constants,
        states_index=services.packs.states_index,
        reference_indices=services.packs.reference_indices,
        compensating_factors=services.packs.compensating_factors,
        pack_version=services.packs.base_version, as_of=as_of)
    for discrepancy in case.discrepancies:
        ledger.append(application_id=application_id,
                      event_type="discrepancy_found", actor="agent",
                      payload=discrepancy.__dict__)
    for flag in case.red_flags:
        ledger.append(application_id=application_id, event_type="red_flag",
                      actor="agent", payload=flag.__dict__)

    recompute = _make_recompute(package, case)
    rules = services.engine.evaluate(services.packs, case.context,
                                     recompute=recompute)
    ledger.append(
        application_id=application_id, event_type="rule_eval_batch",
        actor="agent",
        payload={"pack_version": rules.pack_version,
                 "overlay_pack_version": rules.overlay_pack_version,
                 "pack_manifest_sha256": services.packs.base_manifest_sha256,
                 "results": [{"rule_id": e.rule_id, "outcome": e.outcome,
                              "reason_code": e.reason_code}
                             for e in rules.evaluations]})

    voe_result = adapter_results["voe"].result.get("result", "unavailable")
    severity_counts = {
        "elevated": sum(1 for f in case.red_flags if f.severity == "elevated"),
        "critical": sum(1 for f in case.red_flags if f.severity == "critical"),
    }
    prop = package["property"]
    aus = run_simulator(
        services.aus_config,
        credit_score=case.four_cs["credit"]["representative_score"],
        back_dti=case.four_cs["capacity"]["back_ratio"],
        ltv=case.four_cs["collateral"]["ltv"],
        reserves_months=case.four_cs["capital"]["reserves_months"],
        self_employed=bool(borrower.get("self_employed")),
        occupancy=package["loan"]["occupancy"],
        red_flag_counts=severity_counts, rules_rollup=rules.overall,
        triggers={
            "voe_not_verified": voe_result != "verified",
            "income_discrepancy": any(
                d.exceeded and d.field.startswith("income.")
                for d in case.discrepancies),
            "unsourced_large_deposit": any(
                f.flag_code == "RF-DEP-UNSOURCED" for f in case.red_flags),
            "funds_unseasoned": case.context["assets.unseasoned_funds"][0] == 1,
            "credit_report_age_gt_90": case.context["credit.report_age_days"][0] > 90,
            "appraisal_age_gt_90": case.context["appraisal.age_days"][0] > 90,
            "ltv_gt_80": D(case.four_cs["collateral"]["ltv"]) > D("80.00"),
            "gift_funds_present": bool(package["assets"].get("gift_funds")),
        })
    ledger.append(application_id=application_id, event_type="aus_run",
                  actor="agent",
                  payload={"simulator_version": aus.simulator_version,
                           "recommendation": aus.recommendation,
                           "breakdown": aus.breakdown,
                           "total_points": aus.total_points})

    conditions = synthesize_conditions(case, rules, aus)
    for condition in conditions:
        ledger.append(application_id=application_id,
                      event_type="condition_created", actor="agent",
                      payload={"condition_id": condition.id,
                               "category": condition.category,
                               "source_kind": condition.source_kind,
                               "source_id": condition.source_id,
                               "drafted_by_llm": condition.drafted_by_llm})

    suggested = suggested_action(case, rules, voe_result)
    packet = build_decision_packet(
        application_id=application_id, case=case, rules=rules, aus=aus,
        conditions=conditions, suggested=suggested,
        four_eyes_threshold=services.four_eyes_threshold,
        loan_amount=D(package["loan"]["amount"]))
    ledger.append(application_id=application_id,
                  event_type="decision_packet_ready", actor="agent",
                  payload={"suggested_action": suggested,
                           "failed_rule_ids": list(rules.failed_rule_ids),
                           "four_eyes_required": packet["four_eyes_required"],
                           "packet_sha256": sha256_hex(canonical_json(packet))})
    return CaseRun(application_id, package, as_of, case, rules, aus,
                   conditions, packet, extractions, adapter_results)


def _make_recompute(package: dict, case: AssembledCase):
    taxes = D(package["property"]["annual_taxes"]) / 12
    hazard = D(package["property"]["annual_hazard_insurance"]) / 12
    income = D(case.four_cs["capacity"]["qualifying_income_monthly"])
    liabilities = D(case.computed["dti"]["liabilities"])
    rate = package["loan"]["note_rate"]
    term = int(package["loan"]["term_months"])

    def recompute(ctx, amount):
        lineage = Lineage(application_id="COUNTEROFFER0000000000000")
        pi = principal_interest(
            lineage,
            loan_amount=lineage.add("package_stated", "amount", str(money(amount))),
            note_rate_pct=lineage.add("package_stated", "rate", rate),
            term_months=term)
        back = ratio_pct((D(pi.value) + taxes + hazard + liabilities)
                         / income * HUNDRED)
        out = dict(ctx)
        out["loan.amount"] = (money(amount), None)
        out["dti.back_ratio"] = (back, None)
        return out

    return recompute


@dataclass(frozen=True)
class FinalOutcome:
    action: str
    hmda_action_taken: int | None
    snapshot_sha256: str
    adverse_action: dict | None
    override: dict | None
    validation_errors: tuple[str, ...] = ()


def finalize(services: Services, run: CaseRun,
             resume: dict[str, Any]) -> FinalOutcome:
    """specs/09 §3.10–§3.13: validate the human decision, generate adverse
    action on decline, map HMDA, seal the snapshot + chain."""
    ledger = services.ledger
    decision, errors = validate_resume(resume, run.packet)
    if errors:
        return FinalOutcome("invalid", None, "", None, None, tuple(errors))

    ledger.append(application_id=run.application_id, event_type="human_action",
                  actor=f"underwriter:{decision.underwriter_id}",
                  payload={"action": decision.action,
                           "underwriter_id": decision.underwriter_id,
                           "second_reviewer_id": decision.second_reviewer_id,
                           "reason_codes": list(decision.reason_codes),
                           "notes": decision.notes,
                           "condition_edits_count": len(decision.condition_edits)})

    override_record = None
    if decision.is_override:
        override_record = {
            "suggested_action": run.packet["suggested_action"],
            "actual_action": decision.action,
            "justification": decision.justification,
            "underwriter_id": decision.underwriter_id,
            "second_reviewer_id": decision.second_reviewer_id,
        }
        ledger.append(application_id=run.application_id, event_type="override",
                      actor=f"underwriter:{decision.underwriter_id}",
                      payload=override_record)

    adverse = None
    if decision.action == "decline":
        adverse = build_adverse_action_notice(
            reason_codes=decision.reason_codes,
            reason_bindings=services.reason_bindings,
            credit=run.package["credit"],
            states_index=services.packs.states_index,
            property_state=run.package["property"]["address"]["state"])
        ledger.append(
            application_id=run.application_id,
            event_type="adverse_action_generated",
            actor="system",
            payload={"reason_codes": list(decision.reason_codes),
                     "fcra_score": adverse["fcra_block"]["score"],
                     "admt_state_artifact": bool(adverse["admt_block"]),
                     "notice_sha256": sha256_hex(adverse["body_text"])})

    action_code = hmda_action_taken(decision.action)
    ledger.append(application_id=run.application_id,
                  event_type="hmda_action_taken", actor="system",
                  payload={"action_taken": action_code,
                           "denial_reasons": [
                               services.reason_bindings[c]["hmda_denial_code"]
                               for c in decision.reason_codes]})
    terminal = {"approve_with_conditions": "approved_with_conditions",
                "suspend": "suspended", "decline": "declined",
                "counteroffer": "counteroffer"}[decision.action]
    ledger.append(application_id=run.application_id, event_type="state_change",
                  actor="system",
                  payload={"from": "ready_for_decision", "to": terminal})

    snapshot, digest = build_snapshot(
        application_id=run.application_id,
        versions={
            "policy_pack": services.packs.base_version,
            "policy_pack_manifest_sha256": services.packs.base_manifest_sha256,
            "state_overlay_pack": services.packs.overlay_version,
            "state_overlay_manifest_sha256": services.packs.overlay_manifest_sha256,
            "prompts": services.registry.pinned_versions(),
            "model_ids": sorted({e["model"] for e in run.extractions.values()}),
            "aus_simulator": run.aus.simulator_version,
            "code_git_sha": services.code_git_sha,
            "llm_provider": services.llm_provider,
        },
        inputs={
            "package_sha256": sha256_hex(canonical_json(run.package)),
            "extracted_fields": [
                {"id": f"{doc_id}.{field}", "document_id": doc_id,
                 "field_name": field, "value": str(value),
                 "confidence": str(entry["confidence"].get(field, "0")),
                 "prompt": entry["prompt"], "model": entry["model"]}
                for doc_id, entry in sorted(run.extractions.items())
                for field, value in sorted(entry["fields"].items())
                if not isinstance(value, (list, dict))],
            "adapter_results": [
                {"adapter": result.adapter_name, "version": result.adapter_version,
                 "result": result.result}
                for result in run.adapter_results.values()],
        },
        computed=run.case.computed,
        rules=run.rules,
        aus={"recommendation": run.aus.recommendation,
             "breakdown": run.aus.breakdown,
             "messages": [m.__dict__ for m in run.aus.messages]},
        conditions=[c.__dict__ for c in run.conditions],
        decision={
            "action": decision.action,
            "suggested_action": run.packet["suggested_action"],
            "decided_by": decision.underwriter_id,
            "second_reviewer": decision.second_reviewer_id,
            "reason_codes": list(decision.reason_codes),
            "reasons_detail": [   # decision-reason record, human-readable forever
                {"reason_code": code,
                 "ecoa_text": services.reason_bindings[code]["ecoa_text"],
                 "hmda_denial_code":
                     services.reason_bindings[code]["hmda_denial_code"]}
                for code in decision.reason_codes],
            "notes": decision.notes,
            "override": override_record,
            "counteroffer_terms": decision.counteroffer_terms,
            "hmda_action_taken": action_code,
        },
        adverse_action_notice_sha256=(
            sha256_hex(adverse["body_text"]) if adverse else None),
    )
    ledger.store_snapshot(run.application_id, canonical_json(snapshot),
                          digest, snapshot["sealed_at"])
    ledger.append(application_id=run.application_id, event_type="seal",
                  actor="system",
                  payload={"snapshot_sha256": digest,
                           "decision_action": decision.action,
                           "pack_version": services.packs.base_version,
                           "overlay_pack_version": services.packs.overlay_version,
                           "aus_simulator": run.aus.simulator_version,
                           "code_git_sha": services.code_git_sha})
    return FinalOutcome(decision.action, action_code, digest, adverse,
                        override_record)


__all__ = ["Services", "CaseRun", "FinalOutcome", "run_to_gate", "finalize",
           "EXTRACTION_PROMPTS"]
