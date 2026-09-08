"""Sampled online eval logger — hashed identifiers only, no raw query text."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings


def _sha16(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]


def maybe_log_online_turn(
    *,
    request_id: str,
    user_id: str | None,
    query: str,
    route: str | None,
    freshness: str | None,
    cache_hit: bool = False,
    cache_layer: str | None = None,
    guardrail: str | None = None,
    groundedness_ok: bool | None = None,
    model: str | None = None,
    settings: Settings | None = None,
) -> None:
    cfg = settings or get_settings()
    if not cfg.que_eval_online_sample:
        return
    rate = float(cfg.que_eval_online_rate or 0.0)
    if rate <= 0.0 or random.random() > rate:
        return

    record: dict[str, Any] = {
        "request_id": request_id,
        "user_hash": _sha16((user_id or "").strip() or "anon"),
        "query_hash": _sha16((query or "").strip()),
        "query_looks_pii": "@" in (query or ""),
        "route": route,
        "freshness": freshness,
        "cache_hit": cache_hit,
        "cache_layer": cache_layer,
        "guardrail": guardrail,
        "groundedness_ok": groundedness_ok,
        "model": model,
    }
    path = Path(cfg.que_eval_online_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    except OSError:
        return
