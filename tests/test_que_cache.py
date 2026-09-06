"""QUE-local cache tests (not Quizzer Redis)."""

from __future__ import annotations

import random

from app.core.que_cache import (
    get_cached_intent,
    get_cached_llm_reply,
    reset_que_caches,
    set_cached_intent,
    set_cached_llm_reply,
)
from app.orchestration.canned import match_canned_reply


def test_intent_cache_roundtrip():
    reset_que_caches()
    assert get_cached_intent("helo") is None
    set_cached_intent("helo", "greeting")
    assert get_cached_intent("helo") == "greeting"


def test_llm_cache_roundtrip():
    reset_que_caches()
    key = "hist-demo"
    assert get_cached_llm_reply(key) is None
    set_cached_llm_reply(key, content="Open Exams first.", model="test-model")
    hit = get_cached_llm_reply(key)
    assert hit is not None
    assert hit["content"] == "Open Exams first."
    assert hit["model"] == "test-model"


def test_canned_avoids_same_variant_twice_in_conversation():
    reset_que_caches()
    cid = "conv-variant-1"
    first = match_canned_reply("hello", conversation_id=cid, rng=random.Random(0))
    second = match_canned_reply("hello", conversation_id=cid, rng=random.Random(0))
    assert first and second
    # Same RNG seed but last-variant exclusion should force a different line when possible.
    assert first.text != second.text
