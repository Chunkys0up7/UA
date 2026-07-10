"""
DefaultAgent — minimal LangGraph CoAgent named "default".

Why this exists:
    CopilotKit 1.57+ requires at least one agent registered on the runtime.
    `<CopilotKit>` (with no `agent` prop) calls `useAgent("default")`
    internally; if the runtime has no agents, the page errors out on load.

What it does:
    A single-node LangGraph that delegates to our `LLMProvider`. With
    `LLM_PROVIDER=mock`, chat answers "[mock] <user message>" — the page
    works on first install with no keys. With `LLM_PROVIDER=openai|anthropic`
    it returns real model output.

Replace this graph with your own multi-node graph (planner, tool executor,
etc.) when you outgrow one-shot chat. The wrapper in `app/runtime.py`
stays the same.

Spec: docs/classes/DefaultAgent.md
"""

from __future__ import annotations

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.llm import LLMMessage, get_provider


def _to_llm_message(msg: BaseMessage) -> LLMMessage:
    """Map LangChain message types into our normalized LLMMessage."""
    if isinstance(msg, SystemMessage):
        role = "system"
    elif isinstance(msg, HumanMessage):
        role = "user"
    elif isinstance(msg, AIMessage):
        role = "assistant"
    elif isinstance(msg, ToolMessage):
        role = "tool"
    else:
        role = "user"
    return LLMMessage(role=role, content=str(msg.content))


async def _chat_node(state: MessagesState) -> dict:
    """One LLM call. Replace with multi-step planning when you need it."""
    provider = get_provider()
    msgs = [_to_llm_message(m) for m in state["messages"]]
    rsp = await provider.generate(msgs)
    return {"messages": [AIMessage(content=rsp.content)]}


def build_default_graph() -> CompiledStateGraph:
    """Compile the one-node chat graph."""
    graph = StateGraph(MessagesState)
    graph.add_node("chat", _chat_node)
    graph.add_edge(START, "chat")
    graph.add_edge("chat", END)
    return graph.compile()


__all__ = ["_to_llm_message", "build_default_graph"]
