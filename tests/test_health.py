"""Liveness vs readiness endpoints."""

from __future__ import annotations


def test_health_is_always_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ready_reports_llm_not_configured(client):
    # conftest clears LLM_API_KEY* for all tests — /ready should reflect that
    # honestly instead of claiming healthy.
    resp = client.get("/ready")
    body = resp.json()
    assert body["checks"]["llm_configured"] is False
    assert resp.status_code == 503
    assert body["status"] == "degraded"


def test_ready_ok_when_llm_configured(client, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    object.__setattr__(settings, "llm_api_key", "sk-test-key")
    try:
        resp = client.get("/ready")
        body = resp.json()
        assert body["checks"]["llm_configured"] is True
        # Tools/knowledge checks may still fail in this sandbox — only assert
        # the field we actually changed.
    finally:
        object.__setattr__(settings, "llm_api_key", "")
