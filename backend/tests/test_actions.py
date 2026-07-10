"""Unit tests for Action and ActionRegistry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.actions import Action, ActionRegistry, default_registry, echo_action
from app.actions.base import ActionResult
from app.llm.base import ToolCall


# --- Action -----------------------------------------------------------------


async def test_echo_action_runs() -> None:
    result = await echo_action.call({"text": "hi"})
    assert result.ok is True
    assert result.value == {"echoed": "hi"}


async def test_action_validates_arguments() -> None:
    result = await echo_action.call({"wrong": "key"})
    assert result.ok is False
    assert "invalid arguments" in (result.error or "")


async def test_action_wraps_handler_exceptions() -> None:
    class P(BaseModel):
        x: int

    async def boom(_: P) -> None:
        raise RuntimeError("kaboom")

    a: Action[P] = Action(name="boom", description="x", parameters=P, handler=boom)
    r = await a.call({"x": 1})
    assert r.ok is False
    assert "RuntimeError: kaboom" in (r.error or "")


# --- Schemas ----------------------------------------------------------------


def test_openai_schema_shape() -> None:
    s = echo_action.openai_schema()
    assert s["type"] == "function"
    assert s["function"]["name"] == "echo"
    assert "parameters" in s["function"]


def test_anthropic_schema_shape() -> None:
    s = echo_action.anthropic_schema()
    assert s["name"] == "echo"
    assert "input_schema" in s


def test_copilotkit_schema_shape() -> None:
    s = echo_action.copilotkit_schema()
    assert s["name"] == "echo"
    assert isinstance(s["parameters"], list)
    assert any(p["name"] == "text" and p["required"] for p in s["parameters"])


# --- Registry ---------------------------------------------------------------


def test_default_registry_has_examples() -> None:
    r = default_registry()
    assert "echo" in r
    assert "get_weather" in r
    assert len(r) == 2


def test_registry_rejects_duplicates() -> None:
    r = ActionRegistry([echo_action])
    with pytest.raises(ValueError, match="already registered"):
        r.register(echo_action)


async def test_registry_dispatch_unknown_action() -> None:
    r = ActionRegistry([echo_action])
    res: ActionResult = await r.dispatch(ToolCall(id="x", name="missing", arguments={}))
    assert res.ok is False
    assert "unknown action" in (res.error or "")


async def test_registry_dispatch_runs_handler() -> None:
    r = default_registry()
    res = await r.dispatch(ToolCall(id="x", name="echo", arguments={"text": "yo"}))
    assert res.ok is True
    assert res.value == {"echoed": "yo"}
