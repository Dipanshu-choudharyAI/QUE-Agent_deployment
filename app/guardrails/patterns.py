"""Shared injection pattern library (user text and untrusted payloads)."""

from __future__ import annotations

import re

# Imperative jailbreaks. Quizzer product words in the same sentence do not waive these.
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|your)\s+(instructions|rules|prompts)\b",
        r"\b(ignore|disregard)\s+(the\s+)?(system|developer)\s+(prompt|message)\b",
        r"\b(system prompt|reveal your (system )?prompt|print your (hidden )?instructions)\b",
        r"\b(jailbreak|do anything now)\b",
        r"\byou are (now )?dan\b",
        r"\boverride (your|the) (rules|safety|guardrails|instructions)\b",
        r"\bnew system prompt\b|\byou are now (in |an? )?(unrestricted|evil|developer)\b",
        r"\bfrom now on you (are|will|must)\b",
        r"\bpretend (you are|to be)\s+(an?\s+)?(admin|administrator|root|unfiltered)\b",
        r"\bact as\s+(an?\s+)?(admin|administrator|unrestricted|jailbroken|unfiltered|dan)\b",
        r"\b(enable|turn on|switch to)\s+(developer|debug)\s+mode\b",
        r"\bsimulate\s+(developer|debug|admin)\s+mode\b",
        r"\b(skip|bypass|ignore)\s+(the\s+)?confirmation\b",
        r"<\|im_start\|>|<\|im_end\|>",
        r"#{2,}\s*instruction",
        r"\b(dump|exfiltrate|export)\s+(the\s+)?(database|db|all\s+users?|all\s+students?)\b",
        r"\breveal (all|every)\s+(student|user|email|password)s?\b",
        r"\blist (all|every)\s+(student|user)\s+(emails?|passwords?|records?)\b",
        r"\bshow me (everyone'?s|all)\s+(emails?|passwords?|api keys?)\b",
    )
)


def injection_match(text: str) -> re.Match[str] | None:
    blob = text or ""
    for pat in INJECTION_PATTERNS:
        found = pat.search(blob)
        if found:
            return found
    return None
