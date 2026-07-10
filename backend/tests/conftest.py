"""Test fixtures shared across pytest modules."""

from __future__ import annotations

import os

import pytest

# Force the deterministic provider so unit tests never need network or keys.
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("LLM_MODEL", "mock-1")


@pytest.fixture
def mock_settings(monkeypatch):
    """Provide a clean Settings instance for tests that mutate env."""
    from app import config

    monkeypatch.setattr(config, "_SINGLETON", None)
    yield config.get_settings()
    monkeypatch.setattr(config, "_SINGLETON", None)
