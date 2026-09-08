# Phase 4 — Tools + Secure Execution + Insight Workflows

**Status:** Done (code shipped; kill switch defaults **off** in `.env.example`)  
**Goal:** Answer *live* Quizzer questions (“how many exams did I create?”, “who needs follow-up?”, “why can’t I publish?”) through a **fixed registry of read-only tools** — not ReAct, not raw SQL, not invented numbers.

---

## Problem this phase solved

RAG can teach *how* Analytics works. It cannot know *this user’s* exam count or *this exam’s* publish blockers.

Naive upgrades that we **rejected**:

| Approach | Why not |
|---|---|
| Let the LLM invent counts | Hallucination; trust-breaking |
| OpenAI function-calling free-for-all | Hard to audit; unpredictable tool chains |
| Give QUE the Quizzer DB | Destroys microservice boundary |
| One giant “run any query” tool | Unlimited blast radius |

**Upgrade story:** deterministic **insight workflows** — select at most one tool from query + UI context → Quizzer internal HTTP → labeled `TOOL_RESULT` → LLM coaches from facts only.

---

## What we built

### Contracts first

[`docs/TOOL_CONTRACTS_V1.md`](../TOOL_CONTRACTS_V1.md) freezes:

- Transport, envelope, error codes
- Tool list + required args
- SLOs (selection accuracy ≥ 85%, hard timeout, kill switch)
- Threat notes (UI context ≠ authZ; tool JSON untrusted)

### Quizzer internal API

`POST /internal/que/v1/tools/invoke`  
`GET  /internal/que/v1/tools/health`

Auth headers:

- `X-Que-Service-Key`
- `X-Que-User-Id` (acting user)
- `X-Request-Id` (correlation)

Handlers re-check **quiz ownership** (`created_by == user`). Browser never calls this route.

### QUE tool platform

| Module | Job |
|---|---|
| `app/tools/registry.py` | Typed tool specs + coaching hints |
| `app/tools/select.py` | Deterministic keyword + page selector |
| `app/tools/select.py` → `select_tool_prefer_raw` | Prefer latest user wording over glued follow-ups |
| `app/tools/executor.py` | Timeout, MAX_TOOL_CALLS, circuit breaker, kill switch |
| `app/tools/quizzer_client.py` | HTTP to Quizzer invoke |
| `app/orchestration/agent_status.py` | User-visible status labels for SSE |

### Graph topology

```text
prepare → context → tools | knowledge → generate
```

Routing after context (`app/graphs/que_graph.py`):

- Tools if `QUE_TOOLS_ENABLED` and (route/data_need says tool **or** selector matches)
- Else knowledge RAG

`tools_node` injects a system block labeled **`TOOL_RESULT`** (or clarify / soft error).

### Streaming UX (production-feel)

SSE event types:

1. `meta`
2. `status` — e.g. “Counting exams in your account…”, “Searching Quizzer guides…”
3. `token*`
4. `done` / `error`

Quizzer UI (`QueChatWidget`) shows a short checklist instead of only “Thinking…”.

### Kill switch / config

| Env | Role |
|---|---|
| `QUE_TOOLS_ENABLED` | Master switch (default **false** in example) |
| `QUIZZER_INTERNAL_BASE_URL` | e.g. `http://127.0.0.1:8000` |
| `QUE_TOOL_TIMEOUT_SECONDS` | Hard timeout (≈3s) |
| `QUE_TOOL_MAX_CALLS` | Cap per turn (≈2) |
| Circuit failure/TTL settings | Open circuit after repeated upstream failures |

When tools are off or Quizzer is down: honest “not available yet” — **no invented counts**.

### Tool inventory (17)

Original insight set (14) plus:

- **`summarize_my_exams`** — account-level exam counts (published / draft / archived / arena packs)
- **`lookup_my_exam`** — resolve a named exam by title when the user is not on that exam (no UUID)

Others include: exam status, blueprint, publish blockers, results summary, student coaching, empty analytics, live health, arena weak questions, resume creation, integrity helpers, etc. Full table in `TOOL_CONTRACTS_V1.md`.

### Evals

- `evals/tool_cases.json` + `scripts/run_tool_eval.py` — selection accuracy (18/18 after named-exam lookup)
- `tests/test_tool_select.py`, `tests/test_agent_status.py`
- Quizzer: `backend/tests/test_que_internal_tools.py` (auth reject / health)

---

## How a live-data turn works

```text
User: "How many exams are made by me?"
  + UI context { page: exams_list, role: teacher }

decide_turn → route tool / live_tool (or selector still matches)
stream:
  status: Reading your question…
  status: Counting exams in your account…
  QUE → Quizzer POST /internal/que/v1/tools/invoke
         tool=summarize_my_exams, X-Que-User-Id=<user>
  TOOL_RESULT { exam_count, published_count, ... }
  status: Writing answer…
  tokens: "You have 3 exams (1 published, 2 drafts)…"
```

Selector prefers **raw** user text so a previous “coaching” turn doesn’t pollute tool choice.

---

## Key files

### QUE

| File | Role |
|---|---|
| `docs/TOOL_CONTRACTS_V1.md` | Frozen contracts |
| `app/tools/registry.py` | Tool specs |
| `app/tools/select.py` | Deterministic selection |
| `app/tools/executor.py` | Safe execution |
| `app/tools/quizzer_client.py` | Upstream HTTP |
| `app/orchestration/agent_status.py` | Status copy |
| `app/orchestration/pipeline.py` | `stream_turn_events`, tool/knowledge prepare |
| `app/services/chat_service.py` | SSE framing (meta/status/token/done) |
| `app/graphs/que_graph.py` | Conditional tools\|knowledge |
| `app/graphs/nodes.py` → `tools_node` | Run tool + inject TOOL_RESULT |
| `app/identity/persona.py` | Phase `4-tools`, grounding rules |
| `evals/tool_cases.json` | Golden selection cases |
| `scripts/run_tool_eval.py` | Accuracy runner |

### Quizzer

| File | Role |
|---|---|
| `backend/api/que_internal_tools.py` | Invoke + handlers + ownership |
| `backend/main.py` | Mounts internal tools router |
| `backend/tests/test_que_internal_tools.py` | Auth tests |
| `frontend/src/features/que/QueChatWidget.tsx` | Status checklist UI + insight chips |
| `frontend/src/lib/api/que.ts` | `status` SSE event type |

---

## Important improvements / hardening after first ship

1. **Publish vs page-default priority** in the selector (publish blockers win over “exam workspace → status”).
2. **`summarize_my_exams`** for account inventory asks.
3. **Follow-up resolve fix** — “How many…” is a new topic, not glued to prior coaching.
4. **`select_tool_prefer_raw`** — tool choice uses the latest user sentence first.
5. **Live status SSE** — users see real work (tool / RAG / write), not a fake spinner only.

---

## Interview talking points

- “Why deterministic selection instead of ReAct?” → Known workflows; auditable; one tool per turn; cheaper; easier SLO on selection accuracy.
- “How do you stop data leaks?” → Service key never in browser; every tool checks ownership; UI context is not authZ.
- “How do you stop number hallucination?” → Tools only when enabled; TOOL_RESULT grounding; otherwise honest unavailable.
- “What’s the kill switch?” → `QUE_TOOLS_ENABLED=false` returns to knowledge-only instantly.
- “Workflow vs agent?” → Single tool + LLM summarize is a workflow; multi-step agent loops wait until Phase 7 evidence.

---

## What we deliberately did *not* do yet (Phase 5+)

- Capability / policy engine (role → allowed tools) beyond ownership
- Write / mutate tools (publish, notify, delete)
- Unlimited tool chaining / planning loops
- Hybrid retrieval + rerank (Phase 6)

---

## How to enable & verify locally

```bash
# QUE .env
QUE_TOOLS_ENABLED=true
QUIZZER_INTERNAL_BASE_URL=http://127.0.0.1:8000
QUE_SERVICE_KEY=<same as Quizzer>

uv run python scripts/run_tool_eval.py
uv run pytest tests/test_tool_select.py -q
```

Manual: New chat → “How many exams are made by me?” → status “Counting exams…” → real counts.
