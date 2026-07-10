"""
AnthropicProvider — adapter for the Anthropic Messages API.

Same shape as `OpenAIProvider`. Activated by `LLM_PROVIDER=anthropic`
plus `ANTHROPIC_API_KEY` in `.env`.

Notes on the mapping:
    - Anthropic uses `system` as a top-level parameter, not a message
      with role=system. We extract & concatenate any `system` messages.
    - Tool calls are returned as content blocks of type=`tool_use`; we
      flatten those into our normalized `ToolCall`.

Spec: docs/classes/AnthropicProvider.md
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Self

from app.config import Settings

from .base import LLMChunk, LLMMessage, LLMProvider, LLMResponse, ToolCall


class AnthropicProvider(LLMProvider):
    """Thin adapter over `anthropic.AsyncAnthropic`."""

    name = "anthropic"

    def __init__(self, model: str, api_key: str) -> None:
        super().__init__(model=model)
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER='anthropic'.")
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        self._client = AsyncAnthropic(api_key=api_key)

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(model=settings.llm_model, api_key=settings.anthropic_api_key)

    # --- helpers ----------------------------------------------------------
    @staticmethod
    def _split(messages: list[LLMMessage]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        chat: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                # Anthropic only accepts user/assistant in `messages`.
                role = "user" if m.role in ("user", "tool") else "assistant"
                chat.append({"role": role, "content": m.content})
        return "\n\n".join(system_parts), chat

    # --- generate ---------------------------------------------------------
    async def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        system, chat = self._split(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": chat,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        rsp = await self._client.messages.create(**kwargs)
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in rsp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
                )
        return LLMResponse(
            content="".join(text_parts),
            tool_calls=tuple(tool_calls),
            finish_reason=rsp.stop_reason or "stop",
            raw=rsp.model_dump(),
        )

    # --- stream -----------------------------------------------------------
    async def stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMChunk]:
        system, chat = self._split(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": chat,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                if text:
                    yield LLMChunk(text_delta=text)
            final = await stream.get_final_message()
            for block in final.content:
                if block.type == "tool_use":
                    yield LLMChunk(
                        tool_call=ToolCall(
                            id=block.id, name=block.name, arguments=dict(block.input or {})
                        )
                    )
        yield LLMChunk(done=True)
