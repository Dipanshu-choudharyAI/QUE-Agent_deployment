"""Phase 11 unified suite + baseline differ."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from app.evals.groundedness import is_grounded
from app.evals.suite import (
    CategoryScore,
    compare_to_baseline,
    score_groundedness,
    score_guardrail_fp,
    score_injection,
    score_tools,
)

ROOT = Path(__file__).resolve().parents[1]


def test_groundedness_heuristic_matches_fixtures():
    cases = json.loads((ROOT / "evals" / "groundedness_cases.json").read_text(encoding="utf-8"))[
        "cases"
    ]
    for case in cases:
        got = is_grounded(
            case["candidate_answer"],
            case["context"],
            context_kind=case["context_kind"],
        )
        assert got is case["expect_grounded"], case["id"]


def test_injection_and_fp_categories_are_perfect():
    inj = score_injection(1.0)
    fp = score_guardrail_fp(1.0)
    assert inj.passed, inj.misses
    assert fp.passed, fp.misses
    g = score_groundedness(1.0)
    assert g.passed, g.misses


def test_baseline_differ_fails_when_expected_tool_dropped():
    real = score_tools(0.85)
    dropped = CategoryScore(
        id="tools",
        metric=real.metric,
        score=(real.hits - 1) / real.n,
        hits=real.hits - 1,
        n=real.n,
        threshold=real.threshold,
        misses=["deliberate drop of one expected_tool"],
    )
    baseline = {
        "categories": {
            "tools": {"score": real.score, "hits": real.hits, "n": real.n},
        }
    }
    problems = compare_to_baseline([dropped], baseline)
    assert problems, "suite differ must fail when a tool golden is dropped"

    ok = compare_to_baseline([real], baseline)
    assert ok == []


def test_online_logger_hashes_and_omits_raw_query(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.evals.online import maybe_log_online_turn

    path = tmp_path / "online.jsonl"
    monkeypatch.setenv("QUE_EVAL_ONLINE_SAMPLE", "true")
    monkeypatch.setenv("QUE_EVAL_ONLINE_RATE", "1.0")
    monkeypatch.setenv("QUE_EVAL_ONLINE_PATH", str(path))
    get_settings.cache_clear()
    try:
        maybe_log_online_turn(
            request_id="abc123",
            user_id="user-secret",
            query="How do I create a quiz? alice@school.edu",
            route="knowledge",
            freshness="static",
            guardrail=None,
        )
    finally:
        get_settings.cache_clear()
    raw = path.read_text(encoding="utf-8")
    assert "user-secret" not in raw
    assert "alice@school.edu" not in raw
    row = json.loads(raw.strip())
    assert row["user_hash"]
    assert row["query_hash"]
    assert row["query_looks_pii"] is True
    assert "query" not in row
    assert "user_id" not in row


def test_catalog_points_at_existing_files():
    catalog = json.loads((ROOT / "evals" / "catalog.json").read_text(encoding="utf-8"))
    for entry in catalog["categories"]:
        path = ROOT / entry["path"]
        assert path.is_file(), entry["path"]


def test_compare_to_baseline_uses_copy_not_mutation():
    baseline = {"categories": {"tools": {"score": 1.0, "hits": 1, "n": 1}}}
    snapshot = copy.deepcopy(baseline)
    compare_to_baseline(
        [
            CategoryScore(
                id="tools",
                metric="selection_accuracy",
                score=1.0,
                hits=1,
                n=1,
                threshold=0.85,
            )
        ],
        baseline,
    )
    assert baseline == snapshot
