"""
LLM provider abstraction.

Public surface:
    - `LLMProvider`             — abstract base
    - `LLMMessage`, `LLMResponse`, `LLMChunk` — DTOs
    - `get_provider()`          — factory selecting via Settings.llm_provider

The factory is the only thing the rest of the app talks to. To add a
provider, drop a `*_provider.py` next to the existing ones, register
it in `_REGISTRY`, and you're done.
"""

from __future__ import annotations

from app.config import Settings, get_settings

from .anthropic_provider import AnthropicProvider
from .base import LLMChunk, LLMMessage, LLMProvider, LLMResponse, ToolCall
from .mock_provider import MockProvider
from .openai_provider import OpenAIProvider

_REGISTRY: dict[str, type[LLMProvider]] = {
    "mock": MockProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def get_provider(settings: Settings | None = None) -> LLMProvider:
    """Return the provider instance configured via env."""
    settings = settings or get_settings()
    cls = _REGISTRY.get(settings.llm_provider)
    if cls is None:
        raise ValueError(
            f"Unknown LLM_PROVIDER={settings.llm_provider!r}. "
            f"Known: {sorted(_REGISTRY)}"
        )
    return cls.from_settings(settings)


__all__ = [
    "AnthropicProvider",
    "LLMChunk",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "MockProvider",
    "OpenAIProvider",
    "ToolCall",
    "get_provider",
]
