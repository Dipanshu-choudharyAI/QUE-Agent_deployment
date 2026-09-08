# Phase 3 — Context Engineering (UI context)

**Status:** Done  
**Goal:** Every chat turn knows *where the user is* in Quizzer (page, exam id, role) as a structured hint — so the assistant doesn’t ask “which exam?” when the UI already knows.

---

## Problem this phase solved

After RAG, QUE could explain *how* Quizzer works, but still failed common in-product asks:

- “How did this exam go?” while the user is already on Results
- “Why can’t I publish?” while sitting in the exam workspace
- Role confusion (student vs teacher wording) when the client lied or omitted role

Sending free-text like “user is on /quizzes/abc/results” concatenated into the user message is brittle and prompt-injection friendly.

**Upgrade story:** structured **`QueUiContext`** end-to-end, stamped by the server, injected as a labeled system block with clear precedence rules.

---

## What we built

### Contract: `QueUiContext`

Fields (conceptually):

- `current_page` — e.g. `exam_workspace`, `exam_results`, `analytics`, `exams_list`
- `current_exam_id` / entity type + id
- `user_role` — **server-stamped**, not trusted from the browser alone
- `route_path`, `captured_at`

Present on:

- QUE `ChatRequest.context`
- Quizzer `QueChatRequest.context`

### Frontend

`frontend/src/features/que/buildQueUiContext.ts` maps Next.js pathname → page key + ids.  
`QueChatWidget` attaches `context` on every SSE send.

### Quizzer BFF

`backend/api/que.py` → `_upstream_payload`:

- Sets `user_id` from authenticated User
- **Overwrites** `context.user_role` from the real User (client role is a hint only)

### QUE graph node

`context_node` inserts a labeled `SystemMessage`:

```text
QUIZZER_UI_CONTEXT
{ ...json... }
```

Never concatenated into the user turn text.

### Precedence (documented + prompted)

Highest first:

1. Explicit user wording (named exam / ids in the message)
2. Conversational resolve (`resolved_query`)
3. Structured UI context
4. Retrieved knowledge / tools

**Important:** UI context is a **UX hint**, not authorization. Authorization for live data happens later in Quizzer tool handlers (ownership checks).

### Graph topology after Phase 3

```text
prepare → context → knowledge → generate
```

(Phase 4 adds the tools branch after context.)

---

## Key files

### QUE

| File | Role |
|---|---|
| `app/schemas/chat.py` | `QueUiContext` + `ChatRequest.context` |
| `app/graphs/nodes.py` → `context_node` | Inject labeled UI JSON |
| `app/graphs/state.py` | `ui_context` on state |
| `app/orchestration/ui_context.py` | Helpers / live-data soft replies when tools off |
| `app/orchestration/pipeline.py` | Passes context into graph input |

### Quizzer

| File | Role |
|---|---|
| `frontend/src/features/que/buildQueUiContext.ts` | Path → context |
| `frontend/src/features/que/buildQueUiContext.test.ts` | Mapping tests |
| `frontend/src/features/que/QueChatWidget.tsx` | Attach context every stream |
| `frontend/src/lib/api/que.ts` | Types for context on requests |
| `backend/schemas/que.py` | BFF schema |
| `backend/api/que.py` | Stamp `user_id` + `user_role` |

---

## Important improvements

1. **Structured > stringly** — page enums / ids, not prose dumped into the user message.
2. **Server stamps role** — clients can’t spoof teacher capabilities via context alone.
3. **Labeled system block** — model sees a clear boundary (`QUIZZER_UI_CONTEXT`).
4. **Precedence rules** — user wording still wins when they name another exam.
5. **Sets up Phase 4** — tools read `current_exam_id` / page for arg extraction without a second round trip.

---

## Interview talking points

- “Is UI context authZ?” → No. It’s a hint. Tools re-check quiz ownership with `X-Que-User-Id`.
- “Why not put context in the user message?” → Injection risk + messier precedence; labeled system JSON is cleaner.
- “What if the user switches topic?” → Explicit wording and resolve beat UI context.

---

## What we deliberately did *not* do yet

- Using context to auto-call APIs (that’s Phase 4 tools)
- Multi-entity context graphs / long-term user memory of navigation

---

## How to verify

```bash
# Frontend unit
cd frontend && npx vitest run src/features/que/buildQueUiContext.test.ts
# Manual: open an exam → Ask QUE “explain this exam status” without pasting an id
```
