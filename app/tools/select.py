"""Deterministic insight-tool selector (not LLM tool-calling)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.orchestration.understanding import _norm as _product_norm
from app.tools.registry import REGISTRY, ToolSpec, get_tool


@dataclass(frozen=True)
class ToolSelection:
    tool: ToolSpec | None
    args: dict
    reason: str
    needs_clarify: bool = False
    clarify_prompt: str | None = None


_EXAM_ID_RE = re.compile(
    r"\b(?:exam|quiz)\s*(?:id\s*)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.I,
)
_ATTEMPT_ID_RE = re.compile(
    r"\b(?:attempt)\s*(?:id\s*)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.I,
)
_THRESHOLD_RE = re.compile(r"\b(?:below|under|less than)\s+(\d{1,3})\b", re.I)
_TITLE_TRAILING_RE = re.compile(
    r"\s*,?\s*(?:can you see (?:that|this|it)|please|right now)\s*$",
    re.I,
)
_TITLE_NOISE_RE = re.compile(
    r"\b(made|maded|created|create|by me|for me|please|can you|do you|did you|"
    r"see that|see this|see it)\b",
    re.I,
)
_COMMA_TITLE_RE = re.compile(
    r"(?:exam|quiz)\b[^,\n]*,\s*[\"']?([^\"'\n,?]+)\s*$",
    re.I,
)
_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:exam|quiz)\s+(?:titled|called|named)\s+[\"']?([^\"'\n,?]+)",
        re.I,
    ),
    _COMMA_TITLE_RE,
    re.compile(
        r"in\s+my\s+(?:one\s+)?(?:exam|quiz)\s+[\"']?([^\"'\n,?]+)",
        re.I,
    ),
    re.compile(
        r"(?:see|look\s+at|open|check|find|show\s+me)\s+(?:my\s+)?(?:one\s+)?"
        r"(?:exam|quiz)\s+[\"']?([^\"'\n,?]+)",
        re.I,
    ),
    re.compile(
        r"my\s+(?:one\s+)?(?:exam|quiz)\s+[\"']?([^\"'\n,?]+)",
        re.I,
    ),
)
_PLACEHOLDER_TITLES = frozenset(
    {
        "this",
        "that",
        "it",
        "them",
        "here",
        "one",
        "the",
        "my",
        "a",
        "an",
        "this exam",
        "that exam",
        "the exam",
        "my exam",
        "this quiz",
        "that quiz",
        "the quiz",
        "my quiz",
    }
)


def extract_exam_id(query: str, ui_context: dict | None) -> str | None:
    m = _EXAM_ID_RE.search(query or "")
    if m:
        return m.group(1)
    if ui_context:
        eid = str(ui_context.get("current_exam_id") or "").strip()
        if eid:
            return eid
    return None


def extract_attempt_id(query: str, ui_context: dict | None) -> str | None:
    m = _ATTEMPT_ID_RE.search(query or "")
    if m:
        return m.group(1)
    if ui_context:
        aid = str(ui_context.get("current_entity_id") or "").strip()
        if ui_context.get("current_entity_type") == "attempt" and aid:
            return aid
    return None


def extract_exam_title(query: str) -> str | None:
    """Pull a named exam title from wording like 'my exam AI vs ML'."""
    raw = query or ""
    for pat in _TITLE_PATTERNS:
        m = pat.search(raw)
        if not m:
            continue
        title = _clean_extracted_title(m.group(1))
        if title:
            return title
    return None


def _clean_extracted_title(raw: str) -> str | None:
    t = (raw or "").strip().strip("\"'`")
    t = re.sub(r"\s+", " ", t)
    t = _TITLE_TRAILING_RE.sub("", t).strip()
    t = t.rstrip(".,!?").strip()
    if len(t) < 2:
        return None
    if t.casefold() in _PLACEHOLDER_TITLES:
        return None
    if t.casefold() in {"exams", "quizzes", "status", "results", "blueprint"}:
        return None
    if _TITLE_NOISE_RE.search(t):
        return None
    if "?" in t:
        return None
    if len(t.split()) > 12:
        return None
    return t[:80]


def _is_see_exam_ask(q: str) -> bool:
    return any(
        p in q
        for p in (
            "can you see",
            "do you see",
            "could you see",
            "see my exam",
            "see that exam",
            "see this exam",
            "see my quiz",
            "see one exam",
            "did you see",
            "look at my exam",
            "look at this exam",
            "find my exam",
            "open my exam",
            "check my exam",
            "show me my exam",
            "exam titled",
            "exam called",
            "exam named",
            "quiz titled",
            "quiz called",
            "in my one exam",
            "in my exam",
        )
    )


def _looks_like_inventory_ask(q: str) -> bool:
    """True for bare exam/quiz *inventory* wording ("how many exams do I have").

    Used only as the last-resort ``tool_route_account`` fallback so unrelated
    live asks (class comparisons, roster questions, …) clarify honestly
    instead of silently answering with exam counts.
    """
    has_subject = any(w in q for w in ("exam", "quiz", "account"))
    has_inventory_word = any(
        w in q
        for w in ("how many", "count", "number of", "created", "made", "my exams", "my quizzes", "inventory")
    )
    return has_subject and has_inventory_word


def _is_dashboard_metrics_ask(q: str) -> bool:
    """True for Dashboard KPI asks — not Exams-list inventory."""
    if any(
        k in q
        for k in (
            "dashboard metric",
            "dashboard number",
            "dashboard kpi",
            "metrics on my dashboard",
            "numbers on my dashboard",
            "metric cards",
        )
    ):
        return True
    has_dashboard = "dashboard" in q
    has_metric = any(w in q for w in ("metric", "kpi", "pulse"))
    if has_dashboard and has_metric:
        return True
    if has_dashboard and "number" in q and not any(w in q for w in ("how many exam", "number of exam")):
        return True
    if any(p in q for p in ("my metrics", "my kpis", "the metrics")) and "exam" not in q and "quiz" not in q:
        return True
    return False


def select_tool(
    *,
    query: str,
    ui_context: dict | None = None,
    route: str | None = None,
    exclude_tools: set[str] | frozenset[str] | None = None,
) -> ToolSelection:
    """Pick at most one insight tool from query + Phase 3 UI context."""
    q = _product_norm(query)
    page = str((ui_context or {}).get("current_page") or "unknown")
    exam_id = extract_exam_id(query, ui_context)
    attempt_id = extract_attempt_id(query, ui_context)
    exam_title = extract_exam_title(query)
    args: dict = {}
    if exam_id:
        args["exam_id"] = exam_id
    if attempt_id:
        args["attempt_id"] = attempt_id
    thr = _THRESHOLD_RE.search(query or "")
    if thr:
        args["threshold"] = int(thr.group(1))

    excluded = {n for n in (exclude_tools or set()) if n}
    candidates: list[tuple[str, str, dict | None]] = []

    def _add(name: str, reason: str, extra: dict | None = None) -> None:
        candidates.append((name, reason, extra))

    # Page-aware + keyword rules (ordered). First non-excluded match wins.
    if any(
        k in q
        for k in (
            "how many exam",
            "how many quiz",
            "exams have i",
            "quizzes have i",
            "exams did i",
            "exams made",
            "exams created",
            "exam made by",
            "exams made by",
            "my exams",
            "count my exam",
            "number of exam",
            "how many have i created",
            "how many did i create",
        )
    ) or (
        "how many" in q
        and any(w in q for w in ("exam", "quiz"))
        and any(w in q for w in ("i", "my", "me", "made", "create", "created"))
        and not exam_title
    ):
        _add("summarize_my_exams", "my_exams_count")
    if _is_dashboard_metrics_ask(q):
        _add("summarize_dashboard_metrics", "dashboard_metrics")
    if exam_title and not (
        any(h in q for h in ("how do i", "how can i", "how to", "where is", "where do i"))
        and not _is_see_exam_ask(q)
    ):
        _add("lookup_my_exam", "named_exam_title", {"title": exam_title})
    # Write actions — explicit keyword-only, no page defaults (deliberately narrow;
    # these always go through a human confirmation turn before Quizzer is called).
    # "how do I publish" / "why can't I publish" must stay how-to / diagnose, never
    # an executed write action.
    _how_or_why = any(
        h in q
        for h in ("how do i", "how can i", "how to", "where is", "where do i", "why", "what")
    )
    if (
        any(
            k in q
            for k in ("publish this exam", "publish this quiz", "publish my exam", "publish the exam")
        )
        or (
            "publish" in q
            and any(w in q for w in ("this", "my", "the"))
            and any(w in q for w in ("exam", "quiz"))
        )
    ) and (exam_id or exam_title) and not _how_or_why and not any(
        w in q for w in ("can't", "cannot", "won't", "unable", "blocked")
    ):
        _add("publish_exam", "publish_exam_action", {**args, "title": exam_title or args.get("title")})
    if any(
        k in q
        for k in (
            "notify students",
            "notify the students",
            "remind students",
            "remind the students",
            "send a reminder",
            "send reminder",
            "send students a reminder",
        )
    ) and (exam_id or exam_title) and not _how_or_why:
        _add("notify_students", "notify_students_action", {**args, "title": exam_title or args.get("title")})
    if any(
        k in q
        for k in (
            "delete this exam",
            "delete this quiz",
            "delete the draft",
            "delete my draft",
            "delete draft exam",
            "delete this draft",
        )
    ) and (exam_id or exam_title) and not _how_or_why:
        _add("delete_draft_exam", "delete_draft_action", {**args, "title": exam_title or args.get("title")})
    if any(k in q for k in ("empty analytics", "analytics empty", "no data in analytics", "why is analytics")):
        _add("diagnose_empty_analytics", "empty_analytics")
    if any(k in q for k in ("resume", "where did i leave", "continue creating", "creation session")):
        _add("resume_creation_guidance", "resume_creation")
    if any(
        k in q
        for k in (
            "who needs",
            "follow up",
            "coaching",
            "coach students",
            "struggling student",
            "needs help",
            "needs coaching",
        )
    ):
        if exam_id or page == "exam_results":
            _add("coach_students_needing_help", "coach_results")
        else:
            _add("prioritize_student_coaching", "coach_roster")
    if any(k in q for k in ("integrity", "violation", "cheating", "tab switch")) and attempt_id:
        _add("explain_integrity_attempt", "integrity_attempt")
    if any(k in q for k in ("integrity setting", "reduce cheating", "proctor")):
        _add("recommend_integrity_settings", "integrity_settings")
    if any(
        k in q
        for k in (
            "can't publish",
            "cannot publish",
            "can't i publish",
            "why publish",
            "publish blocked",
            "won't publish",
            "unable to publish",
            "fail to publish",
        )
    ) or ("publish" in q and any(w in q for w in ("why", "can't", "cannot", "won't", "unable", "blocked"))):
        _add("diagnose_publish_blockers", "publish_blockers")
    if any(k in q for k in ("improve", "better exam", "make this exam better", "recommend")) and (
        exam_id or page in {"exam_workspace", "create_exam"}
    ):
        _add("recommend_exam_improvements", "improve_exam")
    if any(k in q for k in ("what should i do", "next step", "after results", "post exam")):
        _add("recommend_post_exam_actions", "post_exam")
    if any(k in q for k in ("how did", "summary of results", "summarize results", "how did this exam")):
        _add("summarize_exam_results", "results_summary")
    if any(k in q for k in ("exam status", "status of this", "explain this exam status", "where am i with")) or (
        "where am i" in q and (exam_id or page == "exam_workspace")
    ):
        _add("explain_exam_status", "exam_status")
    if any(k in q for k in ("what's in this exam", "explain this exam", "blueprint", "question mix")):
        _add("summarize_exam_blueprint", "blueprint")
    if any(k in q for k in ("weak question", "arena question", "hardest question", "item analysis")):
        _add("analyze_arena_weak_questions", "arena_weak")
    if any(k in q for k in ("live exam", "monitoring", "in progress", "who's taking")):
        _add("summarize_live_exam_health", "live_health")
    if _is_see_exam_ask(q) and exam_id:
        _add("explain_exam_status", "see_current_exam")
    if page == "exam_workspace" and exam_id:
        _add("explain_exam_status", "page_exam_status")
    if page == "exam_results" and exam_id:
        _add("summarize_exam_results", "page_results_default")
    if page == "analytics":
        _add("diagnose_empty_analytics", "page_analytics")
    if page == "monitoring":
        _add("summarize_live_exam_health", "page_monitoring")
    if page == "arena":
        _add("analyze_arena_weak_questions", "page_arena")
    if page in {"create_exam"}:
        _add("resume_creation_guidance", "page_create")
    if page in {"exams_list", "dashboard"} and any(
        w in q for w in ("how many", "count", "my exam", "created")
    ) and not _is_see_exam_ask(q):
        _add("summarize_my_exams", "page_exams_count")
    if route == "tool" and exam_id:
        _add("explain_exam_status", "tool_route_fallback")
    if route == "tool" and _is_dashboard_metrics_ask(q):
        _add("summarize_dashboard_metrics", "tool_route_dashboard")
    if route == "tool" and not _is_see_exam_ask(q) and _looks_like_inventory_ask(q):
        # Prefer account inventory over analytics diagnosis for bare live-data asks
        # that are actually shaped like an exam-count/inventory question. Anything
        # else (e.g. "compare results for class X") falls through to an honest
        # clarify instead of silently answering with the wrong tool.
        _add("summarize_my_exams", "tool_route_account")

    name: str | None = None
    reason = "default"
    extra_args: dict | None = None
    for cand_name, cand_reason, extra in candidates:
        if cand_name in excluded:
            continue
        name, reason, extra_args = cand_name, cand_reason, extra
        break

    if extra_args is not None:
        args = extra_args

    if not name:
        return ToolSelection(
            tool=None,
            args=args,
            reason="no_match",
            needs_clarify=True,
            clarify_prompt=(
                "Tell me which exam you mean (or open it in Quizzer), "
                "and whether you want status, results coaching, publish help, or improvements."
            ),
        )

    spec = get_tool(name)
    assert spec is not None
    if spec.requires_exam_id and not args.get("exam_id"):
        return ToolSelection(
            tool=None,
            args=args,
            reason="missing_exam_id",
            needs_clarify=True,
            clarify_prompt="Open the exam in Quizzer or paste the exam id so I can pull live details.",
        )
    if spec.requires_attempt_id and not args.get("attempt_id"):
        return ToolSelection(
            tool=None,
            args=args,
            reason="missing_attempt_id",
            needs_clarify=True,
            clarify_prompt="Which attempt should I inspect? Paste the attempt id from Results.",
        )

    # Phase 5: when UI context carries a role, filter before invoke (don't leak tool names).
    from app.policy.engine import POLICY_DENY_CLARIFY, evaluate_tool_call

    raw_role = None
    if ui_context:
        raw_role = ui_context.get("user_role")
    if raw_role is not None and str(raw_role).strip() != "":
        decision = evaluate_tool_call(role=str(raw_role), tool_name=spec.name, risk_tier=spec.risk_tier)
        if not decision.allow:
            return ToolSelection(
                tool=None,
                args=args,
                reason=f"policy_denied:{decision.reason}",
                needs_clarify=True,
                clarify_prompt=POLICY_DENY_CLARIFY,
            )

    return ToolSelection(tool=spec, args=args, reason=reason)


def select_tool_prefer_raw(
    *,
    raw_query: str | None,
    resolved_query: str | None,
    ui_context: dict | None = None,
    route: str | None = None,
    exclude_tools: set[str] | frozenset[str] | None = None,
) -> ToolSelection:
    """Prefer the latest user wording when it already selects a tool.

    Avoids follow-up resolve gluing an older ask onto a new live-data question.
    """
    raw = (raw_query or "").strip()
    resolved = (resolved_query or "").strip()
    if raw:
        sel = select_tool(
            query=raw,
            ui_context=ui_context,
            route=route,
            exclude_tools=exclude_tools,
        )
        if sel.tool is not None and not sel.needs_clarify:
            return sel
    if resolved and resolved != raw:
        return select_tool(
            query=resolved,
            ui_context=ui_context,
            route=route,
            exclude_tools=exclude_tools,
        )
    if raw:
        return select_tool(
            query=raw,
            ui_context=ui_context,
            route=route,
            exclude_tools=exclude_tools,
        )
    return select_tool(
        query=resolved or "",
        ui_context=ui_context,
        route=route,
        exclude_tools=exclude_tools,
    )


def all_tool_names() -> list[str]:
    return sorted(REGISTRY.keys())
