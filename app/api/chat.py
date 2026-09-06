"""Chat HTTP endpoints — Phase 1 conversational API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core import llm as llm_client
from app.core.errors import ERROR_BAD_REQUEST, public_llm_error
from app.core.security import require_chat_auth
from app.core.tokens import QuePrincipal
from app.identity import identity_metadata
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_service

router = APIRouter(prefix="/v1", tags=["chat"])

Principal = Annotated[QuePrincipal, Depends(require_chat_auth)]


@router.get("/identity")
async def identity(_principal: Principal) -> dict:
    """Return QUE's public identity metadata (no LLM call)."""
    return identity_metadata()


def _with_principal_user(request: ChatRequest, principal: QuePrincipal) -> ChatRequest:
    """Prefer JWT subject when the client omitted user_id."""
    if request.user_id or not principal.user_id:
        return request
    return request.model_copy(update={"user_id": principal.user_id})


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, principal: Principal) -> ChatResponse:
    try:
        return await chat_service.chat_complete(_with_principal_user(request, principal))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": ERROR_BAD_REQUEST, "message": str(exc)},
        ) from exc
    except llm_client.LLMError as exc:
        code, message = public_llm_error(exc)
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if code == "llm_not_configured"
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": code, "message": message},
        ) from exc


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, principal: Principal) -> StreamingResponse:
    """SSE chat. Refuse / canned / tool-pending work without LLM_API_KEY."""
    prepared = _with_principal_user(request, principal)
    return StreamingResponse(
        chat_service.chat_stream_events(prepared),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
