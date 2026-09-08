"""Heuristic groundedness — no LLM-as-judge.

An answer is grounded when its distinctive tokens (and live numbers on tool
turns) appear in the supplied context snippet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "you",
        "your",
        "is",
        "are",
        "do",
        "i",
        "how",
        "with",
        "this",
        "that",
        "open",
        "click",
        "then",
    }
)
# Step markers are allowed even when not in TOOL_RESULT.
_STEP_NUMS = frozenset({"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"})


@dataclass(frozen=True)
class GroundednessResult:
    grounded: bool
    reason: str
    overlap: float = 0.0


def _tokens(text: str) -> set[str]:
    return {
        tok
        for tok in (m.group(0).casefold() for m in _TOKEN_RE.finditer(text or ""))
        if tok not in _STOP and len(tok) > 1
    }


def find_invented_numbers(answer: str, context: str) -> set[str]:
    """Digits in ``answer`` that don't appear in ``context`` (step 1-10 exempt).

    Shared by the offline groundedness eval and the live output guardrail
    (``app/guardrails/output.py``) so both use one number-gate definition.
    """
    ans_nums = set(_NUM_RE.findall(answer or ""))
    ctx_nums = set(_NUM_RE.findall(context or ""))
    return {n for n in ans_nums if n not in ctx_nums and n not in _STEP_NUMS}


def score_groundedness(
    answer: str,
    context: str,
    *,
    context_kind: str = "knowledge",
) -> GroundednessResult:
    reply = (answer or "").strip()
    blob = (context or "").strip()
    if not reply:
        return GroundednessResult(False, "empty_answer")
    if not blob:
        return GroundednessResult(False, "empty_context")

    if context_kind == "tool":
        if find_invented_numbers(reply, blob):
            return GroundednessResult(False, "invented_number", overlap=0.0)

    ctx_toks = _tokens(blob)
    ans_toks = _tokens(reply)
    if not ans_toks:
        return GroundednessResult(False, "no_content_tokens")
    shared = ans_toks & ctx_toks
    overlap = len(shared) / len(ans_toks)
    if context_kind == "tool":
        if len(shared) >= 2 or overlap >= 0.15:
            return GroundednessResult(True, "ok", overlap=overlap)
        return GroundednessResult(False, "low_overlap", overlap=overlap)
    if len(shared) >= 3 or overlap >= 0.18:
        return GroundednessResult(True, "ok", overlap=overlap)
    return GroundednessResult(False, "low_overlap", overlap=overlap)


def is_grounded(
    answer: str,
    context: str,
    *,
    context_kind: str = "knowledge",
) -> bool:
    return score_groundedness(answer, context, context_kind=context_kind).grounded
