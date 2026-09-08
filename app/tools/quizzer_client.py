"""HTTP client for Quizzer internal QUE tools."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ToolClientError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def invoke_quizzer_tool(
    *,
    tool: str,
    args: dict[str, Any],
    user_id: str,
    request_id: str,
    idempotency_key: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    base = (cfg.quizzer_internal_base_url or "").rstrip("/")
    if not base:
        raise ToolClientError("unavailable", "QUIZZER_INTERNAL_BASE_URL is not configured")
    if not cfg.que_service_key:
        raise ToolClientError("unauthorized", "QUE_SERVICE_KEY is not configured")
    if not user_id:
        raise ToolClientError("invalid_argument", "user_id required for tools")

    url = f"{base}/internal/que/v1/tools/invoke"
    timeout = cfg.que_tool_timeout_seconds
    headers = {
        "X-Que-Service-Key": cfg.que_service_key,
        "X-Que-User-Id": user_id,
        "X-Request-Id": request_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body: dict[str, Any] = {"tool": tool, "args": args}
    if idempotency_key:
        body["idempotency_key"] = idempotency_key
        headers["X-Idempotency-Key"] = idempotency_key
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise ToolClientError("upstream_timeout", "Quizzer tool timed out") from exc
    except httpx.HTTPError as exc:
        raise ToolClientError("unavailable", f"Quizzer unreachable: {exc}") from exc

    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise ToolClientError("unavailable", "Quizzer returned non-JSON", status_code=resp.status_code) from exc

    if not isinstance(payload, dict):
        raise ToolClientError("unavailable", "Invalid tool envelope", status_code=resp.status_code)

    if resp.status_code >= 400 or not payload.get("ok", False):
        err = payload.get("error") or {}
        code = str(err.get("code") or "unavailable")
        message = str(err.get("message") or resp.text or "tool failed")
        raise ToolClientError(code, message, status_code=resp.status_code)

    return payload


async def check_tools_health(*, settings: Settings | None = None, timeout: float = 2.0) -> bool:
    """Best-effort reachability probe for readiness — never raises.

    Calls Quizzer's ``GET /internal/que/v1/tools/health``. Returns False on
    any error (timeout, non-2xx, unreachable, or tools not configured).
    """
    cfg = settings or get_settings()
    base = (cfg.quizzer_internal_base_url or "").rstrip("/")
    if not base or not cfg.que_service_key:
        return False
    url = f"{base}/internal/que/v1/tools/health"
    headers = {"X-Que-Service-Key": cfg.que_service_key}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            return False
        payload = resp.json()
        return bool(isinstance(payload, dict) and payload.get("ok", False))
    except Exception:  # noqa: BLE001 — readiness probe must never raise
        return False
