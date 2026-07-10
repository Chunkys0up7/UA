"""
Underwriter walking skeleton — Phase 0 (specs/16 §3, gate T-P0-1).

A deliberately trivial 3-node graph proving the highest-risk integration
before any domain code exists: CopilotKit ⇄ AG-UI ⇄ LangGraph
`interrupt()` round-trip with a durable SQLite checkpointer.

    prepare ──► [interrupt(decision_packet_stub)] human_review ──► finalize

The interrupt payload and resume shape follow
`specs/schemas/interrupt-resume.schema.json` in miniature so the Phase 5
DecisionGate swap is payload-compatible.

Replaced in Phase 5 by the full underwriting graph (specs/09).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from app.logging_config import get_logger

log = get_logger(__name__)

_CHECKPOINT_DB = Path(__file__).resolve().parents[3] / "data" / "db" / "checkpoints.db"


class SkeletonState(TypedDict, total=False):
    application_id: str
    progress: list[dict[str, str]]
    decision_packet: dict[str, Any] | None
    human_decision: dict[str, Any] | None
    messages: list


async def _prepare(state: SkeletonState) -> dict:
    """Stand-in for the 12 analysis nodes: emits a stub decision packet."""
    packet = {
        "application_id": state.get("application_id", "APP-SKELETON-001"),
        "suggested_action": "approve_with_conditions",
        "rules": {"overall": "eligible", "failed": []},
        "eligible_reason_codes": [],
        "four_eyes_required": False,
        "validation_errors": [],
    }
    log.info("skeleton.prepare", packet=packet)
    return {
        "decision_packet": packet,
        "progress": [{"id": "prepare_decision", "label": "Prepare decision", "status": "done",
                      "detail": "stub packet ready"}],
    }


async def _human_review(state: SkeletonState) -> dict:
    """Pause at the gate; resume payload becomes the human decision."""
    resume = interrupt(state.get("decision_packet") or {})
    log.info("skeleton.resumed", resume=resume)
    return {"human_decision": resume if isinstance(resume, dict) else {"action": str(resume)}}


async def _finalize(state: SkeletonState) -> dict:
    decision = state.get("human_decision") or {}
    log.info("skeleton.finalize", decision=decision)
    return {
        "progress": [{"id": "finalize", "label": "Finalize", "status": "done",
                      "detail": f"action={decision.get('action', 'unknown')}"}],
    }


def build_underwriter_skeleton() -> CompiledStateGraph:
    """Compile the 3-node interrupt skeleton with a durable checkpointer."""
    _CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    graph = StateGraph(SkeletonState)
    graph.add_node("prepare", _prepare)
    graph.add_node("human_review", _human_review)
    graph.add_node("finalize", _finalize)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "human_review")
    graph.add_edge("human_review", "finalize")
    graph.add_edge("finalize", END)

    saver = AsyncSqliteSaver(aiosqlite.connect(str(_CHECKPOINT_DB), check_same_thread=False))
    return graph.compile(checkpointer=saver)


__all__ = ["build_underwriter_skeleton", "SkeletonState"]
