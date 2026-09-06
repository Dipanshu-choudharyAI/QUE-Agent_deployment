"""Request Understanding — classify each turn before RAG / tools / LLM.

Phase 1 foundation (handbook): scope, intent, risk, freshness, data need,
and complexity. Rule-based and cheap so every later router can read one object
instead of re-parsing the user text.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

Scope = Literal["in_scope", "out_of_scope", "clarification"]
Intent = Literal[
    "chitchat",
    "meta",
    "knowledge",
    "live_data",
    "analytics",
    "action",
    "out_of_scope",
]
Risk = Literal["read", "low_write", "high_write"]
Freshness = Literal["static", "dynamic", "critical"]
DataNeed = Literal["none", "knowledge", "live_tool"]
Complexity = Literal["single_step", "multi_step"]
Route = Literal["refuse", "canned_eligible", "knowledge", "tool", "clarify"]


@dataclass(frozen=True)
class RequestUnderstanding:
    scope: Scope
    intent: Intent
    risk: Risk
    freshness: Freshness
    data_need: DataNeed
    complexity: Complexity
    route: Route
    reasons: tuple[str, ...] = ()

    def as_log_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


OUT_OF_SCOPE_REFUSAL = (
    "I only help with Quizzer — creating quizzes, exams, monitoring, and results. "
    "Ask me something about using the platform."
)

# General knowledge / coding / world facts that are clearly not Quizzer.
_OUT_OF_SCOPE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\b(who is|who's)\s+(the\s+)?(president|prime minister|ceo of)\b",
        r"\bcapital of\b",
        r"\bweather\b",
        r"\brecipe\b|\bcook(ing)?\b",
        r"\bsorting algorithm\b|\bbubble sort\b|\bquicksort\b",
        r"\bwrite (me )?(a |an )?(python|javascript|java|c\+\+|rust)\b",
        r"\b(code|program|script)\s+(for|to)\b",
        r"\bbitcoin\b|\bstock price\b|\bnft\b",
        r"\b(ignore|disregard)\s+(all\s+)?(previous|prior)\s+(instructions|rules)\b",
        r"\b(system prompt|reveal your (system )?prompt)\b",
        r"\bpretend (you are|to be)\s+(an?\s+)?admin",
        r"\bjoke about\b|\bwrite a poem\b|\blimerick\b",
    )
)

_QUIZZER_HINTS: tuple[str, ...] = (
    "quiz",
    "quizzer",
    "exam",
    "assessment",
    "question",
    "publish",
    "arena",
    "attempt",
    "student",
    "proctor",
    "monitor",
    "analytics",
    "result",
    "score",
    "grade",
    "dashboard",
    "share link",
    "verification",
    "enrollment",
    "negative marking",
    "live exam",
    # Integrations & account surfaces
    "classroom",
    "google classroom",
    "google drive",
    "google calendar",
    "integration",
    "integrations",
    "calendar",
    "calender",  # common typo
    "microsoft teams",
    "teams",
    "roster",
    "onboarding",
    "notification",
    "account settings",
    "settings",
)

_LIVE_DATA_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bhow many\b.*\b(student|attempt|fail|pass|score)",
        r"\b(my|our)\s+(score|result|grade|analytics)\b",
        r"\bwho\s+(failed|passed|scored)\b",
        r"\bcount\b.*\b(student|attempt)",
        r"\bbelow\s+\d+\b",
        r"\btoday'?s?\s+(exam|results?)\b",
        r"\blive\s+(count|students?|attempts?)\b",
    )
)

_ANALYTICS_HINTS: tuple[str, ...] = (
    "analytics",
    "statistics",
    "performance",
    "average score",
    "pass rate",
    "fail rate",
    "compare exam",
    "topic performance",
)

_ACTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\b(create|delete|publish|unpublish|approve|reject|share)\b",
        r"\b(start|stop|end)\s+(the\s+)?(exam|quiz|attempt)\b",
        r"\bchange\b.*\b(setting|timer|password)\b",
    )
)

_META_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"^(hi|hello|hey|yo|hiya|hola|namaste|sup|howdy)(\s|$)",
        r"^(hi|hello|hey)\s+(there|que)\b",
        r"^(good\s+)?(morning|afternoon|evening|night)\b",
        r"\bwhat can you (do|help with)\b",
        r"\bwho are you\b",
        r"\bwhat is quizzer\b",
        r"^(help|help me)$",
        r"^(thanks|thank you|thx|ty)(\s|!|\.|$)",
        r"\bhow are you\b",
        r"^(bye|goodbye|good bye|see you|see ya|take care|later)\b",
        r"\b(what|how)\s+about\s+you\b",
        r"^i('m| am|m)?\s+(fine|good|great|well|ok|okay)\b",
        r"^(ok|okay|cool|nice|great|awesome|perfect|got it|alright)\s*$",
    )
)

_HIGH_WRITE_HINTS: tuple[str, ...] = (
    "delete",
    "remove all",
    "wipe",
    "reset password",
    "change password",
    "unpublish",
)


def _norm(text: str) -> str:
    cleaned = text.casefold().strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _has_quizzer_hint(text: str) -> bool:
    return any(h in text for h in _QUIZZER_HINTS)


def is_hard_out_of_scope(text: str) -> bool:
    """True for clearly non-Quizzer asks (weather, coding, jailbreak, …).

    Used before follow-up continuation so mid-chat topic switches still refuse.
    """
    n = _norm(text or "")
    if not n:
        return False
    return any(pat.search(n) for pat in _OUT_OF_SCOPE_PATTERNS)


def classify_request(
    text: str,
    *,
    conversation_active: bool = False,
) -> RequestUnderstanding:
    """Classify a user ask (usually the *resolved* query).

    ``conversation_active`` means this turn continues an established Quizzer
    thread. In that mode we still refuse hard out-of-scope patterns, but we do
    **not** refuse merely because the wording lacks Quizzer keywords.
    """
    raw = (text or "").strip()
    if not raw:
        return RequestUnderstanding(
            scope="clarification",
            intent="meta",
            risk="read",
            freshness="static",
            data_need="none",
            complexity="single_step",
            route="clarify",
            reasons=("empty_message",),
        )

    n = _norm(raw)
    reasons: list[str] = []

    for pat in _OUT_OF_SCOPE_PATTERNS:
        if pat.search(n):
            # Jailbreak / injection / unrelated world knowledge.
            if _has_quizzer_hint(n) and "ignore" not in n and "system prompt" not in n:
                # e.g. "write a python script to grade quizzer results" — still risky out.
                pass
            reasons.append(f"out_pattern:{pat.pattern[:40]}")
            return RequestUnderstanding(
                scope="out_of_scope",
                intent="out_of_scope",
                risk="read",
                freshness="static",
                data_need="none",
                complexity="single_step",
                route="refuse",
                reasons=tuple(reasons),
            )

    # Short meta / chitchat without product ask.
    for pat in _META_PATTERNS:
        if pat.search(n) and len(n) < 80 and not any(
            h in n for h in ("how do i", "where is", "publish", "create quiz", "monitor")
        ):
            intent: Intent = "chitchat" if pat.pattern.startswith("^(hi") else "meta"
            reasons.append("meta_or_chitchat")
            return RequestUnderstanding(
                scope="in_scope",
                intent=intent,
                risk="read",
                freshness="static",
                data_need="none",
                complexity="single_step",
                route="canned_eligible",
                reasons=tuple(reasons),
            )

    for pat in _LIVE_DATA_PATTERNS:
        if pat.search(n):
            reasons.append("live_data_pattern")
            return RequestUnderstanding(
                scope="in_scope",
                intent="analytics" if any(h in n for h in _ANALYTICS_HINTS) else "live_data",
                risk="read",
                freshness="critical" if "live" in n or "today" in n else "dynamic",
                data_need="live_tool",
                complexity="single_step",
                route="tool",
                reasons=tuple(reasons),
            )

    if any(h in n for h in _ANALYTICS_HINTS) and _has_quizzer_hint(n):
        reasons.append("analytics_hint")
        return RequestUnderstanding(
            scope="in_scope",
            intent="analytics",
            risk="read",
            freshness="dynamic",
            data_need="live_tool",
            complexity="multi_step" if "compare" in n else "single_step",
            route="tool",
            reasons=tuple(reasons),
        )

    action_hit = any(p.search(n) for p in _ACTION_PATTERNS)
    howto_ask = (
        "how" in n
        or "where" in n
        or "what" in n
        or "?" in raw
        or n.startswith("help me")
        or n.startswith("help with")
    )
    if action_hit and howto_ask:
        # "How do I publish?" / "Help me publish" is knowledge, not execution.
        reasons.append("how_to_action_as_knowledge")
        return RequestUnderstanding(
            scope="in_scope",
            intent="knowledge",
            risk="read",
            freshness="static",
            data_need="knowledge",
            complexity="single_step",
            route="knowledge",
            reasons=tuple(reasons),
        )

    if action_hit and _has_quizzer_hint(n):
        risk: Risk = "high_write" if any(h in n for h in _HIGH_WRITE_HINTS) else "low_write"
        reasons.append("action_request")
        return RequestUnderstanding(
            scope="in_scope",
            intent="action",
            risk=risk,
            freshness="dynamic",
            data_need="live_tool",
            complexity="single_step",
            route="tool",
            reasons=tuple(reasons),
        )

    if _has_quizzer_hint(n) or any(
        p in n
        for p in (
            "how do i",
            "how does ",
            "how can i",
            "how to",
            "where is",
            "where do i",
            "what is a",
            "what is an",
            "can i",
            "explain ",
        )
    ):
        reasons.append("knowledge_or_howto")
        return RequestUnderstanding(
            scope="in_scope",
            intent="knowledge",
            risk="read",
            freshness="static",
            data_need="knowledge",
            complexity="multi_step" if " and " in n and "how" in n else "single_step",
            route="knowledge",
            reasons=tuple(reasons),
        )

    # Active Quizzer conversation: continue helping unless hard-OOS (already checked).
    if conversation_active:
        reasons.append("conversation_continuation")
        return RequestUnderstanding(
            scope="in_scope",
            intent="knowledge",
            risk="read",
            freshness="static",
            data_need="knowledge",
            complexity="single_step",
            route="knowledge",
            reasons=tuple(reasons),
        )

    # Cold start with no Quizzer signal → refuse rather than hallucinate.
    reasons.append("no_quizzer_signal")
    return RequestUnderstanding(
        scope="out_of_scope",
        intent="out_of_scope",
        risk="read",
        freshness="static",
        data_need="none",
        complexity="single_step",
        route="refuse",
        reasons=tuple(reasons),
    )
