"""Sanity test that the FastAPI /health endpoint is reachable.

Skipped automatically when the `copilotkit` SDK isn't installed (since
`app.main` imports it at startup). Mark with `integration` so devs can
opt out via `pytest -m 'not integration'`.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest

pytestmark = pytest.mark.integration

if importlib.util.find_spec("copilotkit") is None:
    pytest.skip("copilotkit SDK not installed", allow_module_level=True)


async def test_health_endpoint_returns_ok() -> None:
    from httpx import ASGITransport, AsyncClient

    app_module = importlib.import_module("app.main")
    transport = ASGITransport(app=app_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        rsp = await client.get("/health")
    assert rsp.status_code == 200
    body = rsp.json()
    assert body["status"] == "ok"
    assert body["provider"] == "mock"
