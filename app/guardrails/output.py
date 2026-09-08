"""Output guardrail — block cross-user dumps and echoed jailbreaks."""

from __future__ import annotations

import re
from typing import Any

from app.core.config import Settings, get_settings
from app.evals.groundedness import find_invented_numbers
from app.guardrails import OUTPUT_REFUSAL, GuardrailHit
from app.guardrails.patterns import injection_match

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_ROSTER_DUMP_RE = re.compile(
    r"\b(all students?|entire (class|roster)|here (are|is) (the )?(emails?|student list))\b",
    re.I,
)
_TEACHER_LIVE_RE = re.compile(
    r"\b(exam_count|published_count|you (have|created) \d+ exams?|"
    r"\d+ students scored|who needs coaching)\b",
    re.I,
)


def _allowed_blob(*, user_text: str, tool_blob: str | None, ui_blob: str | None) -> str:
    return " ".join(part for part in (user_text, tool_blob or "", ui_blob or "") if part)


def _emails(text: str) -> set[str]:
    return {m.group(0).casefold() for m in _EMAIL_RE.finditer(text or "")}


def scan_output(
    text: str,
    *,
    user_text: str = "",
    role: str | None = None,
    tool_blob: str | None = None,
    ui_blob: str | None = None,
    settings: Settings | None = None,
) -> GuardrailHit | None:
    cfg = settings or get_settings()
    if not cfg.que_guardrails_enabled:
        return None
    reply = (text or "").strip()
    if not reply:
        return None

    if injection_match(reply):
        return GuardrailHit(layer="output", reason="echoed_injection")

    allowed = _allowed_blob(user_text=user_text, tool_blob=tool_blob, ui_blob=ui_blob)
    extra_emails = _emails(reply) - _emails(allowed)
    if extra_emails:
        return GuardrailHit(layer="output", reason="ungrounded_email")

    has_tool = bool(tool_blob and "TOOL_RESULT" in tool_blob)

    # Runtime anti-hallucination gate — for every role, not just student
    # cross-role: when a TOOL_RESULT block is present, any number in the
    # reply that isn't grounded in it (small step numbers exempt) is an
    # invented live figure.
    if has_tool and find_invented_numbers(reply, tool_blob or ""):
        return GuardrailHit(layer="output", reason="ungrounded_number")

    if _ROSTER_DUMP_RE.search(reply) and not has_tool:
        # How-tos like "add students" mention the word; require dump-like shape.
        if _EMAIL_RE.search(reply) or re.search(r"(?m)^[-*]\s+\S+@.+$", reply):
            return GuardrailHit(layer="output", reason="roster_dump")

    role_n = (role or "").strip().casefold()
    if role_n == "student" and not has_tool and _TEACHER_LIVE_RE.search(reply):
        return GuardrailHit(layer="output", reason="student_cross_role")

    return None


def apply_output_guardrail(
    text: str,
    *,
    user_text: str = "",
    role: str | None = None,
    tool_blob: str | None = None,
    ui_blob: str | None = None,
    settings: Settings | None = None,
) -> tuple[str, GuardrailHit | None]:
    hit = scan_output(
        text,
        user_text=user_text,
        role=role,
        tool_blob=tool_blob,
        ui_blob=ui_blob,
        settings=settings,
    )
    if hit is None:
        return text, None
    return OUTPUT_REFUSAL, hit


def grounding_from_messages(messages: list[Any]) -> str:
    """Concatenate system blocks that may legally ground live facts."""
    parts: list[str] = []
    for message in messages or []:
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            content = str(content or "")
        if "TOOL_RESULT" in content or "QUIZZER_UI_CONTEXT" in content:
            parts.append(content)
    return "\n".join(parts)
