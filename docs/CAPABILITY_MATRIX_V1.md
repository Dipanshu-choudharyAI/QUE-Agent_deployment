# Capability Matrix V1

Policy for QUE insight tools. **Authentication** answers who you are;
**authorization** (ownership) answers which exams you own; **policy** answers
whether this role may call this tool right now.

## Rules

- UI context `user_role` is a UX hint for early filtering — **not** a grant.
- The model’s tool choice is never authorization.
- Quizzer re-checks `User.role` from the DB on every `/internal/que/v1/tools/invoke`.
- Missing / unknown role → **deny** (fail closed).
- All V1 (read) tools are `risk_tier=read` → `requires_confirmation=false`.
- Write tools (Phase 14) are `risk_tier=write` → `requires_confirmation=true`.
  The confirmation is a chat-native human-in-the-loop yes/no turn (see
  [`phases/phase-14-write-tools-and-readiness.md`](phases/phase-14-write-tools-and-readiness.md)),
  not an API-level confirm flag — Quizzer still independently re-validates
  ownership/state on every write call.

## Roles

| Role | Meaning |
|---|---|
| `student` | Learner persona — no insight tools in V1 |
| `teacher` | Creator workspace — all insight tools |
| `admin` | Inherits teacher tool set |

## Matrix

| Tool | student | teacher | admin | risk_tier | requires_confirmation |
|---|---|---|---|---|---|
| explain_exam_status | deny | allow | allow | read | no |
| summarize_exam_blueprint | deny | allow | allow | read | no |
| recommend_exam_improvements | deny | allow | allow | read | no |
| diagnose_publish_blockers | deny | allow | allow | read | no |
| recommend_integrity_settings | deny | allow | allow | read | no |
| summarize_exam_results | deny | allow | allow | read | no |
| coach_students_needing_help | deny | allow | allow | read | no |
| explain_integrity_attempt | deny | allow | allow | read | no |
| recommend_post_exam_actions | deny | allow | allow | read | no |
| summarize_live_exam_health | deny | allow | allow | read | no |
| diagnose_empty_analytics | deny | allow | allow | read | no |
| prioritize_student_coaching | deny | allow | allow | read | no |
| analyze_arena_weak_questions | deny | allow | allow | read | no |
| resume_creation_guidance | deny | allow | allow | read | no |
| summarize_my_exams | deny | allow | allow | read | no |
| summarize_dashboard_metrics | deny | allow | allow | read | no |
| lookup_my_exam | deny | allow | allow | read | no |
| publish_exam | deny | allow | allow | write | **yes** |
| notify_students | deny | allow | allow | write | **yes** |
| delete_draft_exam | deny | allow | allow | write | **yes** |

## Defense in depth

1. QUE selector — skip forbidden tools when `user_role` is stamped
2. QUE executor — `evaluate_tool_call` before HTTP
3. Quizzer invoke — `_role_allowed_for_tool` on DB user + ownership on exams

See also: [`TOOL_CONTRACTS_V1.md`](TOOL_CONTRACTS_V1.md), [`phases/phase-05-policy.md`](phases/phase-05-policy.md).
