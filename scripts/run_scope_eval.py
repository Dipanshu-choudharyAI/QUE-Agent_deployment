#!/usr/bin/env python3
"""Print Phase 1 scope/route accuracy from evals/scope_golden.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orchestration.understanding import classify_request  # noqa: E402


def main() -> int:
    cases = json.loads((ROOT / "evals" / "scope_golden.json").read_text(encoding="utf-8"))
    scope_hits = route_hits = 0
    print(f"{'ID':<10} {'SCOPE':<14} {'ROUTE':<16} RESULT")
    print("-" * 56)
    for case in cases:
        result = classify_request(case["question"])
        scope_ok = result.scope == case["expected_scope"]
        route_ok = result.route == case["expected_route"]
        scope_hits += int(scope_ok)
        route_hits += int(route_ok)
        flag = "OK" if scope_ok and route_ok else "MISS"
        print(
            f"{case['id']:<10} {result.scope:<14} {result.route:<16} {flag}"
            + ("" if flag == "OK" else f"  expected {case['expected_scope']}/{case['expected_route']}")
        )
    n = len(cases)
    scope_acc = scope_hits / n
    route_acc = route_hits / n
    print("-" * 56)
    print(f"cases={n}  scope_accuracy={scope_acc:.1%}  route_accuracy={route_acc:.1%}")
    return 0 if scope_acc >= 0.90 and route_acc >= 0.85 else 1


if __name__ == "__main__":
    raise SystemExit(main())
