"""LangChain chat model factory (OpenAI-compatible providers)."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.core.config import Settings, get_settings


class LLMError(RuntimeError):
    """Raised when the upstream LLM call fails or is misconfigured."""


def get_chat_model(*, settings: Settings | None = None) -> ChatOpenAI:
    """Build a LangChain chat model pointed at the configured OpenAI-compatible API."""
    cfg = settings or get_settings()
    if not cfg.llm_api_key:
        raise LLMError("LLM_API_KEY is not configured")
    return ChatOpenAI(
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        model=cfg.llm_model,
        temperature=cfg.llm_temperature,
        max_tokens=cfg.llm_max_tokens,
        timeout=cfg.llm_timeout_seconds,
        streaming=True,
    )
