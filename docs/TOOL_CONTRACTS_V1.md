# QUE Tool Contracts V1

Versioned internal tool surface for Phase 4 insight workflows.

## Transport (QUE → Quizzer)

- Base: `{QUIZZER_INTERNAL_BASE_URL}/internal/que/v1/tools`
- `POST /invoke` body: `{ "tool": "<name>", "args": { ... }, "idempotency_key": "<optional, write tools>" }`
- Headers:
  - `X-Que-Service-Key` (required)
  - `X-Que-User-Id` (required, acting user)
  - `X-Request-Id` (correlation)
  - `X-Idempotency-Key` (write tools only — mirrors the body field)

## Envelope

```json
{
  "api_version": "1",
  "tool": "summarize_exam_results",
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "request_id": "...",
    "user_id": "...",
    "latency_ms": 12,
    "freshness": "live"
  }
}
```

Error codes: `unauthorized` (401), `forbidden` (403), `not_found` (404),
`invalid_argument` (422), `rate_limited` (429), `unavailable` (503),
`upstream_timeout` (504).

## Tools (17) — all risk_tier=read

| tool | requires exam_id | purpose |
|---|---|---|
| explain_exam_status | yes | Status narrative + next step |
| summarize_exam_blueprint | yes | Question mix / balance |
| recommend_exam_improvements | yes | Ranked improvement actions |
| diagnose_publish_blockers | yes | Why publish fails |
| recommend_integrity_settings | yes | Integrity settings gaps |
| summarize_exam_results | yes | Cohort results story |
| coach_students_needing_help | yes | Who to follow up |
| explain_integrity_attempt | yes + attempt_id | One attempt integrity story |
| recommend_post_exam_actions | yes | After-results actions |
| summarize_live_exam_health | optional | Live sits health |
| diagnose_empty_analytics | no | Why analytics empty |
| prioritize_student_coaching | no | Students needing coaching |
| analyze_arena_weak_questions | yes | Arena weak items |
| resume_creation_guidance | optional | Resume create wizard |
| summarize_my_exams | no | Count exams this user created |
| summarize_dashboard_metrics | no | Dashboard KPI cards (active now, attempts 7d, avg score, AI jobs) |
| lookup_my_exam | no (title) | Find an owned exam by title and return status |

## Write tools (3, Phase 14) — all risk_tier=write, requires_confirmation=true

These are only ever called by QUE after the end user replied "yes" to an
explicit confirmation question in chat (see
[`phases/phase-14-write-tools-and-readiness.md`](phases/phase-14-write-tools-and-readiness.md)).
Quizzer re-validates ownership/role/current-state on every call regardless —
QUE's confirmation is a UX gate, not the authorization boundary.

| tool | requires exam_id | purpose | notes |
|---|---|---|---|
| publish_exam | yes | Publish a draft exam | No-ops (`already_published: true`) if already published; refuses if archived or has unapproved questions |
| notify_students | yes | Email a reminder to enrolled students | Requires the exam to already be published and a linked Google Classroom roster; otherwise `invalid_argument: no student roster is linked` |
| delete_draft_exam | yes | Hard-delete an empty draft | Refuses if published, archived, or has any attempt history — narrower than the UI's `DELETE /quizzes/{id}` (which can soft-delete published/attempted exams) |

Write-tool `idempotency_key`s are deduped server-side for 10 minutes — a
retried HTTP call (client retry, proxy timeout) replays the first result
instead of executing twice.

## Policy (Phase 5)

Role → tool allow/deny is defined in [`CAPABILITY_MATRIX_V1.md`](CAPABILITY_MATRIX_V1.md).

- QUE: `app/policy/` filters selection + executor (fail closed).
- Quizzer: re-validates `User.role` on every invoke (DB), independent of UI context.
- Model tool choice is never a grant. Missing/unknown role → `forbidden`.
- All V1 (read) tools: `risk_tier=read`, `requires_confirmation=false`.
- Write tools: `risk_tier=write`, `requires_confirmation=true` — QUE never
  calls Quizzer for these until a human "yes" (see write-tools section
  above). Never reachable from the bounded agent loop — one mutation per
  confirmed turn only.

## SLOs

- Selection accuracy ≥ 85% on golden set
- Arg accuracy ≥ 95% when id in context/text
- Invented numbers on tool path = 0
- Hard timeout 3s; MAX_TOOL_CALLS=2
- Kill switch: `QUE_TOOLS_ENABLED=false`
- Permission: student (or empty role) blocked on teacher tools = 100% on adversarial set

## Threat notes

UI context is not authorization. Quizzer re-checks quiz ownership **and** role on every call.
Tool JSON is untrusted data for the LLM (labeled TOOL_RESULT).
