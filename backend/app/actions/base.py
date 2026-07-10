"""
Action — one callable the LLM can invoke.

Each action carries:
    - `name`        : the symbol the LLM uses to call it.
    - `description` : a human/LLM sentence explaining what it does.
    - `parameters`  : a Pydantic model describing the args (validated on dispatch).
    - `handler`     : the async function that runs.

We deliberately wrap the handler in this dataclass instead of using bare
functions so the same object can produce the OpenAI tool schema, the
Anthropic tool schema, and the CopilotKit action JSON without a separate
adapter for each.

Spec: docs/classes/Action.md
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

ParamsT = TypeVar("ParamsT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Outcome of running an action."""

    ok: bool
    value: Any = None
    error: str | None = None

    def to_message(self) -> str:
        """Render to a tool-message string the LLM can consume."""
        if self.ok:
            return str(self.value)
        return f"ERROR: {self.error}"


@dataclass(frozen=True, slots=True)
class Action(Generic[ParamsT]):
    """A single typed action."""

    name: str
    description: str
    parameters: type[ParamsT]
    handler: Callable[[ParamsT], Awaitable[Any]]

    # --- Schema generation ------------------------------------------------
    def openai_schema(self) -> dict[str, Any]:
        """Return the OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters.model_json_schema(),
            },
        }

    def anthropic_schema(self) -> dict[str, Any]:
        """Return the Anthropic tool-use schema."""
        schema = self.parameters.model_json_schema()
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    def copilotkit_schema(self) -> dict[str, Any]:
        """Return the CopilotKit action schema (used by the runtime endpoint)."""
        schema = self.parameters.model_json_schema()
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        params = [
            {
                "name": pname,
                "type": pinfo.get("type", "string"),
                "description": pinfo.get("description", ""),
                "required": pname in required,
            }
            for pname, pinfo in properties.items()
        ]
        return {
            "name": self.name,
            "description": self.description,
            "parameters": params,
        }

    # --- Dispatch ---------------------------------------------------------
    async def call(self, raw_args: dict[str, Any]) -> ActionResult:
        """Validate args and run the handler. Never raises — wraps errors."""
        try:
            parsed = self.parameters.model_validate(raw_args)
        except ValidationError as exc:
            return ActionResult(ok=False, error=f"invalid arguments: {exc}")
        try:
            value = await self.handler(parsed)
        except Exception as exc:  # noqa: BLE001 — surface to LLM, never crash
            return ActionResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        return ActionResult(ok=True, value=value)
