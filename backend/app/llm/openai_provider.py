"""
OpenAIProvider — adapter for the OpenAI Chat Completions API.

This is a *placeholder wiring*: the SDK calls are implemented but stay
behind a key check. Set `LLM_PROVIDER=openai` and `OPENAI_API_KEY=...`
in `.env` to activate. The shape of the public methods matches `LLMProvider`
exactly so swapping is a one-line config change.

Spec: docs/classes/OpenAIProvider.md
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, Self

from app.config import Settings

from .base import LLMChunk, LLMMessage, LLMProvider, LLMResponse, ToolCall


class OpenAIProvider(LLMProvider):
    """Thin adapter over `openai.AsyncOpenAI`."""

    name = "openai"

    def __init__(self, model: str, api_key: str) -> None:
        super().__init__(model=model)
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER='openai'.")
        # Lazy import keeps `openai` truly optional.
        from openai import AsyncOpenAI  # noqa: PLC0415

        self._client = AsyncOpenAI(api_key=api_key)

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(model=settings.llm_model, api_key=settings.openai_api_key)

    # --- helpers ----------------------------------------------------------
    @staticmethod
    def _to_openai(messages: list[LLMMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.name:
                entry["name"] = m.name
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            out.append(entry)
        return out

    # --- generate ---------------------------------------------------------
    async def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        rsp = await self._client.chat.completions.create(
            model=self.model,
            messages=self._to_openai(messages),
            tools=tools,
            stream=False,
        )
        choice = rsp.choices[0]
        content = choice.message.content or ""
        tool_calls: tuple[ToolCall, ...] = tuple(
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (choice.message.tool_calls or [])
        )
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            raw=rsp.model_dump(),
        )

    # --- stream -----------------------------------------------------------
    async def stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMChunk]:
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=self._to_openai(messages),
            tools=tools,
            stream=True,
        )
        # Tool call deltas arrive as fragments; reassemble per index.
        partial: dict[int, dict[str, Any]] = {}
        async for event in stream:
            delta = event.choices[0].delta
            if delta.content:
                yield LLMChunk(text_delta=delta.content)
            for tc_delta in delta.tool_calls or []:
                slot = partial.setdefault(
                    tc_delta.index,
                    {"id": tc_delta.id or f"call_{uuid.uuid4().hex[:8]}", "name": "", "args": ""},
                )
                if tc_delta.function and tc_delta.function.name:
                    slot["name"] = tc_delta.function.name
                if tc_delta.function and tc_delta.function.arguments:
                    slot["args"] += tc_delta.function.arguments
        for slot in partial.values():
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": slot["args"]}
            yield LLMChunk(tool_call=ToolCall(id=slot["id"], name=slot["name"], arguments=args))
        yield LLMChunk(done=True)
