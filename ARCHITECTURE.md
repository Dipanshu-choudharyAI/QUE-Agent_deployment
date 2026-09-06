# QUE-Agent — architecture & file-by-file guide

This document explains how QUE is structured, how chat connects to Quizzer, and what every important file does.

**Current phase:** LangGraph chat (`prepare → knowledge → generate`) + product knowledge packs.  
No Quizzer DB access, no embeddings, no account-action tools yet.

---

## Big picture

QUE is an **independently deployable microservice**. It does **not** import Quizzer packages and does **not** talk to Quizzer’s database.

Chat traffic does **not** proxy through Quizzer Backend (that would load Quizzer with every SSE token). Quizzer only mints a short-lived access token after cookie auth; the browser then calls QUE directly.

```text
┌─────────────┐  cookie JWT   ┌──────────────────┐
│ Quizzer UI  │ ────────────► │ Quizzer Backend  │
│ (browser)   │  POST /que/session               │
│             │ ◄──────────── │ mints Que JWT    │
└──────┬──────┘               └──────────────────┘
       │
       │  Authorization: Bearer <que_access>
       │  POST /v1/chat/stream  (SSE stays on QUE)
       ▼
┌─────────────┐                               ┌─────────────┐
│  QUE-Agent  │ ────────────────────────────► │     LLM     │
│   :8100     │                               └─────────────┘
└─────────────┘
```

| Rule | Why |
|---|---|
| Browser → QUE for chat | Offload Quizzer; lower latency for streaming |
| Quizzer → mint only (`/que/session`) | Proves the user is logged in; light/rare request |
| Shared `QUE_JWT_SECRET` | QUE verifies tokens Quizzer minted |
| `QUE_SERVICE_KEY` never in browser | Server/ops + future QUE→Quizzer tools only |
| History sent each turn | QUE is **stateless** (no chat DB / checkpointer yet) |
| `user_id` opaque | From JWT `sub` / request body — audit only, never DB reads |

Deploy shape: `app.quizzer…` (frontend/API) and `que.quizzer…` (this service). Set QUE `CORS_ALLOW_ORIGINS` to the frontend origin(s).

---

## Auth (two credentials)

Full product A→Z (Quizzer workspace + attempt + QUE, expiries, re-login): **[AUTH.md](AUTH.md)**.  
Phased build roadmap (open in browser): **[docs/que-agent-handbook.html](docs/que-agent-handbook.html)**.

Either is enough on `/v1/*`:

1. **`Authorization: Bearer <token>`** — `typ=que_access`, `aud=que-agent`, `iss=quizzer`, signed with `QUE_JWT_SECRET`
2. **`X-Que-Service-Key`** — shared service secret (internal callers; used by Quizzer BFF on `feat/que-agent-wip`)

Token mint (Quizzer, when token-exchange is wired): `create_que_access_token`  
Token verify (QUE): `app/core/tokens.py` → `decode_que_access_token`  
HTTP gate (QUE): `app/core/security.py` → `require_chat_auth`

---

## Request path (one chat turn)

```text
Browser already holds Que access_token (from POST /que/session)

POST /v1/chat  or  POST /v1/chat/stream
        │
        ▼
app/api/chat.py                 # HTTP + require_chat_auth
        │
        ▼
app/services/chat_service.py    # complete vs SSE framing
        │
        ▼
app/orchestration/pipeline.py
  decide_turn → Request Understanding (scope/intent/route)
       ├─ refuse / clarify / tool-pending / canned  → early reply (no LLM)
       └─ knowledge → LangGraph
              prepare  → sanitize history + inject identity
              knowledge → CORE.md + up to 2 keyword-matched guides
              generate → LLM reply
        │
        ▼
ChatResponse  or  SSE: meta(+understanding) → token* → done
```

Quizzer Backend is **not** on this path after the session mint.

Golden scope eval: `evals/scope_golden.json` · `uv run python scripts/run_scope_eval.py`  
Build tracker: [`docs/BUILD_PROGRESS.md`](docs/BUILD_PROGRESS.md) · handbook: [`docs/que-agent-handbook.html`](docs/que-agent-handbook.html)

---

## Repo tree

```text
Que-Agent/
├── AGENTS.md                 # Short rules for coding agents
├── ARCHITECTURE.md           # This file
├── README.md                 # Quick start & endpoints
├── pyproject.toml            # Package + deps + ruff/pytest
├── uv.lock                   # Locked deps (CI uses --frozen)
├── Dockerfile                # Production image
├── .env.example              # Config template
├── .github/workflows/ci.yml  # Secret scan + lint + audit + tests
├── scripts/start.sh          # gunicorn + uvicorn workers
├── app/                      # Python service
│   ├── run.py                # Local entry: python -m app.run
│   ├── main.py               # FastAPI app factory
│   ├── api/                  # HTTP routers
│   ├── core/                 # Config, auth, LLM, errors
│   ├── schemas/              # Request/response models
│   ├── services/             # Thin HTTP service layer
│   ├── orchestration/        # Pipeline + history helpers
│   ├── graphs/               # LangGraph agent
│   ├── identity/             # Thin persona (who QUE is)
│   └── knowledge/            # Pack selection code
├── knowledge/                # Markdown product brain (data)
│   ├── CORE.md
│   ├── manifest.json
│   ├── README.md
│   └── guides/*.md
└── tests/                    # pytest
```

---

## Layer map (who owns what)

| Layer | Folder | Responsibility |
|---|---|---|
| HTTP | `app/api/` | Routes, status codes, SSE response headers |
| Service | `app/services/` | SSE framing, call pipeline |
| Orchestration | `app/orchestration/` | Map request ↔ graph; history sanitize |
| Agent | `app/graphs/` | `prepare → knowledge → generate` |
| Identity | `app/identity/` | Short system prompt / persona metadata |
| Knowledge code | `app/knowledge/` | Select which markdown packs to inject |
| Knowledge data | `knowledge/` | Product guides (not Python) |
| Core | `app/core/` | Settings, service-key auth, LLM factory, public errors |
| Schemas | `app/schemas/` | Pydantic contracts for chat |

---

## File-by-file — application (`app/`)

### Entrypoints

#### `app/run.py`
Local/dev launcher. Loads settings and starts **uvicorn** on `HOST`/`PORT` (default `8100`), with reload in local env.

```bash
uv run python -m app.run
```

#### `app/main.py`
FastAPI factory (`create_app`):

- Lifespan logging (env, version, model, insecure-auth flag)
- CORS for Quizzer frontend origins (`CORS_ALLOW_ORIGINS`) so browser → QUE works
- Mounts `health` + `chat` routers
- Docs (`/docs`) only when `APP_ENV` is local/dev

Exports module-level `app` for gunicorn/uvicorn.

---

### HTTP API — `app/api/`

#### `app/api/health.py`
- `GET /health` — no auth  
- Returns `{ status, service, version, env }`  
- Used by Docker `HEALTHCHECK` and load balancers

#### `app/api/chat.py`
All routes under `/v1` require `require_chat_auth` (Bearer Que JWT **or** service key).  
JWT `sub` is copied into `user_id` when the client omits it.

| Endpoint | What it does |
|---|---|
| `GET /v1/identity` | Persona metadata (no LLM) |
| `POST /v1/chat` | Full reply via `chat_service.chat_complete` |
| `POST /v1/chat/stream` | SSE stream via `chat_service.chat_stream_events` |

Maps `ValueError` → 400, `LLMError` → 503 (not configured) or 502 (upstream fail).

---

### Schemas — `app/schemas/`

#### `app/schemas/chat.py`
Pydantic contracts:

- `ChatMessage` — `role` ∈ `system|user|assistant`, content 1–32k chars (stripped)
- `ChatRequest` — `messages` (1–100), optional `conversation_id`, optional opaque `user_id`
- `ChatResponse` — assistant `message` + `conversation_id` + `model`

Client-sent `system` messages are **dropped** later in `sanitize_history` so callers cannot override identity.

---

### Core — `app/core/`

#### `app/core/config.py`
`pydantic-settings` `Settings` from env / `.env`:

- App: `APP_ENV`, name, version, CORS (frontend origins for browser → QUE)
- Auth: `QUE_JWT_SECRET` (+ algo/aud/iss), `QUE_SERVICE_KEY`, `ALLOW_INSECURE_LOCAL_NO_AUTH`
- LLM: key, base URL, model, timeout, max tokens, temperature
- Memory: `QUE_MEMORY_ENABLED`, `QUE_MEMORY_MAX_TURNS` (LangGraph MemorySaver)
- Server: host, port, log level

**Production guards:** insecure no-auth forbidden outside local; weak JWT/service secrets rejected.  
`get_settings()` is `@lru_cache`’d.

#### `app/core/tokens.py`
Decode/verify Quizzer-minted Que access JWTs (`typ=que_access`, audience/issuer checks).

#### `app/core/security.py`
`require_chat_auth`:

1. Prefer `Authorization: Bearer` → `decode_que_access_token`
2. Else `X-Que-Service-Key` (constant-time compare)
3. Local escape hatch: `ALLOW_INSECURE_LOCAL_NO_AUTH=true` only when `is_local`

Browser never receives the service key.

#### `app/core/llm.py`
- `LLMError` — normalized failure type
- `get_chat_model()` — builds LangChain `ChatOpenAI` against any OpenAI-compatible API (OpenRouter by default), streaming enabled

All LLM access should go through this module.

#### `app/core/errors.py`
Maps exceptions to **stable public codes** (no provider stack traces):

| Code | Meaning |
|---|---|
| `llm_not_configured` | Missing `LLM_API_KEY` |
| `llm_empty_response` | Model returned empty |
| `llm_unavailable` | Generic upstream failure |
| `bad_request` | Validation / empty history |

---

### Services — `app/services/`

#### `app/services/chat_service.py`
Thin HTTP-facing layer over the pipeline:

- `chat_complete` → `pipeline.complete`
- `chat_stream_events` → SSE JSON events:
  1. `meta` (conversation_id, model, identity)
  2. `token` chunks from `stream_tokens`
  3. `done`
  - If stream yields zero tokens / fails → **one** fallback to non-stream `complete`, then fake-chunk the text so the UI still “streams”
  - On total failure → `error` event with public code/message

---

### Orchestration — `app/orchestration/`

#### `app/orchestration/history.py`
`sanitize_history`:

1. Keep only `user` / `assistant` (strip client `system`)
2. Cap to last ~16 messages
3. Cap ~10k characters from the end (preserve recent turns)
4. Guarantee at least one user message remains

Protects latency/cost and identity integrity.

#### `app/orchestration/pipeline.py`
Bridge between HTTP schemas and LangGraph:

| Function | Role |
|---|---|
| `_request_to_input` | Build initial `QueGraphState` |
| `prepare_turn` | Run prepare→knowledge without LLM (tests) |
| `complete` | `graph.ainvoke` → extract last AI text → `ChatResponse` |
| `stream_tokens` | Same prepare→knowledge path, then `model.astream` |

Streaming **does not** use the compiled graph’s `generate` node; it reuses `prepare_node` + `knowledge_node` so context matches non-stream, then streams tokens directly.

---

### LangGraph agent — `app/graphs/`

#### `app/graphs/state.py`
`QueGraphState` TypedDict shared across nodes:

| Field | Purpose |
|---|---|
| `input_messages` | Raw role/content from HTTP |
| `dialog` | Short-term user/assistant turns (checkpointed) |
| `messages` | Ephemeral prompt for this turn (identity + knowledge + dialog) |
| `sources_used` | Audit tags (`identity`, `memory`, `knowledge`, `llm`, …) |
| `conversation_id` / `user_id` | Thread key for MemorySaver (`user_id:conversation_id`) |
| `identity_version` | Bumped with persona changes |
| `knowledge_packs` | Pack ids injected this turn |
| `memory_turns` | Length of `dialog` after merge/append |
| `model_name` | From generate |

#### `app/graphs/memory.py`
In-process LangGraph `MemorySaver` helpers: thread ids, dialog merge/trim, enable flag
(`QUE_MEMORY_ENABLED`, `QUE_MEMORY_MAX_TURNS`). Memory is per worker process — not shared
across replicas (swap checkpointer for Postgres/Redis later if needed).

#### `app/graphs/que_graph.py`
Builds and compiles:

```text
START → prepare → knowledge → generate → END
```

`get_que_graph()` is process-cached (`@lru_cache`) and compiled **with** `MemorySaver` when
memory is enabled. Pass `config={"configurable": {"thread_id": ...}}` so `dialog` persists.

#### `app/graphs/nodes.py`
Three nodes (one job each):

1. **`prepare_node`** (sync)  
   Merge checkpoint `dialog` with incoming turn → build prompt from memory → prepend identity.

2. **`knowledge_node`** (sync)  
   `select_knowledge(input_messages)` → insert knowledge as a second system message (right after identity) → record pack ids.

3. **`generate_node`** (async)  
   `get_chat_model().ainvoke(messages)` → append `AIMessage` to `dialog` + prompt → record model name.

Reserved for later (comments in file): `context_node` (UI/role context), `tools_node` (authorized Quizzer API tools).

---

### Identity — `app/identity/`

#### `app/identity/persona.py`
Thin persona — **not** product docs:

- `IDENTITY_VERSION` — bump when identity text changes meaningfully
- `build_system_prompt()` — short rules: who QUE is, use packs privately, plain text, no live-account claims
- `identity_metadata()` — `{ name, product, identity_version, phase }` for clients/logs

#### `app/identity/__init__.py`
Re-exports persona helpers.

---

### Knowledge selection — `app/knowledge/`

#### `app/knowledge/retrieve.py`
Runtime selection over markdown under `/knowledge` (no embeddings):

1. Load `manifest.json` (cached)
2. Always include docs with `"always": true` (`CORE.md`)
3. Score guides by keyword hits on the **latest user message**
4. Take top `max_guides` (default 2)
5. If query has no hits → fallback to `lifecycle` guide
6. Cap total injected chars (~12k)
7. Prefix with “PRIVATE REFERENCE…” instructions

#### `app/knowledge/__init__.py`
Exports `select_knowledge`, `KnowledgeSelection`, `clear_knowledge_caches`.

---

## File-by-file — knowledge data (`knowledge/`)

This folder is the **product brain**. Code in `app/knowledge/` only selects and injects it.

| File | Role |
|---|---|
| `knowledge/README.md` | How to write guides (SAY/NEVER, click paths) |
| `knowledge/CORE.md` | Always injected — product map + answer contract |
| `knowledge/manifest.json` | Pack index: paths, `always`, keywords, `max_guides` |
| `knowledge/guides/navigation.md` | Sidebar vs exam tabs / where things live |
| `knowledge/guides/publish-share.md` | Create → approve → publish → link window |
| `knowledge/guides/empty-data.md` | Empty Students / Analytics / Dashboard |
| `knowledge/guides/live-monitoring.md` | LIVE, Monitoring, Results |
| `knowledge/guides/lifecycle.md` | End-to-end graded loop (also keyword fallback) |
| `knowledge/guides/verification.md` | Pre-exam identity form (not grading) |
| `knowledge/guides/arena.md` | Arena ≠ graded exam |

Guide style: teacher question → click path → decision tree → **SAY** / **NEVER**.  
Live counts (“how many students…”) must wait for future tools — guides must not invent them.

---

## File-by-file — tests (`tests/`)

| File | Covers |
|---|---|
| `tests/conftest.py` | Env defaults, clear settings/graph caches, `TestClient` |
| `tests/test_health.py` | `/health` |
| `tests/test_chat.py` | Service-key + Que JWT auth, validation, stream without LLM key |
| `tests/test_graph.py` | Graph topology / nodes |
| `tests/test_pipeline.py` | prepare/complete/stream wiring |
| `tests/test_knowledge.py` | Keyword selection, CORE always-on, caches |

Tests avoid live LLM calls where possible; CI runs with empty `LLM_API_KEY`.

---

## File-by-file — ops & tooling

| File | Role |
|---|---|
| `pyproject.toml` | Package metadata, runtime deps (FastAPI, LangGraph, LangChain…), ruff, pytest |
| `uv.lock` | Locked dependency graph — deploy/CI: `uv sync --frozen` |
| `.env.example` | Documented env vars (copy to `.env`) |
| `Dockerfile` | Multi-stage: uv sync → non-root `que` user → gunicorn via `start.sh` |
| `scripts/start.sh` | `gunicorn app.main:app` + `UvicornWorker`, `WEB_CONCURRENCY` workers |
| `.github/workflows/ci.yml` | gitleaks → `uv sync --frozen` → ruff → pip-audit → pytest |
| `.gitleaks.toml` | Secret-scan config |
| `AGENTS.md` | Short agent rules (separate from Quizzer, graph shape, knowledge rules) |
| `README.md` | Human quick start + integration sketch |

---

## Auth & config cheat sheet

| Concern | Mechanism |
|---|---|
| Quizzer user → Quizzer Backend | Cookie JWT |
| Quizzer Backend → mint Que token | `POST /que/session` + shared `QUE_JWT_SECRET` |
| Browser → QUE chat | `Authorization: Bearer <que_access>` + CORS origins |
| Server/ops → QUE | `X-Que-Service-Key` |
| Local docs without key | `ALLOW_INSECURE_LOCAL_NO_AUTH=true` + local env only |
| LLM | `LLM_API_KEY` + OpenAI-compatible `LLM_BASE_URL` |

---

## What is intentionally out of scope (for now)

- Quizzer DB / ORM imports
- Durable multi-worker conversation store (current MemorySaver is in-process / per worker)
- Embeddings / vector RAG
- Tools that read live exam/student numbers or mutate Quizzer
- Proxying chat/SSE through Quizzer Backend (avoided on purpose)

Those land later as new graph nodes / tools, without collapsing identity and knowledge into one blob.

---

## Mental model (one sentence)

**Quizzer proves the user once and mints a Que JWT; the browser streams chat straight to QUE; each turn runs LangGraph with short-term `dialog` memory (same `conversation_id`), injects persona + keyword knowledge, and asks the LLM for a plain-text answer.**
