"""Compile the QUE conversational agent graph.

Topology:

    START → prepare → context → route
                         ├─ tools → generate → END   (workflow, one tool)
                         ├─ agent → generate → END   (bounded multi-tool)
                         └─ knowledge → generate → END

Short-term memory: compiled with LangGraph MemorySaver; pass
``config={"configurable": {"thread_id": ...}}`` so ``dialog`` persists
across turns for the same conversation.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.graphs.memory import get_checkpointer, memory_enabled
from app.graphs.nodes import (
    agent_node,
    context_node,
    generate_node,
    knowledge_node,
    prepare_node,
    tools_node,
)
from app.graphs.state import QueGraphState


def _route_after_context(state: QueGraphState) -> Literal["tools", "agent", "knowledge"]:
    mode = (state.get("runtime_mode") or "").strip()
    if mode == "agent":
        return "agent"
    if mode == "workflow":
        return "tools"
    return "knowledge"


def build_que_graph(*, with_memory: bool | None = None):
    graph = StateGraph(QueGraphState)
    graph.add_node("prepare", prepare_node)
    graph.add_node("context", context_node)
    graph.add_node("tools", tools_node)
    graph.add_node("agent", agent_node)
    graph.add_node("knowledge", knowledge_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "context")
    graph.add_conditional_edges(
        "context",
        _route_after_context,
        {"tools": "tools", "agent": "agent", "knowledge": "knowledge"},
    )
    graph.add_edge("tools", "generate")
    graph.add_edge("agent", "generate")
    graph.add_edge("knowledge", "generate")
    graph.add_edge("generate", END)

    use_memory = memory_enabled() if with_memory is None else with_memory
    if use_memory:
        return graph.compile(checkpointer=get_checkpointer())
    return graph.compile()


@lru_cache
def get_que_graph():
    """Process-wide compiled graph (with in-process short-term memory)."""
    return build_que_graph()
