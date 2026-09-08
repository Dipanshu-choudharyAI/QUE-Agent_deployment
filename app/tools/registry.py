"""Tool registry — insight workflows (read) + confirmed write actions.

Write tools (``risk_tier="write"``) always require an explicit human
confirmation turn (see ``app/orchestration/pending_actions.py`` and
``app/tools/executor.py``) before Quizzer is ever called. They are never
reachable from the bounded agent loop — only the single-tool workflow path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    requires_exam_id: bool = False
    requires_attempt_id: bool = False
    risk_tier: str = "read"
    roles: tuple[str, ...] = ("teacher", "admin")
    coaching_hint: str = (
        "Coach the teacher with concrete next actions. "
        "Only use numbers and facts present in TOOL_RESULT. Do not invent counts."
    )
    # Write tools only — filled with {title} and shown verbatim before executing.
    confirmation_prompt: str | None = None
    # Write tools only — filled with {title} on a successful TOOL_RESULT.
    success_template: str | None = None


REGISTRY: dict[str, ToolSpec] = {
    "explain_exam_status": ToolSpec(
        "explain_exam_status",
        "Explain this exam's status and the single best next step",
        requires_exam_id=True,
    ),
    "summarize_exam_blueprint": ToolSpec(
        "summarize_exam_blueprint",
        "Summarize question mix and balance for this exam",
        requires_exam_id=True,
    ),
    "recommend_exam_improvements": ToolSpec(
        "recommend_exam_improvements",
        "Recommend how to improve this exam for better outcomes",
        requires_exam_id=True,
        coaching_hint=(
            "Give ranked recommendations tied to TOOL_RESULT.recommendations. "
            "Only cite facts from TOOL_RESULT."
        ),
    ),
    "diagnose_publish_blockers": ToolSpec(
        "diagnose_publish_blockers",
        "Diagnose why publish is blocked",
        requires_exam_id=True,
    ),
    "recommend_integrity_settings": ToolSpec(
        "recommend_integrity_settings",
        "Recommend integrity/proctoring settings gaps",
        requires_exam_id=True,
    ),
    "summarize_exam_results": ToolSpec(
        "summarize_exam_results",
        "Summarize how the exam cohort performed",
        requires_exam_id=True,
    ),
    "coach_students_needing_help": ToolSpec(
        "coach_students_needing_help",
        "Prioritize which students need follow-up",
        requires_exam_id=True,
    ),
    "explain_integrity_attempt": ToolSpec(
        "explain_integrity_attempt",
        "Explain integrity events for one attempt",
        requires_exam_id=True,
        requires_attempt_id=True,
    ),
    "recommend_post_exam_actions": ToolSpec(
        "recommend_post_exam_actions",
        "Recommend what to do after seeing results",
        requires_exam_id=True,
    ),
    "summarize_live_exam_health": ToolSpec(
        "summarize_live_exam_health",
        "Summarize live in-progress exam health",
        requires_exam_id=False,
    ),
    "diagnose_empty_analytics": ToolSpec(
        "diagnose_empty_analytics",
        "Diagnose why Analytics looks empty",
        requires_exam_id=False,
    ),
    "prioritize_student_coaching": ToolSpec(
        "prioritize_student_coaching",
        "Prioritize students needing coaching across exams",
        requires_exam_id=False,
    ),
    "analyze_arena_weak_questions": ToolSpec(
        "analyze_arena_weak_questions",
        "Analyze weak Arena questions for this quiz",
        requires_exam_id=True,
    ),
    "resume_creation_guidance": ToolSpec(
        "resume_creation_guidance",
        "Guide the user to resume exam creation",
        requires_exam_id=False,
    ),
    "summarize_my_exams": ToolSpec(
        "summarize_my_exams",
        "Count exams created by this user (published vs draft)",
        requires_exam_id=False,
        coaching_hint=(
            "Answer with the exact exam_count / published_count / draft_count from TOOL_RESULT. "
            "Do not invent numbers. Mention Arena packs only if arena_pack_count is present and > 0."
        ),
    ),
    "summarize_dashboard_metrics": ToolSpec(
        "summarize_dashboard_metrics",
        "Summarize the four Dashboard KPI cards (active now, attempts 7d, avg score 7d, AI jobs)",
        requires_exam_id=False,
        coaching_hint=(
            "These numbers are the Dashboard metric cards, not the Exams list. "
            "Report active_right_now, attempts_7d, avg_score_7d, and ai_jobs_running from TOOL_RESULT. "
            "Do not substitute exam_count / published / draft. Do not invent numbers."
        ),
    ),
    "lookup_my_exam": ToolSpec(
        "lookup_my_exam",
        "Find this user's exam by title and report whether it exists plus its status",
        requires_exam_id=False,
        coaching_hint=(
            "You looked up their exams. If match_count is 1, confirm you can see that exam: "
            "use title, status, question_count, approved_question_count, blockers, and suggested_actions. "
            "If match_count is 0, say you found no exam with that title — do not invent one. "
            "If match_count > 1, list matching titles and ask which exam they mean. "
            "Never say you cannot see their exam when TOOL_RESULT is present."
        ),
    ),
    # --- Write tools (risk_tier="write") — always confirmed by the user first. ---
    "publish_exam": ToolSpec(
        "publish_exam",
        "Publish an exam so students can see and attempt it",
        requires_exam_id=True,
        risk_tier="write",
        confirmation_prompt=(
            "Publish exam '{title}' now? Students will be able to see and attempt it "
            "once it opens. Reply **yes** to publish or **no** to cancel."
        ),
        success_template="Done — published '{title}'. Students can see it once it opens.",
        coaching_hint=(
            "This is a confirmed write action, already executed. Only report exactly what "
            "TOOL_RESULT says happened — never claim the exam was published unless "
            "TOOL_RESULT.ok is true."
        ),
    ),
    "notify_students": ToolSpec(
        "notify_students",
        "Send a reminder notification to students enrolled in an exam",
        requires_exam_id=True,
        risk_tier="write",
        confirmation_prompt=(
            "Send a reminder notification to students enrolled in '{title}'? "
            "Reply **yes** to send or **no** to cancel."
        ),
        success_template="Done — sent a reminder to students enrolled in '{title}'.",
        coaching_hint=(
            "This is a confirmed write action, already executed. Only report exactly what "
            "TOOL_RESULT says happened — never claim a reminder was sent unless "
            "TOOL_RESULT.ok is true."
        ),
    ),
    "delete_draft_exam": ToolSpec(
        "delete_draft_exam",
        "Permanently delete a draft (unpublished) exam",
        requires_exam_id=True,
        risk_tier="write",
        confirmation_prompt=(
            "Permanently delete draft exam '{title}'? This cannot be undone and only works "
            "while it is still a draft. Reply **yes** to delete or **no** to cancel."
        ),
        success_template="Done — deleted draft '{title}'. This can't be undone.",
        coaching_hint=(
            "This is a confirmed write action, already executed. Only report exactly what "
            "TOOL_RESULT says happened — never claim the exam was deleted unless "
            "TOOL_RESULT.ok is true."
        ),
    ),
}

WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    name for name, spec in REGISTRY.items() if spec.risk_tier != "read"
)


def get_tool(name: str) -> ToolSpec | None:
    return REGISTRY.get(name)
