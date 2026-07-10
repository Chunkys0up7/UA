"""CoAgent definitions.

Agents go here. Each agent is a single-file module that builds a
LangGraph `CompiledStateGraph`, which `app.runtime.mount` then wraps in
a `LangGraphAGUIAgent` for CopilotKit.

Two agents ship:
    - `default_agent.build_default_graph()` — minimal chat agent named
      "default"; required so CopilotKit 1.57+'s default `useAgent` call
      succeeds on page load.
    - `demo_agent.build_demo_agent()` — placeholder pattern showing the
      shape of a custom agent (no LangGraph, just demonstrates the
      AgentState surface). Optional reference; not registered.
"""

from .default_agent import build_default_graph
from .demo_agent import build_demo_agent
from .underwriter_skeleton import build_underwriter_skeleton

__all__ = ["build_default_graph", "build_demo_agent", "build_underwriter_skeleton"]
