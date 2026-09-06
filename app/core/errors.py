"""User-safe error mapping — never leak provider internals to clients."""

from __future__ import annotations

from app.core.llm import LLMError

# Stable codes clients can branch on without parsing free text.
ERROR_LLM_UNAVAILABLE = "llm_unavailable"
ERROR_LLM_EMPTY = "llm_empty_response"
ERROR_LLM_NOT_CONFIGURED = "llm_not_configured"
ERROR_BAD_REQUEST = "bad_request"


def public_llm_error(exc: BaseException) -> tuple[str, str]:
    """Return (error_code, user_facing_message) for an LLM failure."""
    text = str(exc).lower()
    if isinstance(exc, LLMError) and "llm_api_key" in text:
        return ERROR_LLM_NOT_CONFIGURED, "QUE is not fully configured yet. Please try again later."
    if isinstance(exc, LLMError) and "empty response" in text:
        return ERROR_LLM_EMPTY, "QUE could not generate a reply. Please try again."
    return (
        ERROR_LLM_UNAVAILABLE,
        "QUE is temporarily unable to reach the language model. Please try again in a moment.",
    )
