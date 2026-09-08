"""Phase 4 tool selector unit tests (no network)."""

from __future__ import annotations

from app.tools.select import select_tool


def test_select_results_summary_with_exam_context():
    sel = select_tool(
        query="How did this exam go?",
        ui_context={"current_page": "exam_results", "current_exam_id": "11111111-1111-1111-1111-111111111111"},
    )
    assert sel.tool is not None
    assert sel.tool.name == "summarize_exam_results"
    assert sel.args["exam_id"].startswith("11111111")


def test_select_publish_blockers():
    sel = select_tool(
        query="Why can't I publish?",
        ui_context={"current_page": "exam_workspace", "current_exam_id": "11111111-1111-1111-1111-111111111111"},
    )
    assert sel.tool is not None
    assert sel.tool.name == "diagnose_publish_blockers"


def test_select_improve_exam():
    sel = select_tool(
        query="How do I make this exam better?",
        ui_context={"current_page": "exam_workspace", "current_exam_id": "11111111-1111-1111-1111-111111111111"},
    )
    assert sel.tool is not None
    assert sel.tool.name == "recommend_exam_improvements"


def test_select_empty_analytics():
    sel = select_tool(query="Why is Analytics empty?", ui_context={"current_page": "analytics"})
    assert sel.tool is not None
    assert sel.tool.name == "diagnose_empty_analytics"


def test_select_clarify_without_exam_id():
    sel = select_tool(query="How did this exam go?", ui_context={"current_page": "dashboard"})
    assert sel.needs_clarify or (sel.tool and sel.tool.name != "summarize_exam_results")


def test_select_coach_students():
    sel = select_tool(
        query="Who needs help after this exam?",
        ui_context={"current_page": "exam_results", "current_exam_id": "11111111-1111-1111-1111-111111111111"},
    )
    assert sel.tool is not None
    assert sel.tool.name == "coach_students_needing_help"


def test_select_resume_creation():
    sel = select_tool(query="Where did I leave off creating?", ui_context={"current_page": "create_exam"})
    assert sel.tool is not None
    assert sel.tool.name == "resume_creation_guidance"


def test_select_my_exams_count():
    sel = select_tool(
        query="How many exams are made by me?",
        ui_context={"current_page": "exams_list", "user_role": "teacher"},
    )
    assert sel.tool is not None
    assert sel.tool.name == "summarize_my_exams"
    assert not sel.needs_clarify


def test_select_student_cannot_use_teacher_tools():
    sel = select_tool(
        query="How many exams are made by me?",
        ui_context={"current_page": "exams_list", "user_role": "student"},
    )
    assert sel.tool is None
    assert sel.reason.startswith("policy_denied")


def test_select_dashboard_metrics_not_exam_inventory():
    sel = select_tool(
        query="I want to ask about my metrics numbers of my Dashbaord",
        ui_context={"current_page": "arena", "user_role": "teacher"},
        route="tool",
    )
    assert sel.tool is not None
    assert sel.tool.name == "summarize_dashboard_metrics"
    assert not sel.needs_clarify


def test_select_how_many_exams_still_inventory():
    sel = select_tool(
        query="How many exams have I created?",
        ui_context={"current_page": "dashboard", "user_role": "teacher"},
    )
    assert sel.tool is not None
    assert sel.tool.name == "summarize_my_exams"


def test_select_named_exam_lookup_without_uuid():
    sel = select_tool(
        query="In my one exam AI vs ML, Can you see that",
        ui_context={"current_page": "dashboard", "user_role": "teacher"},
    )
    assert sel.tool is not None
    assert sel.tool.name == "lookup_my_exam"
    assert sel.args.get("title") == "AI vs ML"
    assert not sel.needs_clarify


def test_select_exam_titled_lookup():
    sel = select_tool(
        query='Can you see my exam titled "AI vs ML"?',
        ui_context={"current_page": "exams_list", "user_role": "teacher"},
    )
    assert sel.tool is not None
    assert sel.tool.name == "lookup_my_exam"
    assert sel.args.get("title") == "AI vs ML"


def test_select_see_this_exam_uses_open_exam():
    sel = select_tool(
        query="Can you see this exam?",
        ui_context={
            "current_page": "exam_workspace",
            "current_exam_id": "11111111-1111-1111-1111-111111111111",
            "user_role": "teacher",
        },
    )
    assert sel.tool is not None
    assert sel.tool.name == "explain_exam_status"
    assert sel.args["exam_id"].startswith("11111111")


def test_select_monitoring_page_default():
    sel = select_tool(query="is everything ok", ui_context={"current_page": "monitoring", "user_role": "teacher"})
    assert sel.tool is not None
    assert sel.tool.name == "summarize_live_exam_health"


def test_select_arena_page_default():
    # Arena is always scoped to one quiz battle — Quizzer stamps
    # current_exam_id in ui_context whenever the user is on this page.
    sel = select_tool(
        query="how's this going",
        ui_context={
            "current_page": "arena",
            "current_exam_id": "11111111-1111-1111-1111-111111111111",
            "user_role": "teacher",
        },
    )
    assert sel.tool is not None
    assert sel.tool.name == "analyze_arena_weak_questions"


def test_select_arena_page_default_without_exam_id_asks_to_clarify():
    # No exam id in context (e.g. arena landing list) — must clarify, never
    # invent a target exam.
    sel = select_tool(query="how's this going", ui_context={"current_page": "arena", "user_role": "teacher"})
    assert sel.tool is None
    assert sel.needs_clarify is True


def test_select_tool_route_account_requires_inventory_shape():
    # Bare live ask with no inventory wording should clarify, not silently
    # answer with exam counts.
    sel = select_tool(
        query="compare results for my two classes",
        ui_context={"current_page": "dashboard", "user_role": "teacher"},
        route="tool",
    )
    assert sel.tool is None or sel.tool.name != "summarize_my_exams"


def test_select_tool_route_account_still_matches_inventory_wording():
    sel = select_tool(
        query="tell me the exam count",
        ui_context={"current_page": "dashboard", "user_role": "teacher"},
        route="tool",
    )
    assert sel.tool is not None
    assert sel.tool.name == "summarize_my_exams"


def test_select_publish_exam_write_action():
    sel = select_tool(
        query="Publish this exam",
        ui_context={
            "current_page": "exam_workspace",
            "current_exam_id": "11111111-1111-1111-1111-111111111111",
            "user_role": "teacher",
        },
    )
    assert sel.tool is not None
    assert sel.tool.name == "publish_exam"


def test_select_how_to_publish_is_not_a_write_action():
    sel = select_tool(
        query="How do I publish this exam?",
        ui_context={
            "current_page": "exam_workspace",
            "current_exam_id": "11111111-1111-1111-1111-111111111111",
            "user_role": "teacher",
        },
    )
    assert sel.tool is None or sel.tool.name != "publish_exam"


def test_select_delete_draft_exam_write_action():
    sel = select_tool(
        query="Delete this draft exam",
        ui_context={
            "current_page": "exam_workspace",
            "current_exam_id": "11111111-1111-1111-1111-111111111111",
            "user_role": "teacher",
        },
    )
    assert sel.tool is not None
    assert sel.tool.name == "delete_draft_exam"


def test_select_notify_students_write_action():
    sel = select_tool(
        query="Send a reminder to students for this exam",
        ui_context={
            "current_page": "exam_workspace",
            "current_exam_id": "11111111-1111-1111-1111-111111111111",
            "user_role": "teacher",
        },
    )
    assert sel.tool is not None
    assert sel.tool.name == "notify_students"


def test_select_named_exam_after_made_by_me_clause():
    sel = select_tool(
        query="Did you see one exam maded by me ,AI vs ML",
        ui_context={"current_page": "dashboard", "user_role": "teacher"},
    )
    assert sel.tool is not None
    assert sel.tool.name == "lookup_my_exam"
    assert sel.args.get("title") == "AI vs ML"
    assert not sel.needs_clarify
