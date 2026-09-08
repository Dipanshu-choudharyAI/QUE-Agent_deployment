# Phase 13 — Reliability

**Status:** Done  
**Goal:** Document and test degraded behavior for every real dependency — without chaos automation.

---

## Problem this phase solved

Failover existed for 429/5xx, and tools already had a circuit breaker. `_is_retryable` still treated **401/403 as retryable**, so a bad key could walk the whole lane list. There was no LLM-provider circuit. Failure modes were not a documented matrix with tests.

**Upgrade story:** write the matrix first, then make retries and circuits match it.

---

## Failure matrix

See [`docs/FAILURE_MATRIX.md`](../FAILURE_MATRIX.md). Rows:

| Failure | Expected |
|---|---|
| LLM timeout / 5xx | Next lane or public try-again |
| LLM 401/403/400 | Do **not** retry |
| Provider circuit open | Skip OpenRouter; try-again message |
| Tool timeout | `TOOL_ERROR` / agent stop — no hang |
| Tool circuit open | Existing executor path |
| Cache disabled / miss | Retrieve + LLM, still correct |
| Invalid JSON from Quizzer | `ToolClientError` → `TOOL_ERROR` |

---

## Retry policy

[`app/core/llm.py`](../../app/core/llm.py) `_is_retryable`: **not** 400/401/403/404/422. Keep 408/429/5xx/timeouts. Stream still does not splice models after the first token.

---

## LLM circuit

Process-local, like tools: `QUE_LLM_CIRCUIT_FAILURES` (default 5) and `QUE_LLM_CIRCUIT_TTL_SECONDS` (default 30). Open → `LLMError("LLM circuit open")` mapped to the public try-again string. `QUE_LLM_CIRCUIT_FAILURES=0` disables the breaker.

Quizzer tool circuit was already in [`app/tools/executor.py`](../../app/tools/executor.py); tests now force it open and assert Quizzer is not called.

---

## Tests

[`tests/test_reliability.py`](../../tests/test_reliability.py) plus 401 coverage in [`tests/test_llm_gateway.py`](../../tests/test_llm_gateway.py).

```bash
uv run pytest tests/test_obs.py tests/test_reliability.py tests/test_llm_gateway.py tests/test_guardrails.py -q
```

---

## Out of scope (deliberate)

Chaos automation. Async job queues (Phase 14). Multi-instance load tests (Phase 15). Changing Quizzer tool contracts beyond the `X-Request-Id` header we already send.
