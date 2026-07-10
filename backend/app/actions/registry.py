"""
ActionRegistry — the lookup table for server-side actions.

Single responsibility: hold `Action` objects keyed by name and dispatch
incoming `ToolCall`s to the right handler. Schema-emission helpers are
on `Action`, not here.

Spec: docs/classes/ActionRegistry.md

Complexity:
    register / get / dispatch:  O(1) average (dict lookups).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.llm.base import ToolCall

from .base import Action, ActionResult
from .examples import echo_action, weather_action


class ActionRegistry:
    """Holds the set of actions available to the LLM."""

    def __init__(self, actions: Iterable[Action[Any]] = ()) -> None:
        self._actions: dict[str, Action[Any]] = {}
        for action in actions:
            self.register(action)

    # --- Mutators ---------------------------------------------------------
    def register(self, action: Action[Any]) -> None:
        if action.name in self._actions:
            raise ValueError(f"Action {action.name!r} already registered.")
        self._actions[action.name] = action

    # --- Accessors --------------------------------------------------------
    def __len__(self) -> int:
        return len(self._actions)

    def __contains__(self, name: object) -> bool:
        return name in self._actions

    def names(self) -> list[str]:
        return sorted(self._actions)

    def get(self, name: str) -> Action[Any] | None:
        return self._actions.get(name)

    # --- Schema emission --------------------------------------------------
    def openai_schemas(self) -> list[dict[str, Any]]:
        return [a.openai_schema() for a in self._actions.values()]

    def anthropic_schemas(self) -> list[dict[str, Any]]:
        return [a.anthropic_schema() for a in self._actions.values()]

    def copilotkit_schemas(self) -> list[dict[str, Any]]:
        return [a.copilotkit_schema() for a in self._actions.values()]

    # --- Dispatch ---------------------------------------------------------
    async def dispatch(self, call: ToolCall) -> ActionResult:
        action = self.get(call.name)
        if action is None:
            return ActionResult(ok=False, error=f"unknown action: {call.name!r}")
        return await action.call(call.arguments)


def default_registry() -> ActionRegistry:
    """Return the registry pre-populated with the example actions.

    Used by `app.runtime.build_endpoint()`. Replace with your own factory
    when you start adding real actions.
    """
    return ActionRegistry(actions=[echo_action, weather_action])
