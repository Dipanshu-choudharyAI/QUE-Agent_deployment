"""Production config guards — fail at boot, not at request time."""

from __future__ import annotations

import pytest

from app.core.config import Settings


def _base(**overrides) -> dict:
    base = dict(
        APP_ENV="production",
        QUE_JWT_SECRET="a-strong-random-secret-that-is-long-enough-32c",
        QUE_SERVICE_KEY="another-strong-random-secret-key",
        LLM_API_KEY="sk-real-key",
        CORS_ALLOW_ORIGINS="https://app.quizzer.example",
    )
    base.update(overrides)
    return base


def test_production_settings_ok_with_all_guards_set():
    Settings(**_base())  # should not raise


def test_production_requires_llm_api_key():
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        Settings(**_base(LLM_API_KEY="", LLM_API_KEY_1="", LLM_API_KEY_2="", LLM_API_KEY_3="",
                          LLM_API_KEY_4="", LLM_API_KEY_5="", LLM_API_KEY_6="", LLM_API_KEY_7="",
                          LLM_API_KEY_8=""))


def test_production_accepts_numbered_llm_api_key():
    Settings(**_base(LLM_API_KEY="", LLM_API_KEY_1="sk-real-key"))  # should not raise


def test_production_requires_cors_origins():
    with pytest.raises(ValueError, match="CORS_ALLOW_ORIGINS"):
        Settings(**_base(CORS_ALLOW_ORIGINS=""))


def test_production_requires_strong_jwt_secret():
    with pytest.raises(ValueError, match="QUE_JWT_SECRET"):
        Settings(**_base(QUE_JWT_SECRET="short"))


def test_local_env_does_not_enforce_any_guard():
    Settings(
        APP_ENV="local",
        QUE_JWT_SECRET="",
        QUE_SERVICE_KEY="",
        LLM_API_KEY="",
        CORS_ALLOW_ORIGINS="",
    )  # should not raise
