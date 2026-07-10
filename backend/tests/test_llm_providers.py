"""Unit tests for the LLM provider abstraction."""

from __future__ import annotations

import pytest

from app.llm import LLMMessage, MockProvider, get_provider
from app.llm.base import LLMChunk, ToolCall


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider(model="mock-1")


async def test_mock_generate_echoes_user(provider: MockProvider) -> None:
    rsp = await provider.generate([LLMMessage(role="user", content="hello")])
    assert rsp.content == "[mock] hello"
    assert rsp.tool_calls == ()
    assert rsp.finish_reason == "stop"


async def test_mock_generate_emits_tool_call(provider: MockProvider) -> None:
    rsp = await provider.generate(
        [LLMMessage(role="user", content='/tool get_weather {"city": "London"}')]
    )
    assert rsp.content == ""
    assert len(rsp.tool_calls) == 1
    tc: ToolCall = rsp.tool_calls[0]
    assert tc.name == "get_weather"
    assert tc.arguments == {"city": "London"}


async def test_mock_stream_yields_words_then_done(provider: MockProvider) -> None:
    chunks: list[LLMChunk] = []
    async for c in provider.stream([LLMMessage(role="user", content="ping pong")]):
        chunks.append(c)
    text = "".join(c.text_delta for c in chunks)
    assert text.strip() == "[mock] ping pong"
    assert chunks[-1].done is True


def test_factory_returns_mock_when_configured(mock_settings) -> None:
    p = get_provider(mock_settings)
    assert p.name == "mock"


def test_describe_returns_metadata(provider: MockProvider) -> None:
    assert provider.describe() == {"provider": "mock", "model": "mock-1"}
