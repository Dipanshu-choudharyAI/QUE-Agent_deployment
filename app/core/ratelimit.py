"""Lenient in-process rate limiter for the chat endpoints.

Token bucket per user (falls back to client IP for anonymous/service calls).
Process-local, like the existing cache/budget/circuit-breaker modules — no
Redis, no SaaS. Meant to stop obvious abuse (scripted hammering, a runaway
client loop) without throttling a real tester typing normally.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.core.config import Settings, get_settings


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


_lock = threading.Lock()
_buckets: dict[str, _Bucket] = {}


def reset_rate_limits() -> None:
    with _lock:
        _buckets.clear()


def _capacity(settings: Settings) -> float:
    per_minute = max(1, int(settings.que_rate_limit_per_minute or 60))
    # Burst allowance on top of the steady rate so a quick back-to-back
    # double-send never trips the limiter for a real user. Explicit None
    # check — `burst or 10` would wrongly treat a deliberate 0 as "unset".
    burst = settings.que_rate_limit_burst
    burst_value = int(burst) if burst is not None else 10
    return float(per_minute) + float(max(0, burst_value))


def check_rate_limit(
    key: str,
    *,
    settings: Settings | None = None,
) -> tuple[bool, float]:
    """Return (allowed, retry_after_seconds).

    Refill rate is ``QUE_RATE_LIMIT_PER_MINUTE`` tokens/minute; bucket size
    adds ``QUE_RATE_LIMIT_BURST`` extra tokens on top of the steady rate.
    """
    cfg = settings or get_settings()
    if not cfg.que_rate_limit_enabled:
        return True, 0.0

    per_minute = max(1, int(cfg.que_rate_limit_per_minute or 60))
    refill_per_second = per_minute / 60.0
    capacity = _capacity(cfg)
    now = time.monotonic()

    with _lock:
        bucket = _buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=capacity, updated_at=now)
            _buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(capacity, bucket.tokens + elapsed * refill_per_second)
            bucket.updated_at = now

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0.0

        missing = 1.0 - bucket.tokens
        retry_after = missing / refill_per_second if refill_per_second > 0 else 1.0
        return False, round(retry_after, 2)
