# Phase 9 — Caching + Data Freshness

**Status:** Done  
**Goal:** Isolation and freshness **before** more speed. Static how-tos may be reused; live account numbers must not.

---

## Problem this phase solved

QUE already had an in-process TTL/LRU cache ([`app/core/que_cache.py`](../../app/core/que_cache.py)) and Request Understanding already labeled `freshness`. They were **not wired together**.

`complete` / `stream_turn_events` cached **every** LLM reply, including `route=tool` and `freshness=dynamic|critical`. Repeating “how many exams did I create?” could skip Quizzer and replay a stale count.

Fingerprint included `user_id` only when present — missing uid collided with other anonymous how-tos. There was no adversarial isolation test.

**Upgrade story:** keep in-process maps (not Redis). Let Phase 1 freshness decide what is stored. Never cache Quizzer tool JSON.

---

## What we built

```text
Request Understanding (freshness)
        │
        ▼
cache_policy
   ├─ static how-to     → LLM reply cache (uid always in key)
   ├─ static/slow RAG   → retrieval TTL (query + mode, not user)
   ├─ dynamic (tools)   → no LLM / no retrieval cache
   └─ critical (live/today) → bypass reply caches
```

| Piece | Location |
|---|---|
| Policy | [`app/orchestration/cache_policy.py`](../../app/orchestration/cache_policy.py) |
| Maps | [`app/core/que_cache.py`](../../app/core/que_cache.py) — intent, LLM, variant, **retrieval** |
| Fingerprint | `_history_fingerprint` always `uid:{id or anon}` |
| Generate/stream | skip get/set LLM cache unless `allow_llm_reply_cache` |
| RAG | `select_knowledge(..., use_cache=)` |

### Classification

| Data | Freshness | Cache |
|---|---|---|
| FAQ intent / canned | static | existing |
| How-to LLM reply | static | LLM map; **user_id required in key** |
| Product RAG chunks | slow_changing | retrieval map (docs, not people) |
| Insight tools / agent | dynamic | **none** |
| “live” / “today” | critical | **bypass** |

Classifier how-tos stay `freshness=static`. Retrieval policy treats product guides as slow-changing even on those turns.

---

## Measured outcome

| Gate | Result |
|---|---|
| Isolation | User A how-to is not served to User B (`tests/test_que_cache.py`) |
| Anon vs named | `uid:anon` ≠ `uid:real-user` |
| Critical | live/today asks do not write the LLM reply cache |
| TTL knobs | `QUE_CACHE_LLM_TTL_SECONDS` (900) ≠ `QUE_CACHE_RETRIEVAL_TTL_SECONDS` (1800) |

---

## Interview talking points

- “How do you stop User A leaking to User B?” → LLM keys always include `user_id` (or `anon`). Isolation test is the gate.
- “What sets TTL?” → Data character: static how-tos 15 min, retrieval 30 min, live tools not cached.
- “Why not cache tool results?” → Dynamic by definition; a fast wrong count is worse than a slower Quizzer call.

---

## What we deliberately did *not* do

- Redis / shared cache across workers
- Semantic (embedding) response cache
- Tool-result cache
- Provider prompt-prefix cache
- Externalizing MemorySaver

---

## How to verify

```bash
uv run pytest tests/test_que_cache.py tests/test_pipeline.py tests/test_graph.py -q
```
