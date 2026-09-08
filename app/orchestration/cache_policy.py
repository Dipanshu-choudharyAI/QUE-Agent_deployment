"""Phase 9 — freshness gates what QUE may cache.

Product how-tos are static. Live tool numbers are dynamic or critical and must
not reuse an LLM reply. Retrieval of product guides is slow-changing (docs
change on deploy), never personalized.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.orchestration.understanding import RequestUnderstanding

_LLM_OK_FRESHNESS = frozenset({"static"})
_RETRIEVAL_OK_FRESHNESS = frozenset({"static", "slow_changing"})


def allow_llm_reply_cache(understanding: RequestUnderstanding) -> bool:
    """True only for static how-tos — never live_tool / tool / critical / dynamic."""
    if understanding.freshness not in _LLM_OK_FRESHNESS:
        return False
    if understanding.data_need == "live_tool":
        return False
    if understanding.route == "tool":
        return False
    return True


def allow_retrieval_cache(understanding: RequestUnderstanding) -> bool:
    return allow_retrieval_from_fields(
        freshness=understanding.freshness,
        route=understanding.route,
        data_need=understanding.data_need,
    )


def allow_retrieval_from_fields(
    *,
    freshness: str | None,
    route: str | None,
    data_need: str | None,
) -> bool:
    """Product RAG may be cached; live/critical/tool turns skip it."""
    fresh = (freshness or "static").strip()
    if fresh == "critical":
        return False
    if (data_need or "").strip() == "live_tool":
        return False
    if (route or "").strip() == "tool":
        return False
    if fresh in _RETRIEVAL_OK_FRESHNESS:
        return True
    return (route or "").strip() == "knowledge"


def llm_reply_ttl(settings: Settings | None = None) -> float:
    cfg = settings or get_settings()
    return float(cfg.que_cache_llm_ttl_seconds)


def retrieval_ttl(settings: Settings | None = None) -> float:
    cfg = settings or get_settings()
    return float(cfg.que_cache_retrieval_ttl_seconds)
