"""
MockProvider — deterministic, network-free LLM for tests and evals.

Behavior:
    - Echoes the last user message with a canned prefix.
    - If the user message starts with `/tool <name> <json-args>`, emits a
      single matching ToolCall — useful for exercising the action pipeline.
    - Streams the response one word at a time.

This lives in the same package as real providers so eval/test code paths
match production wiring exactly.

Spec: docs/classes/MockProvider.md
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, Self

from app.config import Settings

from .base import LLMChunk, LLMMessage, LLMProvider, LLMResponse, ToolCall

_MOCK_PREFIX = "[mock] "


class MockProvider(LLMProvider):
    """No-network LLM. Deterministic outputs make eval scenarios reproducible."""

    name = "mock"

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(model=settings.llm_model or "mock-1")

    # --- internals --------------------------------------------------------
    @staticmethod
    def _last_user(messages: list[LLMMessage]) -> str:
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content
        return ""

    @staticmethod
    def _maybe_tool_call(user_text: str) -> ToolCall | None:
        """Parse `/tool <name> <json-args>` directives for testing."""
        if not user_text.startswith("/tool "):
            return None
        try:
            _, name, raw = user_text.split(" ", 2)
            args = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return None
        return ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=args)

    # --- generate ---------------------------------------------------------
    async def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        user = self._last_user(messages)
        tool = self._maybe_tool_call(user)
        if tool is not None:
            return LLMResponse(content="", tool_calls=(tool,), finish_reason="tool_calls")
        reply = f"{_MOCK_PREFIX}{user}" if user else f"{_MOCK_PREFIX}(empty)"
        return LLMResponse(content=reply, finish_reason="stop")

    # --- stream -----------------------------------------------------------
    async def stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMChunk]:
        user = self._last_user(messages)
        tool = self._maybe_tool_call(user)
        if tool is not None:
            yield LLMChunk(tool_call=tool)
            yield LLMChunk(done=True)
            return
        reply = f"{_MOCK_PREFIX}{user}" if user else f"{_MOCK_PREFIX}(empty)"
        for word in reply.split(" "):
            yield LLMChunk(text_delta=word + " ")
            await asyncio.sleep(0)  # cooperative yield
        yield LLMChunk(done=True)
