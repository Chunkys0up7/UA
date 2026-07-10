"""
LLMProvider — the contract every concrete provider must satisfy.

A provider takes a list of messages plus an optional tool schema and returns
either a single `LLMResponse` (sync) or an async iterator of `LLMChunk`
(streaming). Tool-call shape is normalized so the upstream `ActionRegistry`
sees one format regardless of vendor.

Spec: docs/classes/LLMProvider.md

Complexity:
    - generate / stream:    O(tokens). Network-bound; latency dominates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Self

from app.config import Settings

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """One message in a chat history."""

    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A normalized tool invocation request from the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A complete (non-streaming) model response."""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMChunk:
    """One delta in a streamed response.

    `text_delta` is the new tokens (may be empty if this chunk only carries
    a tool call). `tool_call` is set when the model emits a tool invocation.
    `done` is True on the terminal chunk.
    """

    text_delta: str = ""
    tool_call: ToolCall | None = None
    done: bool = False


class LLMProvider(ABC):
    """Abstract base every concrete LLM adapter implements."""

    name: str = "abstract"

    def __init__(self, model: str) -> None:
        self.model = model

    # --- Construction -----------------------------------------------------
    @classmethod
    @abstractmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Build an instance from validated settings. Raises if misconfigured."""

    # --- Generation -------------------------------------------------------
    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Run the model once and return the full response."""

    @abstractmethod
    def stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Stream the model response token-by-token."""

    # --- Introspection ----------------------------------------------------
    def describe(self) -> dict[str, str]:
        """Return human-readable provider/model metadata for logging & UI."""
        return {"provider": self.name, "model": self.model}
