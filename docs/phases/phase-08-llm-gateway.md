# Phase 8 — LLM Gateway (round-robin models + keys)

**Status:** Done  
**Goal:** One chat call site, a pool of OpenRouter models and API keys, round-robin use, capped failover — without splicing two models into one SSE reply.

---

## Problem this phase solved

`get_chat_model()` built a single `ChatOpenAI` from `LLM_API_KEY` + `LLM_MODEL`. Extra keys in `.env` (`LLM_API_KEY_1` …) were ignored. One 429/5xx took the turn down.

Handbook Phase 8 wanted a **gateway**: complexity-aware routing, automatic failover, capped retries with backoff. Round-robin is how we **use** the pool; failover is how we **survive** provider errors.

**Upgrade story:** keep OpenAI-compatible OpenRouter only (no second SDK). Prefer `openai/gpt-4o-mini` on agent / `multi_step` turns, then walk the rest of the ring so free models stay in the pool.

---

## What we built

```text
Chat turn
    │
    ▼
Pick lane (RR key + RR model, or mini-first if agent/multi_step)
    │
    ▼
ChatOpenAI ainvoke / astream
    │
    ├─ ok → tokens + log model, key_index
    └─ 429/5xx/timeout → backoff → next key, then next model
         └─ exhausted (LLM_MAX_ATTEMPTS) → LLMError
```

| Piece | Location |
|---|---|
| Key / model lists | [`app/core/config.py`](../../app/core/config.py) — `llm_api_keys`, `llm_models` |
| Gateway | [`app/core/llm.py`](../../app/core/llm.py) — `ainvoke_chat`, `astream_chat`, `iter_failover_lanes` |
| Generate | `generate_node` → `ainvoke_chat(..., complexity, runtime_mode)` |
| Stream | `stream_turn_events` → `astream_chat` (failover only **before** the first token) |
| Embeddings | [`app/knowledge/embeddings.py`](../../app/knowledge/embeddings.py) — **first** key only |

Call sites stay `get_chat_model()` / `ainvoke_chat` / `astream_chat`. Nodes do not construct `ChatOpenAI`.

### Pool (OpenRouter ids)

1. `openai/gpt-4o-mini`
2. `google/gemma-4-31b-it:free`
3. `nvidia/nemotron-3.5-lightning:free`

Keys: every non-empty value among `LLM_API_KEY`, `LLM_API_KEY_1` … `LLM_API_KEY_8`. Same `LLM_BASE_URL`. Logs: `model` + `key_index` — never the secret.

### Routing (one turn)

1. **Key:** atomic round-robin `keys[i % len(keys)]`.
2. **Model:** atomic round-robin, **except** `complexity=multi_step` or `runtime_mode=agent` — first try `openai/gpt-4o-mini`, then the rest of the ring.
3. **Failover:** wait `min(cap, base * 2^attempt)`, next key, then next model. Cap `LLM_MAX_ATTEMPTS` (default 3).
4. Streaming: pick one lane before `astream`. Mid-token failure **fails the turn** (no mixed-model SSE).

Kill switch: `LLM_GATEWAY_RR=true` and RR is active only when 2+ keys or 2+ models.

---

## Config (`.env.example` placeholders only)

| Env | Default | Role |
|---|---|---|
| `LLM_MODELS` | three OpenRouter ids | Chat pool; `LLM_MODEL` is the alias if unset |
| `LLM_API_KEY` / `_1`… | empty | Numbered keys live in local `.env` only |
| `LLM_MAX_ATTEMPTS` | 3 | Per-turn failover cap |
| `LLM_RETRY_BASE_MS` / `LLM_RETRY_CAP_MS` | 200 / 2000 | Exponential backoff |
| `LLM_GATEWAY_RR` | true | Off → always first key + first model |

---

## Measured outcome

| Gate | Result |
|---|---|
| Unit | `tests/test_llm_gateway.py` — RR order, mini-first on agent, failover key→model, empty pool, no stream splice |
| Graph / pipeline | existing complete() tests patched onto `ainvoke_chat` |

Manual: three how-tos in a row with tools off — logs rotate `key_index` and model ids. A bad key in slot 0 should serve from the next lane.

---

## Interview talking points

- “Why a gateway?” → Multiple keys were already in env but unused; 429s need a next lane without a code change.
- “How do you avoid a cheap model on hard turns?” → Agent / `multi_step` still **start** on gpt-4o-mini, then fall through the ring.
- “What happens mid-stream?” → Do not splice two models into one reply. Fail the turn if the first token already went out.
- “Embeddings?” → First key only, so the Chroma index stays on one embedding account.

---

## What we deliberately did *not* do

- Native Anthropic / extra SDKs — all three models stay OpenAI-compatible OpenRouter
- Per-user sticky sessions
- Cost accounting beyond `model` + latency logs
- Putting chat RR on the embedding model

---

## How to verify

```bash
uv run pytest tests/test_llm_gateway.py tests/test_graph.py tests/test_pipeline.py -q
# Manual: three chats in a row with tools off — logs should rotate key_index and model ids
# Break primary by using a bad key in slot 0 — next key/model should serve
```
