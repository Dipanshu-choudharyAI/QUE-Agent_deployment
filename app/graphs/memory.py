"""Short-term conversation memory — LangGraph checkpointer helpers.

Persists user/assistant turns per ``thread_id`` (conversation_id + user_id)
in an in-process MemorySaver. Survives across turns on the same worker;
not shared across processes (use a DB checkpointer later for multi-instance).
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import Settings, get_settings
from app.orchestration.history import sanitize_history
from app.schemas.chat import ChatMessage

_THREAD_SAFE = re.compile(r"[^a-zA-Z0-9._:-]+")

# Process-wide saver shared by the compiled graph.
_CHECKPOINTER = MemorySaver()


def get_checkpointer() -> MemorySaver:
    return _CHECKPOINTER


def memory_enabled(*, settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return bool(getattr(cfg, "que_memory_enabled", True))


def max_dialog_turns(*, settings: Settings | None = None) -> int:
    cfg = settings or get_settings()
    return max(2, int(getattr(cfg, "que_memory_max_turns", 20)))


def make_thread_id(conversation_id: str | None, user_id: str | None = None) -> str | None:
    """Stable LangGraph thread id, or None when memory should not run."""
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    uid = _THREAD_SAFE.sub("_", (user_id or "anon").strip())[:64] or "anon"
    safe_cid = _THREAD_SAFE.sub("_", cid)[:128]
    return f"{uid}:{safe_cid}"


def runnable_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def trim_dialog(dialog: list[BaseMessage], *, max_turns: int) -> list[BaseMessage]:
    """Keep the most recent user/assistant turns within ``max_turns`` messages."""
    cleaned = [m for m in dialog if isinstance(m, (HumanMessage, AIMessage))]
    if len(cleaned) <= max_turns:
        return cleaned
    return cleaned[-max_turns:]


def _lc_from_schema(messages: list[ChatMessage]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for message in messages:
        if message.role == "user":
            out.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            out.append(AIMessage(content=message.content))
    return out


def _same_text(a: BaseMessage, b: BaseMessage) -> bool:
    if type(a) is not type(b):
        return False
    ca = a.content if isinstance(a.content, str) else str(a.content or "")
    cb = b.content if isinstance(b.content, str) else str(b.content or "")
    return ca.strip() == cb.strip()


def merge_dialog_with_incoming(
    existing: list[BaseMessage],
    incoming: list[ChatMessage],
    *,
    max_turns: int,
) -> list[BaseMessage]:
    """Merge client history / latest turn into stored dialog without duplicates.

    - Empty memory → seed from sanitized client history.
    - Existing memory → append only the newest user turn when it is new.
    """
    cleaned = sanitize_history(incoming)
    incoming_lc = _lc_from_schema(cleaned)
    if not incoming_lc:
        return trim_dialog(existing, max_turns=max_turns)

    if not existing:
        return trim_dialog(incoming_lc, max_turns=max_turns)

    latest = incoming_lc[-1]
    if not isinstance(latest, HumanMessage):
        # Prefer the last user turn from the request.
        users = [m for m in incoming_lc if isinstance(m, HumanMessage)]
        if not users:
            return trim_dialog(existing, max_turns=max_turns)
        latest = users[-1]

    if existing and _same_text(existing[-1], latest):
        return trim_dialog(existing, max_turns=max_turns)

    # Avoid re-adding if the same user text was the last human already.
    for prev in reversed(existing):
        if isinstance(prev, HumanMessage):
            if _same_text(prev, latest):
                return trim_dialog(existing, max_turns=max_turns)
            break

    return trim_dialog([*existing, latest], max_turns=max_turns)


def append_assistant(dialog: list[BaseMessage], content: str, *, max_turns: int) -> list[BaseMessage]:
    text = (content or "").strip()
    if not text:
        return trim_dialog(dialog, max_turns=max_turns)
    return trim_dialog([*dialog, AIMessage(content=text)], max_turns=max_turns)
