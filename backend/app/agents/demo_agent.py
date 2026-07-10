"""
DemoAgent — a minimal LangGraph-shaped agent stub.

This is intentionally framework-light: it shows the *shape* a real
LangGraph agent would have so you can drop in `from langgraph.graph
import StateGraph` and replace `_run_step` without touching the rest
of the wiring.

Spec: docs/classes/DemoAgent.md
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.llm import LLMMessage, LLMProvider


@dataclass(slots=True)
class AgentState:
    """The state the UI can observe while the agent runs.

    `status` powers `useCoAgentStateRender` on the frontend so users
    see "planning…", "calling get_weather…", "done" in real time.
    """

    status: str = "idle"
    messages: list[LLMMessage] = None  # type: ignore[assignment]
    last_output: str = ""

    def __post_init__(self) -> None:
        if self.messages is None:
            self.messages = []


class DemoAgent:
    """One-shot LLM call wrapped as an agent. Swap for LangGraph when ready."""

    name = "demo"

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self.state = AgentState()

    async def run(self, user_message: str) -> AsyncIterator[AgentState]:
        """Yield state snapshots as the agent progresses."""
        self.state.status = "thinking"
        self.state.messages.append(LLMMessage(role="user", content=user_message))
        yield self._snapshot()

        rsp = await self._provider.generate(self.state.messages)
        self.state.last_output = rsp.content
        self.state.messages.append(LLMMessage(role="assistant", content=rsp.content))
        self.state.status = "done"
        yield self._snapshot()

    def _snapshot(self) -> AgentState:
        return AgentState(
            status=self.state.status,
            messages=list(self.state.messages),
            last_output=self.state.last_output,
        )


def build_demo_agent(provider: LLMProvider) -> DemoAgent:
    return DemoAgent(provider)


__all__ = ["AgentState", "DemoAgent", "build_demo_agent"]
