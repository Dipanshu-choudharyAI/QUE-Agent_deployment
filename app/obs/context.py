"""Per-turn trace + request_id binding (contextvars; no PII)."""

from __future__ import annotations

from contextvars import ContextVar

import structlog

from app.obs.trace import TurnTrace

_current_trace: ContextVar[TurnTrace | None] = ContextVar("que_turn_trace", default=None)


def bind_trace(trace: TurnTrace) -> None:
    _current_trace.set(trace)
    structlog.contextvars.bind_contextvars(request_id=trace.request_id)


def current_trace() -> TurnTrace | None:
    return _current_trace.get()


def clear_trace() -> None:
    _current_trace.set(None)
    structlog.contextvars.unbind_contextvars("request_id")


def add_span(
    name: str,
    ms: float,
    *,
    ok: bool = True,
    extra: dict | None = None,
) -> None:
    trace = current_trace()
    if trace is None:
        return
    trace.add_span(name, ms, ok=ok, extra=extra)
