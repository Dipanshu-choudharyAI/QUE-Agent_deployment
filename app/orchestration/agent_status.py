"""User-visible agent activity labels for SSE status events."""

from __future__ import annotations

from app.tools.registry import get_tool

# Tool → short live status (present continuous).
_TOOL_STATUS: dict[str, str] = {
    "explain_exam_status": "Checking this exam's status…",
    "summarize_exam_blueprint": "Reviewing this exam's questions…",
    "recommend_exam_improvements": "Looking for ways to improve this exam…",
    "diagnose_publish_blockers": "Checking why publish is blocked…",
    "recommend_integrity_settings": "Reviewing integrity settings…",
    "summarize_exam_results": "Pulling exam results…",
    "coach_students_needing_help": "Looking at students who need help…",
    "explain_integrity_attempt": "Checking integrity for this attempt…",
    "recommend_post_exam_actions": "Planning next steps from results…",
    "summarize_live_exam_health": "Checking live exams…",
    "diagnose_empty_analytics": "Checking why Analytics is empty…",
    "prioritize_student_coaching": "Reviewing students across your account…",
    "analyze_arena_weak_questions": "Analyzing weak Arena questions…",
    "resume_creation_guidance": "Checking where you left off creating…",
    "summarize_my_exams": "Counting exams in your account…",
    "summarize_dashboard_metrics": "Reading your Dashboard metrics…",
    "lookup_my_exam": "Looking up that exam in your account…",
}


def tool_status_label(tool_name: str | None) -> str:
    if not tool_name:
        return "Checking your Quizzer data…"
    if tool_name in _TOOL_STATUS:
        return _TOOL_STATUS[tool_name]
    spec = get_tool(tool_name)
    if spec:
        return f"{spec.description.rstrip('.')}…"
    return "Checking your Quizzer data…"


def status_event(
    *,
    stage: str,
    label: str,
    tool: str | None = None,
    step: int | None = None,
) -> dict:
    payload: dict = {"type": "status", "stage": stage, "label": label}
    if tool:
        payload["tool"] = tool
    if step is not None:
        payload["step"] = step
    return payload
