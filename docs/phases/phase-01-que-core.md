# Phase 1 — QUE Core + Understanding + Basic Evals

**Status:** Done  
**Goal:** Make QUE a real product assistant for Quizzer: identity, conversation flow, scope discipline, canned FAQs, short-term memory, and a golden eval so later phases don’t silently break routing.

---

## Problem this phase solved

A raw “chat with GPT about our product” demo fails in production:

- Answers weather / coding / homework (off-product)
- Invents Quizzer UI that doesn’t exist
- Costs tokens for “hi” and “what can you do?”
- Forgets the last turn when the user says “explain that step by step”

**Upgrade story:** add an **orchestration layer** in front of the LLM — resolve → understand → fast-path or LangGraph dialog.

---

## What we built

### Thin identity (not product docs)

Persona lives only in `app/identity/` — who QUE is, tone, “don’t invent live numbers,” use knowledge privately. Product facts do **not** live here (that’s Phase 2).

### Conversational resolve

`app/orchestration/resolve.py` rewrites short follow-ups into full asks *before* scope checks, so “yes, step by step” isn’t refused as out-of-scope.

Later hardened so standalone asks like “How many exams…?” are **not** glued to the previous topic.

### Request Understanding

`app/orchestration/understanding.py` classifies:

- **scope** — in / out / clarify
- **intent** — howto, live_data, meta, …
- **route** — refuse | clarify | canned | tool | knowledge | dialog
- **data_need** — knowledge vs live_tool

Hard out-of-scope (weather, coding homework, …) always refuses.

### Canned replies

`app/orchestration/canned.py` — varied answers for hello / what can you do / what is Quizzer — **no LLM**, with variant rotation via QUE’s own cache.

### LangGraph dialog core

Minimal graph (grew later):

```text
prepare → generate   (+ knowledge/context/tools in later phases)
```

Short-term memory: LangGraph `MemorySaver`, keyed by `conversation_id` (+ optional `user_id`). New chat = new id.

### QUE-local cache

`app/core/que_cache.py` — in-process TTL/LRU for FAQ intents, canned variants, repeated LLM answers. **Not** Quizzer Redis.

### Evals + observability seeds

- Golden scope cases: `evals/scope_golden.json` + `scripts/run_scope_eval.py`
- Structured logs (`structlog`) with `request_id`, route, latency

---

## How a turn works (after Phase 1)

```text
POST /v1/chat[/stream]
  → decide_turn()
       resolve_request()          # follow-ups → full query
       classify_request()         # scope / intent / route
       match_canned_reply()?      # early exit
       refuse / clarify?          # early exit
  → else LangGraph prepare → generate
  → ChatResponse or SSE tokens
```

---

## Key files

| File | Role |
|---|---|
| `app/identity/persona.py` | System prompt + `IDENTITY_VERSION` / phase metadata |
| `app/orchestration/pipeline.py` | `decide_turn`, `complete`, later `stream_turn_events` |
| `app/orchestration/resolve.py` | Follow-up → standalone rewrite |
| `app/orchestration/understanding.py` | Scope / intent / route classifier |
| `app/orchestration/canned.py` | Zero-LLM FAQ replies |
| `app/orchestration/history.py` | Strip client `system`, cap history length |
| `app/graphs/que_graph.py` | Compiled LangGraph |
| `app/graphs/nodes.py` | `prepare_node`, `generate_node`, … |
| `app/graphs/state.py` | `QueGraphState` TypedDict |
| `app/graphs/memory.py` | MemorySaver helpers / thread ids |
| `app/core/que_cache.py` | In-process cache |
| `evals/scope_golden.json` | Scope/routing golden set |
| `scripts/run_scope_eval.py` | Eval runner |
| `tests/test_resolve.py`, `tests/test_pipeline.py`, … | Unit coverage |

---

## Important improvements

1. **Understanding before generation** — refuse cheaply; don’t “hope the prompt behaves.”
2. **Resolve before understand** — follow-ups stay in-scope.
3. **Canned for meta** — lower cost, snappier UX, consistent branding.
4. **Eval from day one** — later RAG/tools regressions are comparable to a Phase 1 baseline.
5. **Memory is short-term and explicit** — new chat clears thread; no fake long-term memory.

---

## Interview talking points

- “How do you keep the bot on-product?” → deterministic understanding + hard OOS patterns, not only system prompt.
- “Why canned replies?” → meta intents don’t need a frontier model; variance comes from a small curated set.
- “How do you test routing?” → golden JSON + script; CI can gate accuracy.
- “What’s MemorySaver?” → in-process checkpoint for `dialog` per `conversation_id`; not multi-replica durable store yet.

---

## What we deliberately did *not* do yet

- Product knowledge RAG (Phase 2)
- Page/exam UI context (Phase 3)
- Live account tools (Phase 4)

---

## How to verify

```bash
uv run python scripts/run_scope_eval.py
uv run pytest tests/test_resolve.py tests/test_pipeline.py -q
```
