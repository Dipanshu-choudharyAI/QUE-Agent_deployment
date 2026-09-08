"""Strip jailbreak lines from untrusted retrieved / tool payloads."""

from __future__ import annotations

from app.guardrails.patterns import injection_match


def neutralize_untrusted_text(text: str) -> str:
    """Drop lines that look like injection; keep the rest as inert data."""
    if not (text or "").strip():
        return text or ""
    kept: list[str] = []
    for line in text.splitlines():
        if injection_match(line):
            kept.append("[untrusted line omitted]")
            continue
        kept.append(line)
    return "\n".join(kept)
