#!/usr/bin/env python3
"""Print P50/P95/P99 latency from optional QUE obs JSONL.

  uv run python scripts/summarize_obs.py
  uv run python scripts/summarize_obs.py --path data/obs.jsonl

Never expects raw query text or emails in the file.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    idx = min(len(ordered) - 1, max(0, int((p / 100.0) * (len(ordered) - 1))))
    return round(ordered[idx], 2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize QUE observability JSONL")
    parser.add_argument(
        "--path",
        default="",
        help="JSONL path (default: QUE_OBS_JSONL)",
    )
    args = parser.parse_args(argv)

    raw = (args.path or os.environ.get("QUE_OBS_JSONL") or "").strip()
    if not raw:
        print("no file: set QUE_OBS_JSONL or pass --path")
        return 1
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        print(f"no file: {path}")
        return 1

    lat: list[float] = []
    by_span: dict[str, list[float]] = defaultdict(list)
    errors = 0
    usd: list[float] = []
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "query" in row or "user_id" in row or "email" in row:
            print("refusing to summarize: raw query, user_id, or email field present")
            return 1
        n += 1
        lat.append(float(row.get("latency_ms") or 0))
        if row.get("error"):
            errors += 1
        if row.get("cost_usd") is not None:
            usd.append(float(row["cost_usd"]))
        for span in row.get("spans") or []:
            name = str(span.get("name") or "unknown")
            by_span[name].append(float(span.get("ms") or 0))

    print(
        f"n={n} errors={errors} "
        f"p50={_percentile(lat, 50)} p95={_percentile(lat, 95)} p99={_percentile(lat, 99)}"
    )
    if usd:
        success_n = n - errors
        mean = round(sum(usd) / max(1, success_n), 8) if success_n else 0.0
        print(f"cost_usd_total={round(sum(usd), 6)} cost_per_successful_task={mean}")
    for name in sorted(by_span):
        vals = by_span[name]
        print(
            f"  span {name}: p50={_percentile(vals, 50)} "
            f"p95={_percentile(vals, 95)} p99={_percentile(vals, 99)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
