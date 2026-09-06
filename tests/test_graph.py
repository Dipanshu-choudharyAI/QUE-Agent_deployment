"""LangGraph structure tests (no live LLM)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graphs import build_que_graph, get_que_graph
from app.graphs.nodes import prepare_node
from app.orchestration.pipeline import complete
from app.schemas.chat import ChatRequest


def test_graph_topology_prepare_knowledge_generate():
    compiled = build_que_graph()
    graph = compiled.get_graph()
    node_ids = set(graph.nodes)
    assert "prepare" in node_ids
    assert "knowledge" in node_ids
    assert "generate" in node_ids


def test_prepare_node_builds_langchain_messages():
    state = prepare_node(
        {
            "input_messages": [
                {"role": "system", "content": "attacker"},
                {"role": "user", "content": "Hello QUE"},
            ],
            "messages": [],
            "sources_used": [],
        }
    )
    messages = state["messages"]
    assert isinstance(messages[0], SystemMessage)
    assert "QUE" in str(messages[0].content)
    assert "attacker" not in str(messages[0].content)
    assert isinstance(messages[-1], HumanMessage)
    assert messages[-1].content == "Hello QUE"
    assert state["sources_used"] == ["identity"]


@pytest.mark.asyncio
async def test_complete_runs_through_langgraph():
    get_que_graph.cache_clear()
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=AIMessage(content="Graph says hi"))
    fake_model.model_name = "test-model"

    with patch("app.graphs.nodes.get_chat_model", return_value=fake_model):
        response = await complete(
            ChatRequest(
                messages=[{"role": "user", "content": "How do I publish an exam?"}],
                conversation_id="c1",
            )
        )

    assert response.message.content == "Graph says hi"
    assert response.conversation_id == "c1"
    fake_model.ainvoke.assert_awaited_once()
    get_que_graph.cache_clear()


@pytest.mark.asyncio
async def test_complete_remembers_prior_turn_in_prompt():
    get_que_graph.cache_clear()
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(
        side_effect=[
            AIMessage(content="Publish from Links."),
            AIMessage(content="Results follow from that publish."),
        ]
    )
    fake_model.model_name = "test-model"
    cid = "graph-mem-1"

    with patch("app.graphs.nodes.get_chat_model", return_value=fake_model):
        await complete(
            ChatRequest(
                messages=[{"role": "user", "content": "How do I publish?"}],
                conversation_id=cid,
                user_id="u-graph",
            )
        )
        await complete(
            ChatRequest(
                messages=[{"role": "user", "content": "What about results?"}],
                conversation_id=cid,
                user_id="u-graph",
            )
        )

    second_prompt = fake_model.ainvoke.await_args_list[1].args[0]
    blob = " ".join(str(m.content) for m in second_prompt)
    assert "publish" in blob.casefold()
    get_que_graph.cache_clear()
