"""QUE agent graph nodes — one responsibility each for future expansion."""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.core.llm import LLMError, get_chat_model
from app.graphs.memory import append_assistant, max_dialog_turns, merge_dialog_with_incoming
from app.graphs.state import QueGraphState
from app.identity import IDENTITY_VERSION, build_system_prompt
from app.knowledge import select_knowledge
from app.orchestration.history import sanitize_history
from app.orchestration.resolve import ResolvedRequest, build_turn_instruction, resolve_request
from app.orchestration.understanding import OUT_OF_SCOPE_REFUSAL
from app.schemas.chat import ChatMessage


def _to_schema_messages(raw: list[dict[str, str]]) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    for item in raw:
        role = item.get("role", "")
        content = item.get("content", "")
        if role not in {"system", "user", "assistant"}:
            continue
        out.append(ChatMessage(role=role, content=content))  # type: ignore[arg-type]
    return out


def _dialog_to_schema(dialog: list[BaseMessage]) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    for message in dialog:
        content = message.content if isinstance(message.content, str) else str(message.content or "")
        if not content.strip():
            continue
        if isinstance(message, HumanMessage):
            out.append(ChatMessage(role="user", content=content))
        elif isinstance(message, AIMessage):
            out.append(ChatMessage(role="assistant", content=content))
    return out


def _resolution_from_state(state: QueGraphState, incoming: list[ChatMessage]) -> ResolvedRequest:
    latest = next((m.content.strip() for m in reversed(incoming) if m.role == "user"), "")
    raw_in_state = (state.get("raw_user_message") or "").strip()
    existing = (state.get("resolved_query") or "").strip()
    # Trust pre-seeded resolution only when it matches this turn's raw utterance
    # (avoids reusing a prior checkpoint's resolved_query).
    if existing and raw_in_state and latest and raw_in_state == latest:
        return ResolvedRequest(
            raw_message=raw_in_state,
            resolved_query=existing,
            is_follow_up=bool(state.get("is_follow_up")),
            topic=state.get("topic"),
            intent=state.get("intent") or "general_product_question",  # type: ignore[arg-type]
            response_mode=state.get("response_mode") or "normal",  # type: ignore[arg-type]
            reasons=("from_state",),
        )
    return resolve_request(
        incoming,
        prior_topic=state.get("topic"),
        prior_task=state.get("current_task"),
    )


def prepare_node(state: QueGraphState) -> dict:
    """Merge short-term dialog memory, resolve follow-ups, inject QUE identity."""
    incoming = _to_schema_messages(state.get("input_messages") or [])
    existing_dialog = list(state.get("dialog") or [])
    dialog = merge_dialog_with_incoming(
        existing_dialog,
        incoming,
        max_turns=max_dialog_turns(),
    )

    # Prefer checkpoint dialog for resolution when client history is thin.
    resolve_msgs = _dialog_to_schema(dialog) if dialog else incoming
    resolution = _resolution_from_state(state, resolve_msgs)

    history = sanitize_history(_dialog_to_schema(dialog)) if dialog else sanitize_history(incoming)
    system = ChatMessage(role="system", content=build_system_prompt())
    turn = build_turn_instruction(resolution)

    prompt: list[BaseMessage] = [
        SystemMessage(content=system.content),
        SystemMessage(content=turn),
    ]
    for message in history:
        if message.role == "user":
            prompt.append(HumanMessage(content=message.content))
        else:
            prompt.append(AIMessage(content=message.content))

    # Ensure the model sees the resolved ask even if the last user turn is short.
    if resolution.is_follow_up and resolution.resolved_query.strip():
        last = prompt[-1] if prompt else None
        if not (isinstance(last, HumanMessage) and last.content == resolution.resolved_query):
            prompt.append(
                HumanMessage(
                    content=(
                        f"(Resolved follow-up for this turn: {resolution.resolved_query})"
                    )
                )
            )

    sources = list(state.get("sources_used") or [])
    if "identity" not in sources:
        sources.append("identity")
    if existing_dialog and "memory" not in sources:
        sources.append("memory")
    if resolution.is_follow_up and "resolve" not in sources:
        sources.append("resolve")

    return {
        "dialog": dialog,
        "messages": prompt,
        "sources_used": sources,
        "identity_version": IDENTITY_VERSION,
        "memory_turns": len(dialog),
        "raw_user_message": resolution.raw_message,
        "resolved_query": resolution.resolved_query,
        "is_follow_up": resolution.is_follow_up,
        "topic": resolution.topic,
        "current_task": resolution.resolved_query,
        "intent": resolution.intent,
        "response_mode": resolution.response_mode,
        "retrieval_query": resolution.resolved_query,
    }


def knowledge_node(state: QueGraphState) -> dict:
    """Inject selected product-knowledge packs after identity, before generate."""
    retrieval_query = (state.get("retrieval_query") or state.get("resolved_query") or "").strip()
    selection = select_knowledge(
        list(state.get("input_messages") or []),
        query=retrieval_query or None,
    )
    messages = list(state.get("messages") or [])
    if selection.content.strip():
        # Place knowledge after identity + turn instruction system messages.
        insert_at = 0
        while insert_at < len(messages) and isinstance(messages[insert_at], SystemMessage):
            insert_at += 1
        if insert_at == 0:
            insert_at = 1 if messages and isinstance(messages[0], SystemMessage) else 0
        messages = [
            *messages[:insert_at],
            SystemMessage(content=selection.content),
            *messages[insert_at:],
        ]

    sources = list(state.get("sources_used") or [])
    if selection.pack_ids and "knowledge" not in sources:
        sources.append("knowledge")
    for pack_id in selection.pack_ids:
        tag = f"knowledge:{pack_id}"
        if tag not in sources:
            sources.append(tag)

    return {
        "messages": messages,
        "sources_used": sources,
        "knowledge_packs": list(selection.pack_ids),
        "retrieval_query": retrieval_query or state.get("retrieval_query"),
    }


def _validate_answer(content: str, *, response_mode: str | None, in_scope: bool) -> str:
    text = (content or "").strip()
    if not text:
        raise LLMError("LLM returned an empty response")
    if in_scope and OUT_OF_SCOPE_REFUSAL[:40] in text:
        return (
            "I can continue on that Quizzer topic. "
            "Ask me to explain step by step, give an example, or cover a related setting."
        )
    if response_mode == "step_by_step":
        has_steps = bool(
            re.search(r"(?m)^\s*1[\).\]]\s+\S", text) or re.search(r"\b1[\).\]]\s+\S", text)
        )
        if not has_steps and len(text) < 120:
            pass
    return text


async def generate_node(state: QueGraphState) -> dict:
    """Call the chat model with the prepared message list; append reply to dialog."""
    messages = state.get("messages") or []
    if not messages:
        raise LLMError("No messages prepared for generation")

    model = get_chat_model()
    try:
        response = await model.ainvoke(messages)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 — normalize provider errors
        raise LLMError(str(exc)) from exc

    content = response.content if isinstance(response.content, str) else str(response.content or "")
    content = _validate_answer(
        content,
        response_mode=state.get("response_mode"),
        in_scope=True,
    )

    sources = list(state.get("sources_used") or [])
    if "llm" not in sources:
        sources.append("llm")

    model_name = getattr(model, "model_name", None) or getattr(model, "model", "") or ""
    dialog = append_assistant(
        list(state.get("dialog") or []),
        content,
        max_turns=max_dialog_turns(),
    )
    return {
        "messages": [*messages, AIMessage(content=content)],
        "dialog": dialog,
        "sources_used": sources,
        "model_name": model_name,
        "memory_turns": len(dialog),
        "topic": state.get("topic"),
        "current_task": state.get("resolved_query") or state.get("current_task"),
        "intent": state.get("intent"),
        "response_mode": state.get("response_mode"),
        "resolved_query": state.get("resolved_query"),
        "is_follow_up": state.get("is_follow_up"),
    }


# Reserved for later:
#   context_node — Quizzer UI / role context
#   tools_node   — authorized Quizzer API tools
