# Phase 7 — Agent Runtime (bounded multi-tool loop)

**Status:** Done  
**Goal:** Make workflow-vs-agent an **explicit** routing decision, and bound the loop when a turn actually needs more than one insight tool.

---

## Problem this phase solved

Phase 4 is a **workflow**: pick one tool → Quizzer HTTP → `TOOL_RESULT` → generate. That is correct for “how many exams did I create?”

It fails when the next tool depends on the ask having **two live intents**:

> Compare how many exams I created **and** how this exam went.

Without a loop, QUE either answers from one tool or invents the other half. A free-form ReAct planner would also work — and would burn tokens on every “how many” ask.

**Upgrade story:** keep deterministic selection + Phase 5 policy. Add a **bounded loop** only when request understanding says `multi_step` (or a multi-intent pattern) **and** a permitted tool exists.

---

## What we built

```text
Request Understanding
        │
        ▼
runtime_mode: knowledge | workflow | agent
        │
   ┌────┴────┐
   ▼         ▼
workflow   agent loop (exclude used tools)
(1 call)   MAX_STEPS / MAX_CALLS / time / chars
   │         │
   └────┬────┘
        ▼
     generate  (+ AGENT_PARTIAL if a budget stopped the loop)
```

| Piece | Location |
|---|---|
| Mode decision | [`app/orchestration/runtime_mode.py`](../../app/orchestration/runtime_mode.py) |
| Bounded loop | [`app/orchestration/agent_loop.py`](../../app/orchestration/agent_loop.py) |
| Graph node | `agent_node` in [`app/graphs/nodes.py`](../../app/graphs/nodes.py) |
| Route after context | [`app/graphs/que_graph.py`](../../app/graphs/que_graph.py) |
| Selector skip | `exclude_tools` on [`app/tools/select.py`](../../app/tools/select.py) |
| Single invoke | `invoke_tool_selection` in [`app/tools/executor.py`](../../app/tools/executor.py) |

**No LLM planner.** Each iteration: `select_tool_prefer_raw(..., exclude_tools=used)` → policy → one Quizzer call → stop or continue.

### When agent vs workflow

| Mode | Rule |
|---|---|
| `knowledge` | Tools off, no live need, or policy deny |
| `workflow` | Live/insight + **one** clear tool (majority of traffic) |
| `agent` | Tools on + live need + (`complexity=multi_step` **or** compare / “and” joining two data asks) + a permitted tool |

Default remains **workflow**.

### Budgets (enforced)

| Env | Default |
|---|---|
| `QUE_TOOL_MAX_CALLS` | 2 |
| `QUE_AGENT_MAX_STEPS` | 3 |
| `QUE_AGENT_MAX_EXECUTION_MS` | 8000 |
| `QUE_AGENT_MAX_TOOL_CHARS` | 12000 |

Termination: `converged` | `step_limit` | `call_limit` | `timeout` | `token_budget` | `clarify` | `error`.

On budget stop with ≥1 successful `TOOL_RESULT`, generate still runs with an `AGENT_PARTIAL` system note. The loop never hangs.

SSE: each iteration emits `status` `tool` / `tool_done` with a `step` index.

---

## Measured outcome

| Gate | Result |
|---|---|
| Runtime-mode eval (`evals/agent_cases.json`) | **7/7** |
| Tool selection (must not regress) | **19/19** |
| Unit | `tests/test_agent_loop.py` — workflow, agent, step-limit, call-limit, student never invokes |

Deliberate loop fixture: `QUE_AGENT_MAX_STEPS=1` on a two-intent ask → `step_limit` + partial note + generate path.

---

## Interview talking points

- “What decides workflow vs agent?” → Explicit `runtime_mode` from understanding + selector, logged, not a default everything routes through.
- “What happens at the step limit?” → Stop, keep results so far, inject `AGENT_PARTIAL`, generate a partial answer. Never hang.
- “Why not ReAct?” → Known V1 tools; policy already fail-closed; one extra LLM round per step is cost without evidence.

---

## What we deliberately did *not* do

- LLM planning / reflection loops
- Cross-session memory beyond MemorySaver dialog
- Multi-agent coordination (Phase 17)
- Write tools

---

## How to verify

```bash
uv run pytest tests/test_agent_loop.py tests/test_tool_select.py tests/test_policy.py -q
uv run python scripts/run_agent_eval.py
# Manual: QUE_TOOLS_ENABLED=true → “How many exams did I make and how did this exam go?”
# → two status events, then a combined answer
```
