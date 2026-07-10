"""Backend action registry — exposes typed Python callables to the LLM."""

from .base import Action, ActionResult
from .examples import echo_action, weather_action
from .registry import ActionRegistry, default_registry

__all__ = [
    "Action",
    "ActionRegistry",
    "ActionResult",
    "default_registry",
    "echo_action",
    "weather_action",
]
