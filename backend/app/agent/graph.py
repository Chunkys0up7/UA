"""The UA underwriting graph (specs/09) — replaces the P0 skeleton at the
same /agent/underwriter mount with the same interrupt/resume contract.

    underwrite ──► human_review ⟦interrupt loop⟧ ──► done

`underwrite` runs the full pipeline (run_to_gate) and stores the CaseRun
in the run registry; `human_review` interrupts with the decision packet
and loops until the resume validates (invalid resumes re-present the
gate with validation_errors — FR-DEC-7). Durable resume: if the process
restarted between interrupt and resume, the CaseRun is rehydrated by
deterministically re-running the pipeline against an ephemeral ledger
(no duplicate events in the real chain).
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from app.agent.runner import CaseRun, Services, finalize, run_to_gate
from app.audit.ledger import AuditLedger
from app.aus.du_simulator import load_config
from app.llm.ua_base import PromptRegistry
from app.llm.ua_mock import MockUALLMClient
from app.logging_config import get_logger
from app.policy_engine import JsonRulesEngine, load_packs
from synthetic.generate import BASE_DATE

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
_services: Services | None = None
_run_registry: dict[str, CaseRun] = {}
_submitted_packages: dict[str, dict] = {}


def get_services() -> Services:
    global _services
    if _services is None:
        provider = os.environ.get("LLM_PROVIDER", "mock")
        if provider == "anthropic":
            from app.llm.ua_anthropic import AnthropicUALLMClient
            llm = AnthropicUALLMClient(
                model_id=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"))
        else:
            provider, llm = "mock", MockUALLMClient()
        _services = Services(
            packs=load_packs(
                REPO_ROOT / "policy" / "packs" / "conforming-2026.1.0",
                REPO_ROOT / "policy" / "packs" / "state-overlays-2026.1.0"),
            registry=PromptRegistry(REPO_ROOT / "policy" / "prompts"),
            llm=llm,
            ledger=AuditLedger(REPO_ROOT / "data" / "db" / "audit.db"),
            aus_config=load_config(REPO_ROOT / "policy" / "aus" / "du-sim.v1.json"),
            engine=JsonRulesEngine(),
            four_eyes_threshold=Decimal(
                os.environ.get("FOUR_EYES_THRESHOLD", "1000000")),
            llm_provider=provider,
            code_git_sha=os.environ.get("CODE_GIT_SHA", "dev"),
        )
    return _services


def submit_package(application_id: str, package: dict) -> None:
    """Called by the REST layer (P6) after schema validation."""
    _submitted_packages[application_id] = package


def _resolve_package(application_id: str) -> dict:
    if application_id in _submitted_packages:
        return _submitted_packages[application_id]
    golden = REPO_ROOT / "data" / "loans" / f"{application_id}.json"
    if golden.exists():  # dev convenience: golden archetypes by name
        return json.loads(golden.read_text(encoding="utf-8"))
    raise KeyError(f"no package submitted for {application_id}")


async def _rehydrate(application_id: str) -> CaseRun:
    """Deterministic rebuild after restart — ephemeral ledger, so the real
    chain gets no duplicate analysis events (specs/09 §6)."""
    import tempfile
    services = get_services()
    with tempfile.TemporaryDirectory() as tmp:
        ephemeral = Services(
            packs=services.packs, registry=services.registry,
            llm=services.llm, ledger=AuditLedger(Path(tmp) / "ephemeral.db"),
            aus_config=services.aus_config, engine=services.engine,
            four_eyes_threshold=services.four_eyes_threshold,
            llm_provider=services.llm_provider,
            code_git_sha=services.code_git_sha)
        return await run_to_gate(
            ephemeral, application_id=application_id,
            package=_resolve_package(application_id), as_of=BASE_DATE)


STAGES = [
    "package_validate", "document_extraction", "data_verification",
    "income_calc", "credit_analysis", "asset_analysis",
    "collateral_analysis", "fraud_screen", "rules_eval", "aus_simulate",
    "condition_synthesis", "prepare_decision", "finalize",
]


class UnderwritingState(TypedDict, total=False):
    application_id: str
    policy_pack_version: str
    progress: list[dict[str, str]]
    four_cs: dict[str, Any]
    red_flags: list[dict[str, Any]]
    aus: dict[str, Any]
    conditions_summary: list[dict[str, Any]]
    decision_packet: dict[str, Any] | None
    human_decision: dict[str, Any] | None
    final_outcome: dict[str, Any] | None
    messages: list


def _progress(done_through: str, detail: str = "") -> list[dict[str, str]]:
    stages = []
    reached = True
    for stage in STAGES:
        status = "done" if reached else "pending"
        stages.append({"id": stage, "label": stage.replace("_", " ").title(),
                       "status": status,
                       "detail": detail if stage == done_through else ""})
        if stage == done_through:
            reached = False
    return stages


async def _underwrite(state: UnderwritingState) -> dict:
    application_id = state["application_id"]
    services = get_services()
    run = await run_to_gate(
        services, application_id=application_id,
        package=_resolve_package(application_id), as_of=BASE_DATE)
    _run_registry[application_id] = run
    if run.halted:
        return {
            "progress": _progress("data_verification",
                                  "halted: OFAC mandatory review"),
            "decision_packet": None,
            "final_outcome": {"action": "suspended", "halt": run.halted},
        }
    case = run.case
    return {
        "policy_pack_version": services.packs.base_version,
        "progress": _progress("prepare_decision", "packet ready for review"),
        "four_cs": {
            "credit": {"representative_score":
                       case.four_cs["credit"]["representative_score"],
                       "open_disputes": case.four_cs["credit"]["open_disputes"],
                       "flags": case.four_cs["credit"]["flags"]},
            "capacity": {"front_ratio": case.four_cs["capacity"]["front_ratio"],
                         "back_ratio": case.four_cs["capacity"]["back_ratio"],
                         "qualifying_income_monthly":
                         case.four_cs["capacity"]["qualifying_income_monthly"]},
            "capital": {"reserves_months":
                        case.four_cs["capital"]["reserves_months"],
                        "unsourced_deposits":
                        case.four_cs["capital"]["unsourced_deposits"]},
            "collateral": {"ltv": case.four_cs["collateral"]["ltv"],
                           "cltv": case.four_cs["collateral"]["cltv"]},
        },
        "red_flags": [{"code": f.flag_code, "severity": f.severity,
                       "description": f.description} for f in case.red_flags],
        "aus": {"recommendation": run.aus.recommendation,
                "message_count": len(run.aus.messages)},
        "conditions_summary": [
            {"id": c.id, "category": c.category, "title": c.title,
             "source_kind": c.source_kind} for c in run.conditions],
        "decision_packet": run.packet,
    }


async def _human_review(state: UnderwritingState) -> dict:
    if state.get("final_outcome"):   # OFAC halt: no gate (FR-VER-5)
        return {}
    application_id = state["application_id"]
    packet = dict(state["decision_packet"] or {})
    errors: list[str] = []
    while True:
        packet["validation_errors"] = errors
        resume = interrupt(packet)
        parsed = json.loads(resume) if isinstance(resume, str) else resume
        run = _run_registry.get(application_id)
        if run is None:
            run = await _rehydrate(application_id)
            _run_registry[application_id] = run
        outcome = finalize(get_services(), run, parsed)
        if outcome.action != "invalid":
            return {
                "human_decision": parsed,
                "progress": _progress("finalize",
                                      f"action={outcome.action}"),
                "final_outcome": {
                    "action": outcome.action,
                    "hmda_action_taken": outcome.hmda_action_taken,
                    "snapshot_sha256": outcome.snapshot_sha256,
                    "adverse_action": bool(outcome.adverse_action),
                    "override": bool(outcome.override),
                },
            }
        errors = list(outcome.validation_errors)
        log.info("gate.invalid_resume", application_id=application_id,
                 errors=errors)


def build_underwriter_graph(checkpointer=None) -> CompiledStateGraph:
    graph = StateGraph(UnderwritingState)
    graph.add_node("underwrite", _underwrite)
    graph.add_node("human_review", _human_review)
    graph.add_edge(START, "underwrite")
    graph.add_edge("underwrite", "human_review")   # NO bypass edge (HR-2)
    graph.add_edge("human_review", END)
    return graph.compile(checkpointer=checkpointer)


__all__ = ["build_underwriter_graph", "UnderwritingState", "get_services",
           "submit_package", "STAGES"]
