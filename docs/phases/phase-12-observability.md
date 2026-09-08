# Phase 12 — Observability + Cost Governance

**Status:** Done  
**Goal:** Span traces, P50/P95/P99, token/USD cost, and budgets that skip work — without Datadog, Grafana, or PagerDuty.

---

## Problem this phase solved

Phase 1 already logged `request_id` and latency. After the gateway, cache, tools, and agent loop, we still could not answer: how slow is the tail, what did this model cost, and will a stuck loop become a surprise bill?

**Upgrade story:** keep logs. Add an in-process span tree and a ring of samples. Enforce token/call/USD ceilings so a bug returns an honest capacity reply instead of another OpenRouter call.

---

## What we built

```text
Chat turn
  → budget gate (user-hour USD)
  → TurnTrace (decide, cache, retrieve, tool, llm, guardrail, generate)
  → LLM usage_metadata → tokens + USD table
  → in-process ring (512)
  → GET /v1/ops/metrics  (service key only)
  → optional QUE_OBS_JSONL + scripts/summarize_obs.py
```

| Piece | Location |
|---|---|
| Spans | [`app/obs/trace.py`](../../app/obs/trace.py) `TurnTrace` |
| Ring + alerts | [`app/obs/metrics.py`](../../app/obs/metrics.py) |
| USD table | [`app/obs/cost.py`](../../app/obs/cost.py) |
| Budgets | [`app/obs/budget.py`](../../app/obs/budget.py) |
| Ops snapshot | [`GET /v1/ops/metrics`](../../app/api/ops.py) — **service key, not JWT** |
| Summarize | [`scripts/summarize_obs.py`](../../scripts/summarize_obs.py) |

Span names: `decide`, `cache`, `retrieve`, `tool`, `llm`, `guardrail`, `generate`.

`request_id` is bound on structlog context for the turn. Quizzer tool hops already send `X-Request-Id`; tool logs add `span=tool` + `latency_ms` on that same id. `user_id` is hashed (16 hex chars), same idea as Phase 11 online JSONL. Raw query, emails, and exam answers are never stored on the trace.

---

## Cost

`ainvoke_chat` / `astream_chat` extract LangChain `usage_metadata` or `response_metadata.token_usage`. Known OpenRouter id `openai/gpt-4o-mini` has a static USD table; `:free` models are $0; unknown models keep tokens and `usd=null`.

`cost_per_successful_task` on the snapshot is mean USD over non-error turns (canned / guardrail / cache count as success at $0).

---

## Budgets that stop work

| Knob | Default | Effect |
|---|---|---|
| `QUE_BUDGET_LLM_CALLS_PER_TURN` | 3 | No further `ainvoke` / stream once the turn already spent that many LLM calls |
| `QUE_BUDGET_TOKENS_PER_TURN` | 16000 | Skip LLM if prompt estimate + `LLM_MAX_TOKENS` would exceed the remaining cap |
| `QUE_BUDGET_USD_PER_USER_HOUR` | 0.50 | Sliding window; `0` disables. Exceeded → `budget:user` before the graph |

Capacity copy is a short honest reply (`budget:turn` / `budget:user`), same shape as a guardrail early reply. Checkpoint: `tests/test_obs.py` sets a tiny token budget, stubs the LLM, asserts **zero** calls.

---

## Alerts

Not PagerDuty. In-process windows for error-rate and USD-per-minute. On breach: one `que_alert` structlog line per cooldown (`QUE_ALERT_COOLDOWN_SECONDS`, default 60s) and `alerts[]` on `/v1/ops/metrics`. No PII in alert payloads.

---

## Out of scope (deliberate)

Datadog / Grafana / PagerDuty. Redis-backed metrics. Multi-instance aggregation (Phase 15).
