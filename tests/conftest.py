"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.knowledge import knowledge_available

# Configure env BEFORE importing the app / settings cache.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("QUE_SERVICE_KEY", "test-service-key-not-for-production")
os.environ.setdefault(
    "QUE_JWT_SECRET",
    "test-que-jwt-secret-not-for-production-32c",
)
os.environ.setdefault("ALLOW_INSECURE_LOCAL_NO_AUTH", "false")
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("LLM_MODEL", "test-model")

# knowledge/ is gitignored — pack-content tests need a local checkout.
requires_knowledge = pytest.mark.skipif(
    not knowledge_available(),
    reason="knowledge/ packs not present (gitignored; local checkout required)",
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from app.core.config import get_settings
    from app.core.que_cache import reset_que_caches
    from app.graphs.que_graph import get_que_graph

    get_settings.cache_clear()
    get_que_graph.cache_clear()
    reset_que_caches()
    yield
    get_settings.cache_clear()
    get_que_graph.cache_clear()
    reset_que_caches()


@pytest.fixture
def service_key() -> str:
    return os.environ["QUE_SERVICE_KEY"]


@pytest.fixture
def que_jwt_secret() -> str:
    return os.environ["QUE_JWT_SECRET"]


@pytest.fixture
def client() -> TestClient:
    # Import after env is set so Settings() picks up test values.
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
