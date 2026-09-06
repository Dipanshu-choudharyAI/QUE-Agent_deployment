"""Chat HTTP service — SSE framing around the orchestration pipeline."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import structlog

from app.core import llm as llm_client
from app.core.config import Settings, get_settings
from app.core.errors import public_llm_error
from app.identity import identity_metadata
from app.orchestration.pipeline import complete, decide_turn, stream_tokens
from app.schemas.chat import ChatRequest, ChatResponse

logger = structlog.get_logger(__name__)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chunk_text_for_fallback(text: str, size: int = 24) -> list[str]:
    """Split a full reply into small chunks so the UI still 'streams' on fallback."""
    text = text.strip()
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


async def chat_complete(request: ChatRequest, *, settings: Settings | None = None) -> ChatResponse:
    return await complete(request, settings=settings)


async def chat_stream_events(
    request: ChatRequest,
    *,
    settings: Settings | None = None,
) -> AsyncIterator[str]:
    """Yield Server-Sent Event chunks (`data: JSON\\n\\n`).

    Prefer real token streaming. Only if the stream fails with zero tokens,
    fall back once to non-stream completion and emit it in small chunks.
    """
    cfg = settings or get_settings()
    decision = decide_turn(request)

    # Emit meta immediately so the client can leave a blank "Thinking…" state
    # while knowledge prep / TTFT still runs.
    meta: dict = {
        "type": "meta",
        "conversation_id": request.conversation_id,
        "model": decision.early_model or cfg.llm_model,
        "identity": identity_metadata(),
        "request_id": decision.request_id,
        "understanding": decision.understanding.as_log_dict(),
        "knowledge_packs": [],
        "resolution": decision.resolution.as_log_dict(),
    }
    yield _sse(meta)
    # Yield to the event loop so ASGI can flush meta before heavy work.
    await asyncio.sleep(0)

    if decision.early_reply is not None:
        for piece in _chunk_text_for_fallback(decision.early_reply, size=28):
            yield _sse({"type": "token", "content": piece})
            await asyncio.sleep(0.012)
        yield _sse({"type": "done", "model": decision.early_model})
        return

    if not cfg.llm_api_key:
        code, message = public_llm_error(llm_client.LLMError("LLM_API_KEY is not configured"))
        yield _sse({"type": "error", "code": code, "message": message})
        return

    # Pack selection is cheap but still do it after meta flush.
    from app.knowledge import select_knowledge

    selection = select_knowledge(
        [{"role": m.role, "content": m.content} for m in request.messages],
        query=decision.resolution.resolved_query,
    )
    meta["knowledge_packs"] = selection.pack_ids
    meta["knowledge_scores"] = selection.scores

    got_token = False
    stream_error: Exception | None = None

    try:
        async for token in stream_tokens(request, settings=cfg, decision=decision):
            if not token:
                continue
            got_token = True
            yield _sse({"type": "token", "content": token})
            # Cooperative flush — keeps SSE chunks from bunching into one write.
            await asyncio.sleep(0)
    except (llm_client.LLMError, ValueError) as exc:
        stream_error = exc

    if got_token:
        yield _sse({"type": "done", "knowledge_packs": meta.get("knowledge_packs") or []})
        return

    try:
        logger.warning(
            "que_stream_fallback_to_complete",
            conversation_id=request.conversation_id,
            reason=str(stream_error) if stream_error else "empty_stream",
        )
        response = await complete(request, settings=cfg)
        content = response.message.content
        chunks = _chunk_text_for_fallback(content)
        if not chunks:
            code, message = public_llm_error(llm_client.LLMError("LLM returned an empty response"))
            yield _sse({"type": "error", "code": code, "message": message})
            return
        for piece in chunks:
            yield _sse({"type": "token", "content": piece})
            await asyncio.sleep(0.012)
        yield _sse({"type": "done"})
    except llm_client.LLMError as exc:
        code, message = public_llm_error(stream_error or exc)
        yield _sse({"type": "error", "code": code, "message": message})
    except ValueError as exc:
        yield _sse({"type": "error", "code": "bad_request", "message": str(exc)})
