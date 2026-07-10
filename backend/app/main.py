"""
FastAPI entrypoint.

Starts the app, configures CORS + logging, and mounts the CopilotKit
remote endpoint. Run locally with:

    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, runtime
from app.config import get_settings
from app.logging_config import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    log.info("backend.startup", version=__version__, provider=settings.llm_provider)
    # Underwriter agent mounts here: its AsyncSqliteSaver checkpointer
    # requires a running event loop (specs/09 §6 durability).
    await runtime.mount_underwriter(app)
    yield
    log.info("backend.shutdown")


app = FastAPI(
    title="CopilotKit Kickstarter Backend",
    version=__version__,
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Always returns 200."""
    return {"status": "ok", "version": __version__, "provider": settings.llm_provider}


# Wire the CopilotKit endpoint last so the import is lazy (and skippable
# in tests that don't need the SDK).
runtime.mount(app)
