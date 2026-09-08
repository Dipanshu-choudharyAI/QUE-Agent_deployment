"""In-process token-bucket rate limiter — lenient, per-user/IP."""

from __future__ import annotations

from app.core.config import Settings
from app.core.ratelimit import check_rate_limit


def _cfg(**overrides) -> Settings:
    base = dict(APP_ENV="local", QUE_RATE_LIMIT_ENABLED=True)
    base.update(overrides)
    return Settings(**base)


def test_allows_up_to_capacity_then_blocks():
    cfg = _cfg(QUE_RATE_LIMIT_PER_MINUTE=60, QUE_RATE_LIMIT_BURST=5)
    key = "user:t1"
    ok_count = 0
    for _ in range(65):
        allowed, _retry = check_rate_limit(key, settings=cfg)
        if allowed:
            ok_count += 1
    assert ok_count == 65  # capacity = 60 + 5 burst
    blocked, retry_after = check_rate_limit(key, settings=cfg)
    assert blocked is False
    assert retry_after > 0


def test_disabled_never_blocks():
    cfg = _cfg(QUE_RATE_LIMIT_ENABLED=False, QUE_RATE_LIMIT_PER_MINUTE=1, QUE_RATE_LIMIT_BURST=0)
    for _ in range(50):
        allowed, _retry = check_rate_limit("user:t2", settings=cfg)
        assert allowed is True


def test_buckets_are_independent_per_key():
    cfg = _cfg(QUE_RATE_LIMIT_PER_MINUTE=1, QUE_RATE_LIMIT_BURST=0)
    allowed_a, _ = check_rate_limit("user:a", settings=cfg)
    allowed_b, _ = check_rate_limit("user:b", settings=cfg)
    assert allowed_a is True
    assert allowed_b is True  # different key, own bucket — not starved by "a"


def test_chat_endpoint_returns_429_when_limit_exceeded(client, que_jwt_secret):
    # A real end-user JWT (not the service key) — service-to-service callers
    # are exempt from this per-user limiter by design.
    from datetime import UTC, datetime, timedelta

    import jwt

    from app.core.config import get_settings

    settings = get_settings()
    object.__setattr__(settings, "que_rate_limit_per_minute", 1)
    object.__setattr__(settings, "que_rate_limit_burst", 0)
    try:
        token = jwt.encode(
            {
                "sub": "rl-test-user",
                "typ": "que_access",
                "aud": "que-agent",
                "iss": "quizzer",
                "exp": datetime.now(UTC) + timedelta(minutes=10),
            },
            que_jwt_secret,
            algorithm="HS256",
        )
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"messages": [{"role": "user", "content": "hello"}]}
        first = client.post("/v1/chat", json=payload, headers=headers)
        assert first.status_code != 429
        second = client.post("/v1/chat", json=payload, headers=headers)
        assert second.status_code == 429
    finally:
        object.__setattr__(settings, "que_rate_limit_per_minute", 60)
        object.__setattr__(settings, "que_rate_limit_burst", 20)
