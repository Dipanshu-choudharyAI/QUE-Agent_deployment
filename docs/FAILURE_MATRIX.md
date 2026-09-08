# Failure matrix (Phase 13)

Correct **degraded** behavior for every real dependency QUE has. These rows are
triggered in unit tests (`tests/test_reliability.py`, `tests/test_llm_gateway.py`),
not chaos automation.

QUE has no Quizzer DB and no Redis. “Cache outage” means the in-process cache is
disabled or misses. “Invalid JSON” is the Quizzer tool envelope, not an LLM
planner (QUE does not parse model JSON for tool calls).

| Failure | Expected | Where | Test |
|---|---|---|---|
| LLM timeout / 5xx | Next gateway lane, then public try-again (`LLMError` → 502) | `app/core/llm.py` `ainvoke_chat` / `astream_chat` | `test_ainvoke_retries_5xx_then_succeeds`, existing 429 failover |
| LLM 401 / 403 / 400 | **Do not retry.** Fail that turn. | `_is_retryable` | `test_ainvoke_does_not_retry_401`, `test_failover_does_not_advance_on_401` |
| LLM provider circuit open | Skip OpenRouter; `LLMError("LLM circuit open")` → public try-again | `QUE_LLM_CIRCUIT_FAILURES` / `QUE_LLM_CIRCUIT_TTL_SECONDS` | `test_llm_circuit_open_skips_provider` |
| Tool timeout | `TOOL_ERROR` / agent `error` stop — no hang | `ToolClientError("upstream_timeout")` | `test_tool_timeout_is_tool_error_not_hang` |
| Tool circuit open | Executor returns unavailable `TOOL_ERROR` without calling Quizzer | `QUE_TOOL_CIRCUIT_*` | `test_tool_circuit_open_returns_tool_error` |
| Cache disabled / miss | Fall through to retrieve + LLM; answer still correct | `QUE_CACHE_ENABLED=false` | `test_cache_disabled_falls_through_to_llm` |
| Invalid JSON from Quizzer | `ToolClientError` → `TOOL_ERROR` | `app/tools/quizzer_client.py` | `test_invalid_quizzer_json_is_tool_client_error` |
| Write action: Quizzer unreachable on confirmed "yes" | Deterministic "I couldn't do that… Nothing was changed." — never a fake success | `app/tools/executor.execute_confirmed_write_action` | `tests/test_write_tools.py` |
| Write action: role/budget/circuit fails at confirm time | Deny with a deterministic reply; pending action already cleared, no retry loop possible | `execute_confirmed_write_action` | `tests/test_write_tools.py::test_execute_confirmed_write_action_denies_wrong_role` |
| Write action: stale/ambiguous reply to a pending confirmation | Pending action discarded; turn processed normally (no accidental execution) | `app/orchestration/pending_actions.py` | `tests/test_write_tools.py` |
| Rate limit exceeded | `429` with `Retry-After`; service-key callers exempt | `app/core/ratelimit.py` | `tests/test_ratelimit.py` |
| `/ready` dependency down (LLM key / index / Quizzer tools) | `503` with a `checks` breakdown — never a bare 200 | `app/api/health.py` | `tests/test_health.py` |

Retries keep **408 / 429 / 5xx / timeouts**. Permission and malformed requests
are never retried — retrying them only burns the turn budget.

Stream failover still does **not** splice models after the first token.
