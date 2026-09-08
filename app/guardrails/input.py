"""Input guardrail — reject jailbreak/injection before RAG, tools, or LLM."""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.guardrails import GuardrailHit
from app.guardrails.patterns import injection_match


def scan_user_text(text: str, *, settings: Settings | None = None) -> GuardrailHit | None:
    """Return a hit if the *user* utterance is an injection attempt.

    Quizzer product words in the same message do not waive the scan.
    """
    cfg = settings or get_settings()
    if not cfg.que_guardrails_enabled:
        return None
    raw = (text or "").strip()
    if not raw:
        return None
    found = injection_match(raw)
    if found is None:
        return None
    snippet = found.group(0)[:80]
    return GuardrailHit(layer="input", reason="injection", pattern=snippet)
