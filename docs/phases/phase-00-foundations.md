# Phase 0 — Foundations & Prerequisites

**Status:** Done  
**Goal:** Stand up QUE as its own deployable service with correct auth boundaries — before any “smart” agent behavior.

---

## Problem this phase solved

Quizzer already had a large FastAPI + Next.js product. Putting an LLM chat *inside* Quizzer’s request path (or giving the agent Quizzer DB access) would:

- Couple AI latency to the main API
- Mix creator-workspace auth with agent credentials
- Make it hard to scale / kill / rewrite the assistant independently

**Upgrade story:** split QUE into a **microservice** with its own process, config, and credentials.

---

## What we built

### Separate service

| Concern | Choice |
|---|---|
| Runtime | FastAPI + Uvicorn, Python 3.11, `uv` |
| Port (local) | `:8100` (Quizzer API stays `:8000`) |
| Package layout | `app/` application code; no Quizzer imports |
| Config | `pydantic-settings` from `.env` (`app/core/config.py`) |
| Deploy story | Own Docker image; `knowledge/` copied in later phases |

### Auth model (two credentials)

1. **Browser path (intended end state):** Quizzer mints short-lived `que_access` JWT → browser calls QUE with `Authorization: Bearer …`
2. **Service path (ops + current BFF):** `X-Que-Service-Key` shared secret — **never** shipped to the browser

Shared mint secret: `QUE_JWT_SECRET` on both Quizzer and QUE.

### Chat HTTP surface

- `GET /health`
- `GET /v1/identity`
- `POST /v1/chat`
- `POST /v1/chat/stream` (SSE)

---

## How the system works (Phase 0 view)

```text
Quizzer UI  --cookie JWT-->  Quizzer Backend
                                 |
                                 |  POST /que/session  (mint)  OR  BFF proxy with service key
                                 v
                            QUE-Agent :8100
                                 |
                                 v
                               LLM API
```

Hard rules from day one:

- QUE does **not** talk to Quizzer’s database
- QUE does **not** import Quizzer Python packages
- Service key stays server-side only

---

## Key files (QUE)

| File | Role |
|---|---|
| `app/main.py` | FastAPI app factory, CORS, routers, startup checks |
| `app/run.py` | Local uvicorn entry |
| `app/core/config.py` | Env settings + production guards (weak secrets, insecure auth) |
| `app/core/security.py` | `require_chat_auth` — Bearer JWT **or** service key |
| `app/core/tokens.py` | Decode/verify Quizzer-minted Que access JWT |
| `app/core/llm.py` | Single gateway to LangChain `ChatOpenAI` |
| `app/core/errors.py` | Public error codes (no provider stack traces) |
| `app/api/health.py` | Liveness |
| `app/api/chat.py` | Chat + stream endpoints |
| `app/schemas/chat.py` | Request/response contracts |
| `app/services/chat_service.py` | HTTP ↔ orchestration bridge (grew in later phases) |
| `.env.example` | Documented env vars |
| `AGENTS.md` / `ARCHITECTURE.md` | Agent + human architecture notes |

### Quizzer side (session mint / BFF)

| File | Role |
|---|---|
| `backend/api/que.py` | `/que/session`, `/que/chat`, `/que/chat/stream` BFF |
| `backend/services/que_client.py` | HTTP client Quizzer → QUE |
| `backend/core/security.py` (Que mint helpers) | Creates Que access tokens |

---

## Important improvements / decisions

1. **Microservice first** — identity of the assistant is not tangled with Quizzer’s monolith.
2. **Two credentials by design** — browser never sees the service key.
3. **Fail closed in prod** — `ALLOW_INSECURE_LOCAL_NO_AUTH` refused outside local.
4. **One LLM module** — every model call goes through `app/core/llm.py` (easy to swap gateway later).

---

## Interview talking points

- “Why not embed the agent in Quizzer?” → blast radius, scaling, ownership of latency, cleaner auth.
- “How does auth work?” → Quizzer proves the user once; QUE verifies a short-lived token *or* accepts a server service key from the BFF.
- “What’s the trust boundary?” → QUE never gets DB credentials; at most it later calls Quizzer *internal* APIs with a service key + acting user id.

---

## What we deliberately did *not* do yet

- RAG / knowledge packs
- Tools
- Multi-agent loops
- Durable cross-replica conversation DB (MemorySaver came later, still in-process)

---

## How to verify

```bash
# QUE
uv run python -m app.run
curl http://127.0.0.1:8100/health
```

Expect JSON `status: ok`.
