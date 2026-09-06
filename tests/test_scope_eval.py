"""Golden scope eval — Phase 1 handbook metric: scope accuracy.

Run: uv run pytest tests/test_scope_eval.py -q
Or:  uv run python scripts/run_scope_eval.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.orchestration.understanding import classify_request

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "evals" / "scope_golden.json"
MIN_SCOPE_ACCURACY = 0.90
MIN_ROUTE_ACCURACY = 0.85


def _load_cases() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_golden_file_has_enough_cases():
    cases = _load_cases()
    assert len(cases) >= 20
    scopes = {c["expected_scope"] for c in cases}
    assert "in_scope" in scopes
    assert "out_of_scope" in scopes


def test_scope_accuracy_meets_threshold():
    cases = _load_cases()
    scope_hits = 0
    route_hits = 0
    misses: list[str] = []

    for case in cases:
        result = classify_request(case["question"])
        scope_ok = result.scope == case["expected_scope"]
        route_ok = result.route == case["expected_route"]
        if scope_ok:
            scope_hits += 1
        if route_ok:
            route_hits += 1
        if not scope_ok or not route_ok:
            misses.append(
                f"{case['id']}: got scope={result.scope} route={result.route} "
                f"expected scope={case['expected_scope']} route={case['expected_route']}"
            )

    n = len(cases)
    scope_acc = scope_hits / n
    route_acc = route_hits / n
    assert scope_acc >= MIN_SCOPE_ACCURACY, (
        f"scope_accuracy={scope_acc:.3f} below {MIN_SCOPE_ACCURACY}; misses:\n"
        + "\n".join(misses)
    )
    assert route_acc >= MIN_ROUTE_ACCURACY, (
        f"route_accuracy={route_acc:.3f} below {MIN_ROUTE_ACCURACY}; misses:\n"
        + "\n".join(misses)
    )


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["id"])
def test_each_golden_case_scope(case: dict):
    result = classify_request(case["question"])
    assert result.scope == case["expected_scope"]
