"""LangGraph state for the QUE conversational agent."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from langchain_core.messages import BaseMessage


class QueGraphState(TypedDict):
    """Agent state shared across graph nodes.

    Topology: prepare → knowledge → generate.

    ``dialog`` is short-term memory (user/assistant turns) restored by the
    LangGraph checkpointer when ``thread_id`` is set. ``messages`` is the
    ephemeral prompt for this turn only (identity + knowledge + dialog).

    Conversational resolution fields (resolved_query, topic, …) are set by the
    orchestration layer before/during the graph so RAG and generation use the
    rewritten ask — not only the raw follow-up utterance.
    """

    # Raw role/content dicts from the HTTP request (pre-sanitize).
    input_messages: list[dict[str, str]]
    # Short-term conversation memory (Human/AI only) — checkpointed.
    dialog: NotRequired[list[BaseMessage]]
    # LangChain messages actually sent to / returned from the model this turn.
    messages: list[BaseMessage]
    sources_used: list[str]
    conversation_id: NotRequired[str | None]
    user_id: NotRequired[str | None]
    identity_version: NotRequired[str]
    model_name: NotRequired[str]
    knowledge_packs: NotRequired[list[str]]
    memory_turns: NotRequired[int]

    # --- Conversational resolution (checkpointed for continuity) ---
    raw_user_message: NotRequired[str | None]
    resolved_query: NotRequired[str | None]
    is_follow_up: NotRequired[bool]
    topic: NotRequired[str | None]
    current_task: NotRequired[str | None]
    intent: NotRequired[str | None]
    response_mode: NotRequired[str | None]
    retrieval_query: NotRequired[str | None]
