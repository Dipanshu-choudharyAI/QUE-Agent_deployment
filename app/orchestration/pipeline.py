"""HTTP-facing orchestration — runs the LangGraph agent for each turn.

The graph owns agent structure. This module maps ChatRequest ↔ graph I/O,
runs Request Understanding (Phase 1), and exposes complete / stream helpers.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import structlog
from langchain_core.messages import AIMessage, BaseMessage

from app.core.config import Settings, get_settings
from app.core.llm import LLMError
from app.core.que_cache import (
    cache_key,
    get_cached_llm_reply,
    set_cached_llm_reply,
)
from app.graphs.memory import (
    append_assistant,
    make_thread_id,
    max_dialog_turns,
    memory_enabled,
    merge_dialog_with_incoming,
    runnable_config,
)
from app.graphs.nodes import knowledge_node, prepare_node
from app.graphs.que_graph import get_que_graph
from app.graphs.state import QueGraphState
from app.identity import identity_metadata
from app.orchestration.canned import latest_user_text, match_canned_reply
from app.orchestration.history import sanitize_history
from app.orchestration.resolve import ResolvedRequest, resolve_request
from app.orchestration.understanding import (
    OUT_OF_SCOPE_REFUSAL,
    RequestUnderstanding,
    classify_request,
    is_hard_out_of_scope,
)
from app.schemas.chat import ChatMessage, ChatRequest, ChatResponse

logger = structlog.get_logger(__name__)

TOOL_NOT_READY_REPLY = (
    "I can't read live Quizzer account or exam numbers yet. "
    "Open the relevant Dashboard or Results view in the app for current figures, "
    "or ask how to find that screen."
)

CLARIFY_REPLY = "Could you ask that as a Quizzer question — for example how to create, publish, or monitor an exam?"


def _prepare_with_knowledge(
    request: ChatRequest,
    *,
    dialog: list | None = None,
    resolution: ResolvedRequest | None = None,
) -> dict:
    """Same prepare → knowledge path as the compiled graph (for streaming)."""
    initial = _request_to_input(request, resolution=resolution)
    if dialog is not None:
        initial["dialog"] = dialog
    state = prepare_node(initial)
    state = {
        **initial,
        **state,
    }
    return knowledge_node(state)


def _thread_config(request: ChatRequest) -> tuple[str | None, dict | None]:
    if not memory_enabled():
        return None, None
    thread_id = make_thread_id(request.conversation_id, request.user_id)
    if not thread_id:
        # Checkpointer requires a thread_id; one-shot turns get an ephemeral id.
        thread_id = f"ephemeral:{uuid.uuid4().hex}"
    return thread_id, runnable_config(thread_id)


async def _persist_dialog_turn(request: ChatRequest, assistant_text: str) -> int:
    """Write user+assistant into short-term memory (early replies / stream path)."""
    thread_id, config = _thread_config(request)
    if not config:
        return 0
    graph = get_que_graph()
    try:
        snap = await graph.aget_state(config)
        existing = list((snap.values or {}).get("dialog") or [])
    except Exception:  # noqa: BLE001
        existing = []
    dialog = merge_dialog_with_incoming(
        existing,
        list(request.messages),
        max_turns=max_dialog_turns(),
    )
    dialog = append_assistant(dialog, assistant_text, max_turns=max_dialog_turns())
    try:
        # as_node required when updating outside a running superstep.
        await graph.aupdate_state(
            config,
            {
                **_request_to_input(request),
                "dialog": dialog,
                "memory_turns": len(dialog),
            },
            as_node="generate",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "que_memory_persist_failed",
            thread_id=thread_id,
            error=str(exc),
            path="persist_dialog_turn",
        )
        return 0
    return len(dialog)


@dataclass
class PreparedTurn:
    """Messages after the prepare node — useful for unit tests without LLM calls."""

    messages: list[ChatMessage]
    sources_used: list[str] = field(default_factory=list)
    identity: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnDecision:
    """Outcome of understanding + fast paths before LLM."""

    request_id: str
    understanding: RequestUnderstanding
    resolution: ResolvedRequest
    early_reply: str | None = None
    early_model: str | None = None


def _request_to_input(
    request: ChatRequest,
    *,
    resolution: ResolvedRequest | None = None,
) -> QueGraphState:
    payload: QueGraphState = {
        "input_messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "messages": [],
        "sources_used": [],
        "conversation_id": request.conversation_id,
        "user_id": request.user_id,
    }
    if resolution is not None:
        payload["raw_user_message"] = resolution.raw_message
        payload["resolved_query"] = resolution.resolved_query
        payload["is_follow_up"] = resolution.is_follow_up
        payload["topic"] = resolution.topic
        payload["current_task"] = resolution.resolved_query
        payload["intent"] = resolution.intent
        payload["response_mode"] = resolution.response_mode
        payload["retrieval_query"] = resolution.resolved_query
    return payload


def _log_request_trace(
    *,
    request_id: str,
    request: ChatRequest,
    resolution: ResolvedRequest,
    understanding: RequestUnderstanding,
    knowledge_packs: list[str] | None = None,
) -> None:
    logger.info(
        "que_request_trace",
        request_id=request_id,
        conversation_id=request.conversation_id,
        raw_user_message=resolution.raw_message,
        previous_context_available=bool(resolution.prior_user_message),
        resolved_query=resolution.resolved_query,
        is_follow_up=resolution.is_follow_up,
        topic=resolution.topic,
        resolve_intent=resolution.intent,
        response_mode=resolution.response_mode,
        scope_decision=understanding.scope,
        route=understanding.route,
        retrieval_query=resolution.resolved_query,
        resolve_reasons=list(resolution.reasons),
        knowledge_packs=knowledge_packs or [],
        understanding_intent=understanding.intent,
        understanding_risk=understanding.risk,
        understanding_freshness=understanding.freshness,
        understanding_data_need=understanding.data_need,
        understanding_complexity=understanding.complexity,
        understanding_reasons=list(understanding.reasons),
    )


def _lc_to_schema(messages: list[BaseMessage]) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    for message in messages:
        content = message.content if isinstance(message.content, str) else str(message.content or "")
        if not content.strip():
            continue
        msg_type = message.type
        if msg_type == "system":
            out.append(ChatMessage(role="system", content=content))
        elif msg_type == "human":
            out.append(ChatMessage(role="user", content=content))
        elif msg_type == "ai":
            out.append(ChatMessage(role="assistant", content=content))
    return out


def prepare_turn(request: ChatRequest) -> PreparedTurn:
    """Run prepare → knowledge (no LLM) — identity + product packs."""
    partial = _prepare_with_knowledge(request)
    return PreparedTurn(
        messages=_lc_to_schema(partial["messages"]),
        sources_used=list(partial.get("sources_used") or []),
        identity=identity_metadata(),
    )


def _assistant_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            content = message.content if isinstance(message.content, str) else str(message.content or "")
            if content.strip():
                return content
    raise LLMError("LLM returned an empty response")


def _history_fingerprint(request: ChatRequest) -> str:
    """Stable key for LLM reply cache — sanitized role/content turns only."""
    cleaned = sanitize_history(list(request.messages))
    parts = [f"{m.role}:{m.content.strip()}" for m in cleaned]
    if request.conversation_id:
        parts.insert(0, f"cid:{request.conversation_id.strip()}")
    if request.user_id:
        parts.insert(0, f"uid:{request.user_id.strip()}")
    return cache_key("hist", *parts)


def _chunk_text(text: str, size: int = 28) -> list[str]:
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


def decide_turn(request: ChatRequest) -> TurnDecision:
    """Resolve follow-ups, then classify with conversation-aware scope."""
    request_id = uuid.uuid4().hex[:12]
    user_text = latest_user_text(request.messages)
    resolution = resolve_request(list(request.messages))

    # Hard out-of-scope on the *raw* utterance always wins (weather, jokes, …),
    # even mid-conversation — do not let follow-up rewriting soften that.
    if is_hard_out_of_scope(user_text):
        understanding = classify_request(user_text)
        _log_request_trace(
            request_id=request_id,
            request=request,
            resolution=resolution,
            understanding=understanding,
        )
        return TurnDecision(
            request_id=request_id,
            understanding=understanding,
            resolution=resolution,
            early_reply=OUT_OF_SCOPE_REFUSAL,
            early_model="scope:refuse",
        )

    # Warm social / FAQ replies before product scope. Keeps hello / I'm fine /
    # bye interactive without treating them as out-of-scope.
    canned = match_canned_reply(
        user_text,
        conversation_id=request.conversation_id,
    )
    if canned is not None:
        understanding = classify_request(
            user_text,
            conversation_active=True,
        )
        # Force a friendly route for logging even if classifier was unsure.
        if understanding.route == "refuse":
            understanding = RequestUnderstanding(
                scope="in_scope",
                intent="chitchat",
                risk="read",
                freshness="static",
                data_need="none",
                complexity="single_step",
                route="canned_eligible",
                reasons=("canned_social", *understanding.reasons),
            )
        _log_request_trace(
            request_id=request_id,
            request=request,
            resolution=resolution,
            understanding=understanding,
        )
        return TurnDecision(
            request_id=request_id,
            understanding=understanding,
            resolution=resolution,
            early_reply=canned.text,
            early_model=canned.model,
        )

    # Active Quizzer thread → classifier may continue without keyword matches.
    # Prefer resolver follow-up flag; also treat any prior Quizzer topic in-thread
    # as active so ordinals like "first" never cold-refuse mid-conversation.
    conversation_active = bool(
        resolution.is_follow_up
        or resolution.topic
        or (
            resolution.prior_user_message
            and any(
                h in (resolution.prior_user_message or "").casefold()
                for h in (
                    "quiz",
                    "exam",
                    "integrat",
                    "calendar",
                    "classroom",
                    "publish",
                    "arena",
                )
            )
        )
    )
    understanding = classify_request(
        resolution.resolved_query or user_text,
        conversation_active=conversation_active,
    )

    _log_request_trace(
        request_id=request_id,
        request=request,
        resolution=resolution,
        understanding=understanding,
    )

    if understanding.route == "refuse":
        return TurnDecision(
            request_id=request_id,
            understanding=understanding,
            resolution=resolution,
            early_reply=OUT_OF_SCOPE_REFUSAL,
            early_model="scope:refuse",
        )

    if understanding.route == "clarify":
        return TurnDecision(
            request_id=request_id,
            understanding=understanding,
            resolution=resolution,
            early_reply=CLARIFY_REPLY,
            early_model="scope:clarify",
        )

    if understanding.route == "tool":
        # Phase 4 will execute tools; until then never invent live numbers.
        return TurnDecision(
            request_id=request_id,
            understanding=understanding,
            resolution=resolution,
            early_reply=TOOL_NOT_READY_REPLY,
            early_model="route:tool_pending",
        )

    return TurnDecision(
        request_id=request_id,
        understanding=understanding,
        resolution=resolution,
    )


def _log_turn(
    *,
    event: str,
    decision: TurnDecision,
    request: ChatRequest,
    latency_ms: float,
    model: str | None = None,
    cache_hit: bool = False,
    error: str | None = None,
    knowledge_packs: list[str] | None = None,
    knowledge_scores: dict[str, int] | None = None,
    knowledge_truncated: bool | None = None,
) -> None:
    logger.info(
        event,
        request_id=decision.request_id,
        conversation_id=request.conversation_id,
        user_id=request.user_id,
        latency_ms=round(latency_ms, 2),
        model=model,
        cache_hit=cache_hit,
        error=error,
        knowledge_packs=knowledge_packs or [],
        knowledge_scores=knowledge_scores or {},
        knowledge_truncated=knowledge_truncated,
        resolved_query=decision.resolution.resolved_query,
        is_follow_up=decision.resolution.is_follow_up,
        response_mode=decision.resolution.response_mode,
        topic=decision.resolution.topic,
        resolve_intent=decision.resolution.intent,
        **decision.understanding.as_log_dict(),
    )


async def complete(request: ChatRequest, *, settings: Settings | None = None) -> ChatResponse:
    cfg = settings or get_settings()
    started = time.perf_counter()
    decision = decide_turn(request)
    thread_id, mem_config = _thread_config(request)

    if decision.early_reply is not None:
        memory_turns = await _persist_dialog_turn(request, decision.early_reply)
        _log_turn(
            event="que_chat_complete",
            decision=decision,
            request=request,
            latency_ms=(time.perf_counter() - started) * 1000,
            model=decision.early_model,
            knowledge_packs=[],
        )
        logger.info(
            "que_memory_saved",
            request_id=decision.request_id,
            thread_id=thread_id,
            memory_turns=memory_turns,
            path="early",
        )
        return ChatResponse(
            message=ChatMessage(role="assistant", content=decision.early_reply),
            conversation_id=request.conversation_id,
            model=decision.early_model or "unknown",
        )

    fingerprint = _history_fingerprint(request)
    cached = get_cached_llm_reply(fingerprint)
    if cached is not None:
        model_name = f"cache:{cached.get('model') or cfg.llm_model}"
        packs = list(cached.get("knowledge_packs") or [])
        await _persist_dialog_turn(request, cached["content"])
        _log_turn(
            event="que_chat_complete",
            decision=decision,
            request=request,
            latency_ms=(time.perf_counter() - started) * 1000,
            model=model_name,
            cache_hit=True,
            knowledge_packs=packs,
        )
        return ChatResponse(
            message=ChatMessage(role="assistant", content=cached["content"]),
            conversation_id=request.conversation_id,
            model=model_name,
            knowledge_packs=packs,
            sources_used=["cache", "knowledge", *[f"knowledge:{p}" for p in packs]],
        )

    # Resolve packs before generate so logs/response always show what was loaded.
    from app.knowledge import select_knowledge

    selection = select_knowledge(
        [{"role": m.role, "content": m.content} for m in request.messages],
        query=decision.resolution.resolved_query,
    )
    _log_request_trace(
        request_id=decision.request_id,
        request=request,
        resolution=decision.resolution,
        understanding=decision.understanding,
        knowledge_packs=selection.pack_ids,
    )

    graph = get_que_graph()
    initial = _request_to_input(request, resolution=decision.resolution)
    invoke_kwargs: dict = {}
    if mem_config is not None:
        invoke_kwargs["config"] = mem_config

    try:
        result = await graph.ainvoke(initial, **invoke_kwargs)
    except LLMError:
        _log_turn(
            event="que_chat_complete",
            decision=decision,
            request=request,
            latency_ms=(time.perf_counter() - started) * 1000,
            error="llm_error",
            knowledge_packs=selection.pack_ids,
            knowledge_scores=selection.scores,
            knowledge_truncated=selection.truncated,
        )
        raise
    except ValueError:
        _log_turn(
            event="que_chat_complete",
            decision=decision,
            request=request,
            latency_ms=(time.perf_counter() - started) * 1000,
            error="bad_request",
            knowledge_packs=selection.pack_ids,
            knowledge_scores=selection.scores,
            knowledge_truncated=selection.truncated,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        _log_turn(
            event="que_chat_complete",
            decision=decision,
            request=request,
            latency_ms=(time.perf_counter() - started) * 1000,
            error=type(exc).__name__,
            knowledge_packs=selection.pack_ids,
            knowledge_scores=selection.scores,
            knowledge_truncated=selection.truncated,
        )
        raise LLMError(str(exc)) from exc

    content = _assistant_text(result.get("messages") or [])
    model_name = result.get("model_name") or cfg.llm_model
    packs = list(result.get("knowledge_packs") or selection.pack_ids)
    sources = list(result.get("sources_used") or [])
    set_cached_llm_reply(
        fingerprint,
        content=content,
        model=model_name,
        knowledge_packs=packs,
    )
    _log_turn(
        event="que_chat_complete",
        decision=decision,
        request=request,
        latency_ms=(time.perf_counter() - started) * 1000,
        model=model_name,
        knowledge_packs=packs,
        knowledge_scores=selection.scores,
        knowledge_truncated=selection.truncated,
    )
    logger.info(
        "que_memory_saved",
        request_id=decision.request_id,
        thread_id=thread_id,
        memory_turns=result.get("memory_turns"),
        path="graph",
    )
    return ChatResponse(
        message=ChatMessage(role="assistant", content=content),
        conversation_id=request.conversation_id,
        model=model_name,
        knowledge_packs=packs,
        sources_used=sources,
    )


async def stream_tokens(
    request: ChatRequest,
    *,
    settings: Settings | None = None,
    decision: TurnDecision | None = None,
) -> AsyncIterator[str]:
    """Stream tokens after prepare → knowledge (same context as complete)."""
    from app.core.llm import get_chat_model
    from app.knowledge import select_knowledge

    cfg = settings or get_settings()
    started = time.perf_counter()
    decision = decision or decide_turn(request)
    thread_id, mem_config = _thread_config(request)

    if decision.early_reply is not None:
        memory_turns = await _persist_dialog_turn(request, decision.early_reply)
        _log_turn(
            event="que_chat_stream",
            decision=decision,
            request=request,
            latency_ms=(time.perf_counter() - started) * 1000,
            model=decision.early_model,
        )
        logger.info(
            "que_memory_saved",
            request_id=decision.request_id,
            thread_id=thread_id,
            memory_turns=memory_turns,
            path="early_stream",
        )
        for piece in _chunk_text(decision.early_reply):
            yield piece
        return

    fingerprint = _history_fingerprint(request)
    cached = get_cached_llm_reply(fingerprint)
    if cached is not None:
        model_name = f"cache:{cached.get('model') or cfg.llm_model}"
        packs = list(cached.get("knowledge_packs") or [])
        await _persist_dialog_turn(request, cached["content"])
        _log_turn(
            event="que_chat_stream",
            decision=decision,
            request=request,
            latency_ms=(time.perf_counter() - started) * 1000,
            model=model_name,
            cache_hit=True,
            knowledge_packs=packs,
        )
        for piece in _chunk_text(cached["content"]):
            yield piece
        return

    selection = select_knowledge(
        [{"role": m.role, "content": m.content} for m in request.messages],
        query=decision.resolution.resolved_query,
    )
    _log_request_trace(
        request_id=decision.request_id,
        request=request,
        resolution=decision.resolution,
        understanding=decision.understanding,
        knowledge_packs=selection.pack_ids,
    )

    existing_dialog: list = []
    if mem_config is not None:
        try:
            snap = await get_que_graph().aget_state(mem_config)
            existing_dialog = list((snap.values or {}).get("dialog") or [])
        except Exception:  # noqa: BLE001
            existing_dialog = []

    prepared = _prepare_with_knowledge(
        request,
        dialog=existing_dialog,
        resolution=decision.resolution,
    )
    messages = prepared["messages"]
    packs = list(prepared.get("knowledge_packs") or selection.pack_ids)
    dialog_after_prepare = list(prepared.get("dialog") or existing_dialog)

    collected: list[str] = []
    try:
        model = get_chat_model(settings=cfg)
        async for chunk in model.astream(messages):
            content = chunk.content
            if isinstance(content, str) and content:
                collected.append(content)
                yield content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                        piece = str(block["text"])
                        collected.append(piece)
                        yield piece
                    elif isinstance(block, str) and block:
                        collected.append(block)
                        yield block
    except LLMError:
        _log_turn(
            event="que_chat_stream",
            decision=decision,
            request=request,
            latency_ms=(time.perf_counter() - started) * 1000,
            error="llm_error",
            knowledge_packs=packs,
            knowledge_scores=selection.scores,
            knowledge_truncated=selection.truncated,
        )
        raise
    except ValueError:
        _log_turn(
            event="que_chat_stream",
            decision=decision,
            request=request,
            latency_ms=(time.perf_counter() - started) * 1000,
            error="bad_request",
            knowledge_packs=packs,
            knowledge_scores=selection.scores,
            knowledge_truncated=selection.truncated,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        _log_turn(
            event="que_chat_stream",
            decision=decision,
            request=request,
            latency_ms=(time.perf_counter() - started) * 1000,
            error=type(exc).__name__,
            knowledge_packs=packs,
            knowledge_scores=selection.scores,
            knowledge_truncated=selection.truncated,
        )
        raise LLMError(str(exc)) from exc

    full = "".join(collected).strip()
    model_name = getattr(model, "model_name", None) or getattr(model, "model", "") or cfg.llm_model
    if full:
        set_cached_llm_reply(
            fingerprint,
            content=full,
            model=str(model_name),
            knowledge_packs=packs,
        )
        if mem_config is not None:
            dialog = append_assistant(
                dialog_after_prepare,
                full,
                max_turns=max_dialog_turns(),
            )
            try:
                await get_que_graph().aupdate_state(
                    mem_config,
                    {
                        **_request_to_input(request, resolution=decision.resolution),
                        "dialog": dialog,
                        "memory_turns": len(dialog),
                        "knowledge_packs": packs,
                    },
                    as_node="generate",
                )
                logger.info(
                    "que_memory_saved",
                    request_id=decision.request_id,
                    thread_id=thread_id,
                    memory_turns=len(dialog),
                    path="stream",
                )
            except Exception as exc:  # noqa: BLE001
                # Never fail the user-visible stream because checkpoint write failed.
                logger.warning(
                    "que_memory_persist_failed",
                    request_id=decision.request_id,
                    thread_id=thread_id,
                    error=str(exc),
                    path="stream",
                )
    _log_turn(
        event="que_chat_stream",
        decision=decision,
        request=request,
        latency_ms=(time.perf_counter() - started) * 1000,
        model=str(model_name),
        knowledge_packs=packs,
        knowledge_scores=selection.scores,
        knowledge_truncated=selection.truncated,
    )
