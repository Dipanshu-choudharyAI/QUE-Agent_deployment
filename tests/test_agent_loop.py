"""Phase 7 runtime mode + bounded agent loop (no live Quizzer)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.orchestration.agent_loop import format_partial_note, run_agent_loop
from app.orchestration.runtime_mode import decide_runtime_mode
from app.orchestration.understanding import classify_request, is_multi_step_ask
from app.tools.select import select_tool

EXAM = "11111111-1111-1111-1111-111111111111"
MULTI_QUERY = "How many exams are made by me and how did this exam go?"
UI_TEACHER = {
    "current_page": "exam_results",
    "current_exam_id": EXAM,
    "user_role": "teacher",
}


def _settings(**overrides) -> Settings:
    payload = {
        "APP_ENV": "local",
        "QUE_TOOLS_ENABLED": True,
        "QUIZZER_INTERNAL_BASE_URL": "http://127.0.0.1:9",
        "QUE_SERVICE_KEY": "test-service-key-not-for-production",
        "QUE_JWT_SECRET": "test-que-jwt-secret-not-for-production-32c",
        "QUE_AGENT_MAX_STEPS": 3,
        "QUE_TOOL_MAX_CALLS": 2,
        "QUE_AGENT_MAX_EXECUTION_MS": 8000,
        "QUE_AGENT_MAX_TOOL_CHARS": 12000,
    }
    payload.update(overrides)
    return Settings(**payload)


def test_single_live_ask_is_workflow():
    u = classify_request("How many exams are made by me?")
    mode, reason, sel = decide_runtime_mode(
        query="How many exams are made by me?",
        ui_context={"current_page": "exams_list", "user_role": "teacher"},
        route=u.route,
        data_need=u.data_need,
        complexity=u.complexity,
        settings=_settings(),
    )
    assert mode == "workflow"
    assert sel is not None and sel.tool is not None
    assert sel.tool.name == "summarize_my_exams"


def test_multi_intent_ask_is_agent():
    assert is_multi_step_ask(MULTI_QUERY) is True
    u = classify_request(MULTI_QUERY)
    assert u.complexity == "multi_step"
    assert u.route == "tool"
    mode, reason, sel = decide_runtime_mode(
        query=MULTI_QUERY,
        ui_context=UI_TEACHER,
        route=u.route,
        data_need=u.data_need,
        complexity=u.complexity,
        settings=_settings(),
    )
    assert mode == "agent"
    assert reason == "multi_step"
    assert sel is not None and sel.tool is not None


def test_student_policy_deny_is_knowledge_not_agent():
    u = classify_request(MULTI_QUERY)
    mode, _reason, sel = decide_runtime_mode(
        query=MULTI_QUERY,
        ui_context={**UI_TEACHER, "user_role": "student"},
        route=u.route,
        data_need=u.data_need,
        complexity=u.complexity,
        settings=_settings(),
    )
    assert mode == "knowledge"
    assert sel is not None
    assert sel.reason.startswith("policy_denied")


def test_exclude_tools_picks_second_candidate():
    first = select_tool(query=MULTI_QUERY, ui_context=UI_TEACHER)
    assert first.tool is not None
    second = select_tool(
        query=MULTI_QUERY,
        ui_context=UI_TEACHER,
        exclude_tools={first.tool.name},
    )
    assert second.tool is not None
    assert second.tool.name != first.tool.name


@pytest.mark.asyncio
async def test_agent_loop_runs_two_tools():
    async def fake_invoke(*, tool, args, user_id, request_id, settings=None):
        return {"ok": True, "data": {"tool": tool, "n": 1}}

    with patch("app.tools.executor.invoke_quizzer_tool", new=AsyncMock(side_effect=fake_invoke)):
        result = await run_agent_loop(
            query=MULTI_QUERY,
            raw_query=MULTI_QUERY,
            ui_context=UI_TEACHER,
            user_id="u1",
            route="tool",
            settings=_settings(),
        )
    assert result.termination_reason == "converged"
    assert len(result.tools_used) == 2
    assert result.successful_count == 2
    assert all("TOOL_RESULT" in m for m in result.system_messages)


@pytest.mark.asyncio
async def test_agent_loop_step_limit_partial():
    async def fake_invoke(*, tool, args, user_id, request_id, settings=None):
        return {"ok": True, "data": {"tool": tool}}

    with patch("app.tools.executor.invoke_quizzer_tool", new=AsyncMock(side_effect=fake_invoke)):
        result = await run_agent_loop(
            query=MULTI_QUERY,
            raw_query=MULTI_QUERY,
            ui_context=UI_TEACHER,
            user_id="u1",
            route="tool",
            settings=_settings(QUE_AGENT_MAX_STEPS=1, QUE_TOOL_MAX_CALLS=2),
        )
    assert result.termination_reason == "step_limit"
    assert len(result.tools_used) == 1
    assert result.successful_count == 1
    assert any("AGENT_PARTIAL" in m and "step_limit" in m for m in result.system_messages)
    assert "step_limit" in format_partial_note("step_limit")


@pytest.mark.asyncio
async def test_agent_loop_call_limit_partial():
    async def fake_invoke(*, tool, args, user_id, request_id, settings=None):
        return {"ok": True, "data": {"tool": tool}}

    with patch("app.tools.executor.invoke_quizzer_tool", new=AsyncMock(side_effect=fake_invoke)):
        result = await run_agent_loop(
            query=MULTI_QUERY,
            raw_query=MULTI_QUERY,
            ui_context=UI_TEACHER,
            user_id="u1",
            route="tool",
            settings=_settings(QUE_AGENT_MAX_STEPS=3, QUE_TOOL_MAX_CALLS=1),
        )
    assert result.termination_reason == "call_limit"
    assert len(result.tools_used) == 1
    assert any("AGENT_PARTIAL" in m for m in result.system_messages)


@pytest.mark.asyncio
async def test_agent_loop_never_invokes_when_policy_denied():
    invoke = AsyncMock()
    with patch("app.tools.executor.invoke_quizzer_tool", new=invoke):
        result = await run_agent_loop(
            query=MULTI_QUERY,
            raw_query=MULTI_QUERY,
            ui_context={**UI_TEACHER, "user_role": "student"},
            user_id="u-student",
            route="tool",
            settings=_settings(),
        )
    invoke.assert_not_awaited()
    assert result.termination_reason in {"error", "clarify"}
    assert result.tools_used == []
