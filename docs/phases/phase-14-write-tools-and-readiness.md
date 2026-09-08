# Phase 14 — Write tools (human-in-the-loop), rate limits, production readiness

## Problem

Through Phase 13, QUE could only *read* Quizzer data. Testers needed QUE to
actually **do** things (publish an exam, nudge students, clean up a draft),
but a chat assistant that mutates data on its own say-so is a liability:
one hallucinated "done!" or one prompt-injected "yes, delete it" and a
teacher loses real work. Separately, before real testers hit the service:
no rate limiting (one runaway client loop could hammer the LLM budget for
everyone), and `enforce_production_guards` didn't check the two things that
actually break chat in prod (`LLM_API_KEY`, `CORS_ALLOW_ORIGINS`) — both
would fail *at request time* instead of at boot.

## Design

### Write tools — propose, confirm, execute (never LLM-decided)

Three new tools in `app/tools/registry.py`: `publish_exam`, `notify_students`,
`delete_draft_exam`. All have `risk_tier="write"`, which the existing Phase 5
policy engine (`app/policy/engine.py`) already treated as
`requires_confirmation=True` — that seat existed since Phase 5 and had never
been filled in.

The flow is a strict two-phase split, and the *decision to mutate* never
touches the LLM:

1. **Propose** (normal graph path). `select_tool` picks the tool from tight
   keyword rules in `app/tools/select.py` (e.g. "publish this exam", never
   "how do I publish"). `execute_selected_tool` → `invoke_tool_selection`
   sees `requires_confirmation`, and instead of calling Quizzer it:
   - stores a `PendingAction` in `app/orchestration/pending_actions.py`
     (in-process TTL store, 5 minutes, keyed by the same thread key memory
     uses — `app/graphs/memory.make_thread_id`)
   - returns a `TOOL_CONFIRM` system block; the persona
     (`app/identity/persona.py`) instructs the LLM to relay that question
     *verbatim and nothing else* — it cannot execute or embellish.
2. **Confirm** (next turn, outside the graph entirely).
   `app/orchestration/pipeline.resolve_write_confirmation` runs right after
   `decide_turn` for *every* turn (cheap dict lookup when nothing is
   pending). A tight regex (`is_affirmative_reply` / `is_negative_reply` in
   `pending_actions.py`) checks the raw reply:
   - **"yes"** → clears the pending action, calls
     `app/tools/executor.execute_confirmed_write_action` (async, does the
     real Quizzer POST with the stored `idempotency_key`), and returns a
     **deterministic, non-LLM** success/failure sentence
     (`ToolSpec.success_template`). The model never gets a chance to
     paraphrase whether something actually happened.
   - **"no" / "cancel" / anything else** → clears the pending action,
     replies "Cancelled — nothing was changed." Any other wording (which
     could carry an injected instruction) is treated as ambiguous and
     safely discards the pending action rather than executing it.

Defense in depth:

- Write tools are excluded from the bounded agent loop entirely
  (`runtime_mode.decide_runtime_mode` always routes them to the single-tool
  `workflow` path; `agent_loop.py` also excludes `WRITE_TOOL_NAMES` from its
  own selection as a second layer) — one mutation per confirmed turn, never
  chained.
- `execute_confirmed_write_action` re-validates the kill switch, the tool
  budget, a **separate stricter per-user-per-hour cap**
  (`QUE_BUDGET_WRITE_ACTIONS_PER_HOUR`, `app/obs/budget.allow_write_action`),
  the tool circuit breaker, and role policy again — the propose-time checks
  could be stale by the time "yes" arrives.
- Quizzer (`backend/api/que_internal_tools.py`) re-checks ownership and
  current state itself (never trusts that QUE already confirmed with the
  human) and dedupes on `idempotency_key` for 10 minutes so a retried HTTP
  call can't double-publish/double-delete.
- `delete_draft_exam` is intentionally narrower than Quizzer's own
  `DELETE /quizzes/{id}` — only a genuinely unpublished, zero-attempt draft
  is hard-deleted. Anything riskier routes back to the full UI flow.
- New output-guardrail check (`ungrounded_number` in
  `app/guardrails/output.py`, reusing
  `app/evals/groundedness.find_invented_numbers`) now applies to **every**
  role, not just students — any number in a reply that isn't grounded in a
  `TOOL_RESULT` block is blocked.

### Rate limiting

`app/core/ratelimit.py` — in-process token bucket, per authenticated user
(falls back to client IP for anonymous callers). Deliberately lenient
(`QUE_RATE_LIMIT_PER_MINUTE=60` + `QUE_RATE_LIMIT_BURST=20` by default) so
normal typing/retries never trip it; service-key (server-to-server) callers
are exempt since they aren't end users. Wired into `/v1/chat` and
`/v1/chat/stream` in `app/api/chat.py`, returns `429` with `Retry-After`.

### Production readiness

- `app/core/config.enforce_production_guards` now also requires at least one
  `LLM_API_KEY*` and a non-empty `CORS_ALLOW_ORIGINS` outside local/dev —
  both used to fail silently at first request instead of at boot.
- `GET /ready` (`app/api/health.py`) actually checks dependencies: LLM key
  present, knowledge index present (when RAG is on), knowledge manifest
  valid, and a live Quizzer tools-health probe
  (`app/tools/quizzer_client.check_tools_health`) when tools are enabled.
  Returns `503` when any check fails. `GET /health` stays pure liveness.
  `Dockerfile`'s `HEALTHCHECK` now hits `/ready`.
- [`../RUNBOOK.md`](../RUNBOOK.md) — rollback steps + `.env.staging.example`.

## Files

- `app/tools/registry.py` — `publish_exam`, `notify_students`,
  `delete_draft_exam` (+ `confirmation_prompt`/`success_template` on
  `ToolSpec`, `WRITE_TOOL_NAMES`)
- `app/tools/select.py` — tight write-action keyword rules; monitoring/arena
  page defaults; narrowed `tool_route_account` fallback
  (`_looks_like_inventory_ask`)
- `app/tools/executor.py` — propose branch (`propose_action`,
  `format_tool_confirm_message`), `execute_confirmed_write_action`,
  `format_write_result_message`
- `app/tools/quizzer_client.py` — `idempotency_key` passthrough,
  `check_tools_health`
- `app/orchestration/pending_actions.py` (new) — TTL store +
  `is_affirmative_reply`/`is_negative_reply`
- `app/orchestration/pipeline.py` — `resolve_write_confirmation`
- `app/orchestration/runtime_mode.py`, `app/orchestration/agent_loop.py` —
  write tools excluded from the agent loop
- `app/obs/budget.py` — `allow_write_action` / `record_write_action`
- `app/guardrails/output.py`, `app/evals/groundedness.py` —
  `ungrounded_number` check for all roles (`find_invented_numbers`)
- `app/guardrails/patterns.py` — a few more jailbreak patterns (act as
  admin, developer mode, skip confirmation)
- `app/core/ratelimit.py` (new), `app/api/chat.py` — rate limiting
- `app/core/config.py` — production guards, `QUE_RATE_LIMIT_*`,
  `QUE_BUDGET_WRITE_ACTIONS_PER_HOUR`
- `app/api/health.py` — real `/ready`; `Dockerfile` HEALTHCHECK
- Quizzer: `backend/api/que_internal_tools.py` — the three write handlers,
  idempotency dedupe, `WRITE_TOOL_NAMES`

## Interview notes

- "Why doesn't the LLM decide whether to execute the mutation?" — because an
  LLM can be prompt-injected or can hallucinate confidence. The *only* code
  path that calls Quizzer's write endpoint is a tight regex match on the
  human's very next reply, run entirely outside the graph/LLM.
- "What stops a stale 'yes' three days later from firing?" — a 5-minute TTL
  on the pending action, and clearing it the moment any reply (yes, no, or
  ambiguous) is seen.
- "What if the HTTP call to Quizzer succeeds but QUE never gets the
  response (timeout)?" — the idempotency key is stored with the pending
  action and sent on every attempt; Quizzer dedupes on it for 10 minutes so
  a client-side retry replays the same result instead of double-executing.
