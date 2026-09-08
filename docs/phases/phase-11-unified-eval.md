# Phase 11 — Unified Evaluation Platform

**Status:** Done  
**Goal:** One offline runner, per-category scores, a committed baseline, CI gate, and a sampled online JSONL — without LLM-as-judge and without merging every golden into one stale mega-file.

---

## Problem this phase solved

Each earlier phase had its own script (`run_scope_eval.py`, `run_retrieval_eval.py`, `run_tool_eval.py`, `run_permission_eval.py`, `run_agent_eval.py`). CI ran **pytest only**. A tool-selection miss could hide behind a stable blended number if we ever averaged them. Groundedness was not scored. There was no regression differ against a committed snapshot.

**Upgrade story:** keep the per-phase scripts as debug entry points. Add a **catalog** that points at those files, one suite runner, thresholds per category, and `--fail-on-regression`.

---

## What we built

```text
evals/catalog.json
        │
        ▼
scripts/run_eval_suite.py --offline
        ├─ scope
        ├─ retrieval (keyword, no API keys)
        ├─ tools
        ├─ permissions
        ├─ agent
        ├─ injection
        ├─ guardrail_fp
        └─ groundedness
                │
                ▼
evals/baselines/offline.json
        │
        ▼
CI: pytest then suite --fail-on-regression
```

| Piece | Location |
|---|---|
| Catalog | [`evals/catalog.json`](../../evals/catalog.json) |
| Runner | [`scripts/run_eval_suite.py`](../../scripts/run_eval_suite.py) |
| Scoring | [`app/evals/suite.py`](../../app/evals/suite.py) |
| Groundedness | [`app/evals/groundedness.py`](../../app/evals/groundedness.py) + [`evals/groundedness_cases.json`](../../evals/groundedness_cases.json) |
| Baseline | [`evals/baselines/offline.json`](../../evals/baselines/offline.json) |
| Online sample | [`app/evals/online.py`](../../app/evals/online.py) — hashed `user_id` / query only |
| Summarize | [`scripts/summarize_online_eval.py`](../../scripts/summarize_online_eval.py) |
| CI | `.github/workflows/ci.yml` after pytest |

`--with-retrieval-dense` is local-only (index + embeddings). Keyword retrieval **is** in the CI offline gate.

Checkpoint: `tests/test_eval_suite.py` drops one tool hit and asserts `compare_to_baseline` fails.

---

## Offline baseline (this drop)

| Category | Score | Hits | Threshold |
|---|---|---|---|
| scope | 1.0000 | 36/36 | 0.90 |
| retrieval (keyword recall@k) | 0.9412 | 31/34 perfect | 0.70 |
| tools | 1.0000 | 19/19 | 0.85 |
| permissions | 1.0000 | 5/5 | 1.00 |
| agent | 1.0000 | 7/7 | 0.85 |
| injection | 1.0000 | 14/14 | 1.00 |
| guardrail_fp | 1.0000 | 26/26 | 1.00 |
| groundedness | 1.0000 | 8/8 | 1.00 |

No blended accuracy is printed or gated.

Groundedness is a **heuristic**: token overlap plus “numbers in the answer must appear in `TOOL_RESULT`.” It is not a substitute for a labeled LLM judge.

---

## Online sample

Off by default (`QUE_EVAL_ONLINE_SAMPLE=false`). When on, a fraction of completed turns append one JSONL row: `request_id`, `route`, `freshness`, `cache_hit`, `cache_layer`, `guardrail`, hashed user, hashed query. Raw query text and `user_id` are never stored.

---

## Interview talking points

- “Why didn’t eval start here?” → Scope goldens shipped in Phase 1. This phase **unifies** them so one CI command sees a tool regression.
- “Offline vs online?” → Offline is the merge gate (deterministic, no keys). Online is a sampled operational log for later dashboards (Phase 12), not a judge.
- “How do you know CI would catch a drop?” → Unit test mutates tool hits downward; the baseline differ fails.

---

## What we deliberately did *not* do

- LLM-as-judge
- Copying every golden into one mega-JSON
- Dense retrieval as a CI hard gate
- Dashboards / cost budgets (Phase 12)
