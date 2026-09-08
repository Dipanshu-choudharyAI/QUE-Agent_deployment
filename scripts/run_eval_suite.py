#!/usr/bin/env python3
"""Unified offline eval suite (Phase 11).

  uv run python scripts/run_eval_suite.py --offline
  uv run python scripts/run_eval_suite.py --offline --fail-on-regression
  uv run python scripts/run_eval_suite.py --offline --write-baseline
  uv run python scripts/run_eval_suite.py --with-retrieval-dense
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.evals.suite import (  # noqa: E402
    BASELINE_PATH,
    CategoryScore,
    baseline_payload,
    compare_to_baseline,
    load_baseline,
    load_catalog,
    run_offline_suite,
)


def _print_scores(scores: list[CategoryScore]) -> None:
    print(f"{'CATEGORY':<18} {'METRIC':<28} {'SCORE':>8}  HITS  THRESH  PASS")
    print("-" * 78)
    for s in scores:
        flag = "OK" if s.passed else "FAIL"
        print(
            f"{s.id:<18} {s.metric:<28} {s.score:8.4f}  {s.hits:>3}/{s.n:<3} "
            f"{s.threshold:6.2f}  {flag}"
        )
        for miss in s.misses[:8]:
            print(f"    miss {miss}")
    print("-" * 78)
    print("Per-category scores only — no blended accuracy.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QUE unified eval suite")
    parser.add_argument("--offline", action="store_true", help="CI default: no embedding API")
    parser.add_argument(
        "--with-retrieval-dense",
        action="store_true",
        help="Also score dense retrieval (needs index + embeddings)",
    )
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    logging.getLogger().setLevel(logging.WARNING)
    try:
        import structlog

        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    except Exception:  # noqa: BLE001
        pass

    scores = run_offline_suite(with_retrieval_dense=args.with_retrieval_dense)
    _print_scores(scores)

    catalog = load_catalog()
    thresholds = {
        str(c["id"]): float(c.get("threshold") or 0.0) for c in catalog.get("categories") or []
    }

    if args.write_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = baseline_payload(scores, thresholds=thresholds)
        BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {BASELINE_PATH}")

    failed_threshold = [s.id for s in scores if not s.passed]
    regressions: list[str] = []
    if args.fail_on_regression:
        regressions = compare_to_baseline(scores, load_baseline())

    if args.json:
        print(json.dumps({"categories": [s.as_dict() for s in scores]}, indent=2))

    if failed_threshold:
        print(f"below threshold: {', '.join(failed_threshold)}")
        return 1
    if regressions:
        print("regression vs baseline:")
        for row in regressions:
            print(f"  {row}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
