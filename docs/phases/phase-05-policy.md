# Phase 5 — Identity + Permissions + Capabilities + Policy

**Status:** Done  
**Goal:** Enforce who may call which insight tool — fail closed — with defense in depth. Model tool choice is never a grant.

---

## Problem this phase solved

Phase 4 tools worked for teachers, but:

- `ToolSpec.roles` existed and was **never checked**
- Quizzer invoke checked ownership, **not** `User.role`
- A student (or empty role) could still hit teacher tools if the selector matched

**Upgrade story:** separate **policy** from ownership. Auth answers who you are; ownership answers which exam; policy answers whether this role may call this tool *now*.

---

## What we built

### QUE `app/policy/`

| Module | Role |
|---|---|
| `roles.py` | `normalize_role` → student \| teacher \| admin \| None |
| `capabilities.py` | Role ↔ tool allow from `ToolSpec.roles` (admin inherits teacher) |
| `engine.py` | `evaluate_tool_call` → `PolicyDecision(allow, reason, requires_confirmation)` |

Fail closed: missing/unknown role → deny. Read tools → `requires_confirmation=false` (seat for future writes).

### Wiring

- **Selector** — if `ui_context.user_role` is set and not allowed → `policy_denied` + safe clarify (no tool name leak)
- **Executor** — always evaluates policy before HTTP; `TOOL_ERROR` / `forbidden`
- **Graph routing** — policy-denied selections go to **knowledge**, not tools

### Quizzer re-validation

`Quizzer/backend/api/que_internal_tools.py`:

- `TOOL_ALLOWED_ROLES` mirrors QUE (teacher/admin for all V1 tools)
- After service-key user load, before handler: role check → `403` + envelope
- Logs `que_internal_tool_forbidden_role`
- Still does **not** trust any role header — only DB `User.role`

### Docs / evals

- [`docs/CAPABILITY_MATRIX_V1.md`](../CAPABILITY_MATRIX_V1.md)
- Policy section in [`TOOL_CONTRACTS_V1.md`](../TOOL_CONTRACTS_V1.md)
- `evals/permission_cases.json` + `scripts/run_permission_eval.py`
- Tests: `tests/test_policy.py`, Quizzer student-deny / teacher-allow

---

## How a denied turn works

```text
Student asks "How many exams did I make?"
  → select matches summarize_my_exams
  → policy: role_not_permitted
  → route knowledge (or TOOL_ERROR if executor)
  → no Quizzer invoke / no live counts
```

Teacher path unchanged: select → allow → Quizzer ownership + role → TOOL_RESULT.

---

## Interview talking points

- Auth vs authZ vs policy — three questions, three places.
- Why model choice isn’t a grant — prompt is suggestion; registry filter + executor + Quizzer DB role are grants.
- Why UI context isn’t authZ — stamped for UX; Quizzer re-checks DB role.
- Confirmation seat — ready for write tools without scattering if-statements.

---

## What we deliberately did *not* do

- Write / mutate tools
- Full multi-tenant RBAC framework
- Student-safe live tools (none in V1 matrix)

---

## How to verify

```bash
uv run pytest tests/test_policy.py tests/test_tool_select.py -q
uv run python scripts/run_permission_eval.py
# Quizzer
pytest backend/tests/test_que_internal_tools.py -q
```
