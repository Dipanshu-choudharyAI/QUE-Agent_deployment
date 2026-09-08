"""Tests for user-visible agent status labels."""

from app.orchestration.agent_status import status_event, tool_status_label


def test_tool_status_label_known():
    assert "students" in tool_status_label("coach_students_needing_help").casefold()
    assert "publish" in tool_status_label("diagnose_publish_blockers").casefold()
    assert "exam" in tool_status_label("lookup_my_exam").casefold()


def test_tool_status_label_fallback():
    assert tool_status_label(None)
    assert "Quizzer" in tool_status_label("unknown_tool_xyz")


def test_status_event_shape():
    ev = status_event(stage="tool", label="Checking…", tool="explain_exam_status")
    assert ev["type"] == "status"
    assert ev["stage"] == "tool"
    assert ev["tool"] == "explain_exam_status"
