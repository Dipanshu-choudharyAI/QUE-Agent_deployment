"""Phase 5 policy engine unit tests."""

from __future__ import annotations

from app.policy import (
    POLICY_DENY_CLARIFY,
    evaluate_tool_call,
    normalize_role,
)
from app.tools.select import select_tool


def test_normalize_role():
    assert normalize_role("teacher") == "teacher"
    assert normalize_role("Teacher") == "teacher"
    assert normalize_role("student") == "student"
    assert normalize_role("admin") == "admin"
    assert normalize_role("staff") == "admin"
    assert normalize_role("") is None
    assert normalize_role(None) is None
    assert normalize_role("hacker") is None


def test_teacher_allowed_read_tool():
    d = evaluate_tool_call(role="teacher", tool_name="summarize_my_exams")
    assert d.allow is True
    assert d.requires_confirmation is False
    assert d.reason == "allowed"


def test_admin_inherits_teacher_tools():
    d = evaluate_tool_call(role="admin", tool_name="diagnose_publish_blockers")
    assert d.allow is True


def test_student_denied():
    d = evaluate_tool_call(role="student", tool_name="summarize_my_exams")
    assert d.allow is False
    assert d.reason == "role_not_permitted"


def test_missing_role_denied():
    d = evaluate_tool_call(role=None, tool_name="summarize_my_exams")
    assert d.allow is False
    assert d.reason == "missing_or_unknown_role"


def test_unknown_tool_denied():
    d = evaluate_tool_call(role="teacher", tool_name="delete_everything")
    assert d.allow is False
    assert d.reason == "unknown_tool"


def test_select_student_denied_my_exams():
    sel = select_tool(
        query="How many exams are made by me?",
        ui_context={"current_page": "exams_list", "user_role": "student"},
    )
    assert sel.tool is None
    assert sel.reason.startswith("policy_denied")
    assert sel.clarify_prompt == POLICY_DENY_CLARIFY


def test_select_teacher_allowed_my_exams():
    sel = select_tool(
        query="How many exams are made by me?",
        ui_context={"current_page": "exams_list", "user_role": "teacher"},
    )
    assert sel.tool is not None
    assert sel.tool.name == "summarize_my_exams"
