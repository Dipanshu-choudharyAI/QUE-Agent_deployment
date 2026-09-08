"""Write-tool human-in-the-loop flow: propose -> confirm/cancel -> execute."""

from __future__ import annotations

import pytest

from app.orchestration.pending_actions import (
    get_pending,
    is_affirmative_reply,
    is_negative_reply,
    propose_action,
)


def _cfg(**overrides):
    from app.core.config import Settings

    base = dict(
        APP_ENV="local",
        QUE_TOOLS_ENABLED=True,
        QUIZZER_INTERNAL_BASE_URL="http://127.0.0.1:9",
        QUE_SERVICE_KEY="test-service-key-not-for-production",
        QUE_JWT_SECRET="test-que-jwt-secret-not-for-production-32c",
    )
    base.update(overrides)
    return Settings(**base)


def test_affirmative_and_negative_are_tight():
    assert is_affirmative_reply("yes")
    assert is_affirmative_reply("Yes, do it.")
    assert is_affirmative_reply("go ahead")
    assert not is_affirmative_reply("yes please also tell me a joke")
    assert not is_affirmative_reply("yesterday")

    assert is_negative_reply("no")
    assert is_negative_reply("cancel")
    assert is_negative_reply("never mind")
    assert not is_negative_reply("no problem, publish it")


@pytest.mark.asyncio
async def test_propose_stores_pending_action_and_returns_confirm_message():
    from app.tools.executor import invoke_tool_selection
    from app.tools.select import select_tool

    sel = select_tool(
        query="Publish this exam",
        ui_context={
            "current_page": "exam_workspace",
            "current_exam_id": "11111111-1111-1111-1111-111111111111",
            "user_role": "teacher",
        },
    )
    assert sel.tool is not None and sel.tool.name == "publish_exam"

    execution = await invoke_tool_selection(
        sel,
        user_id="teacher-1",
        request_id="req-1",
        ui_context={"user_role": "teacher"},
        conversation_id="conv-1",
        settings=_cfg(),
    )
    assert execution.confirmation_pending is True
    assert "TOOL_CONFIRM" in execution.system_message
    assert "Publish exam" in execution.system_message

    from app.graphs.memory import make_thread_id

    thread_key = make_thread_id("conv-1", "teacher-1")
    pending = get_pending(thread_key)
    assert pending is not None
    assert pending.tool_name == "publish_exam"
    assert pending.role == "teacher"


@pytest.mark.asyncio
async def test_execute_confirmed_write_action_success(monkeypatch):
    from app.tools import executor as executor_mod

    async def _fake_invoke_quizzer_tool(**kwargs):
        return {"ok": True, "data": {"exam_id": kwargs["args"]["exam_id"]}}

    monkeypatch.setattr(executor_mod, "invoke_quizzer_tool", _fake_invoke_quizzer_tool)

    pending = propose_action(
        thread_key="thread-x",
        tool_name="publish_exam",
        args={"exam_id": "11111111-1111-1111-1111-111111111111", "title": "Midterm"},
        user_id="teacher-1",
        role="teacher",
        confirmation_prompt="Publish exam 'Midterm' now?",
    )
    execution = await executor_mod.execute_confirmed_write_action(
        pending, request_id="req-2", settings=_cfg()
    )
    assert execution.error_code is None
    assert "Midterm" in (execution.final_reply or "")
    assert "Done" in (execution.final_reply or "")


@pytest.mark.asyncio
async def test_execute_confirmed_write_action_denies_wrong_role(monkeypatch):
    from app.tools import executor as executor_mod

    called = {"n": 0}

    async def _fake_invoke_quizzer_tool(**kwargs):
        called["n"] += 1
        return {"ok": True, "data": {}}

    monkeypatch.setattr(executor_mod, "invoke_quizzer_tool", _fake_invoke_quizzer_tool)

    pending = propose_action(
        thread_key="thread-y",
        tool_name="delete_draft_exam",
        args={"exam_id": "11111111-1111-1111-1111-111111111111", "title": "Old draft"},
        user_id="student-1",
        role="student",
        confirmation_prompt="Delete draft exam 'Old draft'?",
    )
    execution = await executor_mod.execute_confirmed_write_action(
        pending, request_id="req-3", settings=_cfg()
    )
    assert execution.error_code == "forbidden"
    assert called["n"] == 0
    assert "Nothing was changed" in (execution.final_reply or "")


@pytest.mark.asyncio
async def test_resolve_write_confirmation_yes_executes_and_no_cancels(monkeypatch):
    from app.orchestration import pipeline
    from app.schemas.chat import ChatMessage, ChatRequest
    from app.tools import executor as executor_mod

    async def _fake_invoke_quizzer_tool(**kwargs):
        return {"ok": True, "data": {}}

    monkeypatch.setattr(executor_mod, "invoke_quizzer_tool", _fake_invoke_quizzer_tool)

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="yes")],
        conversation_id="conv-yes",
        user_id="teacher-1",
    )
    decision = pipeline.decide_turn(request)
    from app.graphs.memory import make_thread_id

    real_key = make_thread_id("conv-yes", "teacher-1")
    propose_action(
        thread_key=real_key,
        tool_name="publish_exam",
        args={"exam_id": "11111111-1111-1111-1111-111111111111", "title": "Final"},
        user_id="teacher-1",
        role="teacher",
        confirmation_prompt="Publish exam 'Final' now?",
    )
    resolved = await pipeline.resolve_write_confirmation(decision, request, _cfg())
    assert resolved.early_reply is not None
    assert "Final" in resolved.early_reply
    assert get_pending(real_key) is None

    # Cancel path.
    request2 = ChatRequest(
        messages=[ChatMessage(role="user", content="no")],
        conversation_id="conv-no",
        user_id="teacher-1",
    )
    decision2 = pipeline.decide_turn(request2)
    key2 = make_thread_id("conv-no", "teacher-1")
    propose_action(
        thread_key=key2,
        tool_name="delete_draft_exam",
        args={"exam_id": "11111111-1111-1111-1111-111111111111", "title": "Draft"},
        user_id="teacher-1",
        role="teacher",
        confirmation_prompt="Delete draft exam 'Draft'?",
    )
    resolved2 = await pipeline.resolve_write_confirmation(decision2, request2, _cfg())
    assert resolved2.early_reply == "Cancelled — nothing was changed."
    assert get_pending(key2) is None


def test_write_tools_excluded_from_agent_mode():
    from app.orchestration.runtime_mode import decide_runtime_mode

    mode, reason, sel = decide_runtime_mode(
        query="Publish this exam and also tell me who needs coaching",
        raw_query="Publish this exam and also tell me who needs coaching",
        ui_context={
            "current_page": "exam_workspace",
            "current_exam_id": "11111111-1111-1111-1111-111111111111",
            "user_role": "teacher",
        },
        route="tool",
        data_need="live_tool",
        complexity="multi_step",
        settings=_cfg(),
    )
    assert mode == "workflow"
    assert sel is not None and sel.tool is not None and sel.tool.name == "publish_exam"
