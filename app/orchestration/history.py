"""Conversation history helpers — keep Phase 1 requests bounded and safe."""

from __future__ import annotations

from app.schemas.chat import ChatMessage

# Soft caps to protect latency/cost; schemas already enforce hard max lengths.
DEFAULT_MAX_MESSAGES = 16
DEFAULT_MAX_CHARS = 10_000


def sanitize_history(
    messages: list[ChatMessage],
    *,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[ChatMessage]:
    """Drop client system prompts and trim to recent turns within a char budget.

    Callers must not override QUE identity via a leading system message.
    Future RAG/tool context is injected by the orchestration pipeline, not clients.
    """
    cleaned = [m for m in messages if m.role in {"user", "assistant"}]
    if not cleaned:
        raise ValueError("At least one user or assistant message is required")

    # Keep the latest N messages first.
    trimmed = cleaned[-max_messages:]

    # Then enforce a rough character budget from the end (preserve recent context).
    total = 0
    kept_reversed: list[ChatMessage] = []
    for message in reversed(trimmed):
        size = len(message.content)
        if kept_reversed and total + size > max_chars:
            break
        kept_reversed.append(message)
        total += size

    kept = list(reversed(kept_reversed))
    if not any(m.role == "user" for m in kept):
        # Ensure the model always sees at least the latest user turn.
        last_user = next((m for m in reversed(cleaned) if m.role == "user"), None)
        if last_user is None:
            raise ValueError("At least one user message is required")
        return [last_user]
    return kept
