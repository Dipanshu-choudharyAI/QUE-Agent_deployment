#!/usr/bin/env python3
"""Summarize sampled online eval JSONL (Phase 11).

  uv run python scripts/summarize_online_eval.py
  uv run python scripts/summarize_online_eval.py --path data/eval_online.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize QUE online eval JSONL")
    parser.add_argument(
        "--path",
        default="",
        help="JSONL path (default: QUE_EVAL_ONLINE_PATH or data/eval_online.jsonl)",
    )
    args = parser.parse_args(argv)

    path = Path(args.path) if args.path else ROOT / "data" / "eval_online.jsonl"
    if not path.is_file():
        print(f"no file: {path}")
        return 1

    routes: Counter[str] = Counter()
    guardrails: Counter[str] = Counter()
    freshness: Counter[str] = Counter()
    cache_hits = 0
    n = 0
    pii_flags = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        n += 1
        routes[str(row.get("route") or "unknown")] += 1
        g = row.get("guardrail")
        guardrails[str(g) if g else "none"] += 1
        freshness[str(row.get("freshness") or "unknown")] += 1
        if row.get("cache_hit"):
            cache_hits += 1
        if row.get("query_looks_pii"):
            pii_flags += 1
        if "query" in row or "user_id" in row:
            print("refusing to summarize: raw query or user_id field present")
            return 1

    print(f"rows={n} cache_hits={cache_hits} query_looks_pii={pii_flags}")
    print("by route:")
    for key, count in routes.most_common():
        print(f"  {key}: {count}")
    print("by guardrail:")
    for key, count in guardrails.most_common():
        print(f"  {key}: {count}")
    print("by freshness:")
    for key, count in freshness.most_common():
        print(f"  {key}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
