"""
CopilotKit runtime wiring.

Builds a `CopilotKitRemoteEndpoint` populated with our `ActionRegistry`
(at `/copilotkit_remote`) and mounts a separate AG-UI LangGraph endpoint
at `/agent/default` for the chat agent.

Why two endpoints? The `copilotkit` 0.1.88 SDK's `LangGraphAGUIAgent`
bridge is broken (calls `super().dict_repr()` and `agent.execute()` that
don't exist in its base class). Until that's fixed upstream, we expose
the LangGraph agent via `ag_ui_langgraph.add_langgraph_fastapi_endpoint`
directly and tell the React provider about it via
`agents__unsafe_dev_only` (which points an `HttpAgent` at our path).

This module is the only place that imports the `copilotkit` /
`ag_ui_langgraph` SDKs.

Spec: docs/classes/Runtime.md
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.actions import ActionRegistry, default_registry
from app.actions.base import Action
from app.agents import build_default_graph, build_underwriter_skeleton
from app.llm import LLMProvider, get_provider
from app.logging_config import get_logger

log = get_logger(__name__)

_REMOTE_PATH = "/copilotkit_remote"
_AGENT_PATH = "/agent/default"
_DEFAULT_AGENT_NAME = "default"
_UNDERWRITER_PATH = "/agent/underwriter"
_UNDERWRITER_NAME = "underwriter"


def _action_to_copilotkit(action: Action[Any]) -> Any:
    """Wrap one of our `Action` objects in a `copilotkit.Action`."""
    from copilotkit import Action as CKAction  # type: ignore[import-untyped]

    schema = action.copilotkit_schema()

    async def _handler(**kwargs: Any) -> Any:
        result = await action.call(kwargs)
        return result.value if result.ok else {"error": result.error}

    return CKAction(
        name=schema["name"],
        description=schema["description"],
        parameters=schema.get("parameters", []),
        handler=_handler,
    )


def mount(app: FastAPI, *, registry: ActionRegistry | None = None) -> None:
    """Attach the CopilotKit remote endpoint and the LangGraph agent endpoint."""
    registry = registry or default_registry()
    provider: LLMProvider = get_provider()
    log.info(
        "copilotkit.runtime.mount",
        provider=provider.name,
        model=provider.model,
        actions=registry.names(),
        agent_path=_AGENT_PATH,
        remote_path=_REMOTE_PATH,
    )

    # Lazy imports keep these SDKs truly optional for unit tests.
    from copilotkit import CopilotKitRemoteEndpoint  # type: ignore[import-untyped]
    from copilotkit.integrations.fastapi import add_fastapi_endpoint  # type: ignore[import-untyped]
    from ag_ui_langgraph import LangGraphAgent, add_langgraph_fastapi_endpoint

    # 1. /copilotkit_remote — actions and info (no agents to dodge the
    #    broken LangGraphAGUIAgent bridge in copilotkit 0.1.88).
    sdk_actions = [
        _action_to_copilotkit(a)
        for a in (registry.get(n) for n in registry.names())
        if a
    ]
    endpoint = CopilotKitRemoteEndpoint(actions=sdk_actions, agents=[])
    add_fastapi_endpoint(app, endpoint, _REMOTE_PATH)
    log.info("copilotkit.runtime.mounted", path=_REMOTE_PATH)

    # 2. /agent/default — direct AG-UI LangGraph endpoint, called by the
    #    React side via an HttpAgent registered in `agents__unsafe_dev_only`.
    default_agent = LangGraphAgent(
        name=_DEFAULT_AGENT_NAME,
        graph=build_default_graph(),
        description=(
            "Default chat agent. Wraps the LLMProvider in a one-node LangGraph."
        ),
    )
    add_langgraph_fastapi_endpoint(app, default_agent, _AGENT_PATH)
    log.info("copilotkit.agent.mounted", path=_AGENT_PATH, agent=_DEFAULT_AGENT_NAME)


async def mount_underwriter(app: FastAPI) -> None:
    """Mount /agent/underwriter from FastAPI lifespan (async context).

    Separate from `mount` because the underwriter graph's
    `AsyncSqliteSaver` checkpointer must be constructed inside a running
    event loop. Routes added during lifespan startup are registered
    before the server accepts requests, so this is safe.

    Phase 5: the full underwriting pipeline graph (specs/09) — same mount
    and resume contract the Phase-0 skeleton proved.
    """
    import aiosqlite
    from ag_ui_langgraph import LangGraphAgent, add_langgraph_fastapi_endpoint
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from pathlib import Path

    from app.agent.graph import build_underwriter_graph

    checkpoint_db = Path(__file__).resolve().parents[2] / "data" / "db" / "checkpoints.db"
    checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
    saver = AsyncSqliteSaver(
        aiosqlite.connect(str(checkpoint_db), check_same_thread=False))
    underwriter_agent = LangGraphAgent(
        name=_UNDERWRITER_NAME,
        graph=build_underwriter_graph(checkpointer=saver),
        description="UA underwriting agent (full pipeline, specs/09).",
    )
    add_langgraph_fastapi_endpoint(app, underwriter_agent, _UNDERWRITER_PATH)
    log.info("copilotkit.agent.mounted", path=_UNDERWRITER_PATH, agent=_UNDERWRITER_NAME)


__all__ = ["mount", "mount_underwriter"]
