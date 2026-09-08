#!/usr/bin/env python3
"""Score Phase 2/6 retrieval eval (precision / recall@K).

Usage:
  # Keyword baseline (no index required):
  uv run python scripts/run_retrieval_eval.py --mode keyword

  # Dense (requires built index):
  uv run python -m app.knowledge
  uv run python scripts/run_retrieval_eval.py --mode dense

  # Hybrid BM25 + dense RRF:
  uv run python scripts/run_retrieval_eval.py --mode hybrid --latency
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "retrieval_cases.json"


def _load_cases() -> dict:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _keyword_doc_ids(query: str, k: int) -> list[str]:
    from app.knowledge.retrieve import _select_keyword

    sel = _select_keyword([{"role": "user", "content": query}], query=query)
    # Drop always-on core from scoring set for guide precision.
    ids = [p for p in sel.pack_ids if p != "core"]
    return ids[:k]


def _dense_doc_ids(query: str, k: int) -> tuple[list[str], bool]:
    from app.knowledge.dense import select_dense

    sel = select_dense(query)
    if sel is None:
        raise RuntimeError("Dense index not ready — run: uv run python -m app.knowledge")
    ids = [p for p in sel.pack_ids if p != "core"][:k]
    return ids, sel.no_answer


def _hybrid_doc_ids(query: str, k: int) -> tuple[list[str], bool]:
    from app.knowledge.hybrid import select_hybrid

    sel = select_hybrid(query)
    if sel is None:
        raise RuntimeError("Hybrid index not ready — run: uv run python -m app.knowledge")
    ids = [p for p in sel.pack_ids if p != "core"][:k]
    return ids, sel.no_answer


def _recall(expected: set[str], got: list[str]) -> float:
    if not expected:
        return 1.0 if not got else 0.0
    hit = sum(1 for e in expected if e in got)
    return hit / len(expected)


def _precision(expected: set[str], got: list[str]) -> float:
    if not got:
        return 1.0 if not expected else 0.0
    hit = sum(1 for g in got if g in expected)
    return hit / len(got)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = int(round(0.95 * (len(ordered) - 1)))
    return ordered[idx]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QUE retrieval eval (precision / recall@K)")
    parser.add_argument("--mode", choices=("keyword", "dense", "hybrid"), default="keyword")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--latency",
        action="store_true",
        help="Record per-case wall time; print mean and p95 ms.",
    )
    args = parser.parse_args(argv)

    payload = _load_cases()
    k = int(payload.get("k") or 5)
    cases = list(payload.get("cases") or [])

    recalls: list[float] = []
    precisions: list[float] = []
    latencies_ms: list[float] = []
    no_answer_ok = 0
    no_answer_n = 0
    rows: list[dict] = []

    for case in cases:
        query = str(case["query"])
        expected = set(case.get("expected_doc_ids") or [])
        expect_no = bool(case.get("expect_no_answer"))

        t0 = time.perf_counter()
        if args.mode == "keyword":
            got = _keyword_doc_ids(query, k)
            no_answer = False
        elif args.mode == "hybrid":
            got, no_answer = _hybrid_doc_ids(query, k)
        else:
            got, no_answer = _dense_doc_ids(query, k)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if args.latency:
            latencies_ms.append(elapsed_ms)

        if expect_no:
            no_answer_n += 1
            if args.mode in {"dense", "hybrid"} and no_answer:
                no_answer_ok += 1
            elif args.mode == "keyword":
                no_answer_ok += 1  # not scored for keyword
            rows.append(
                {
                    "id": case["id"],
                    "expect_no_answer": True,
                    "no_answer": no_answer,
                    "got": got,
                    "latency_ms": round(elapsed_ms, 2),
                }
            )
            continue

        r = _recall(expected, got)
        p = _precision(expected, got)
        recalls.append(r)
        precisions.append(p)
        rows.append(
            {
                "id": case["id"],
                "recall": round(r, 3),
                "precision": round(p, 3),
                "expected": sorted(expected),
                "got": got,
                "latency_ms": round(elapsed_ms, 2),
            }
        )

    summary = {
        "mode": args.mode,
        "n_scored": len(recalls),
        "mean_recall_at_k": round(sum(recalls) / len(recalls), 4) if recalls else 0.0,
        "mean_precision_at_k": round(sum(precisions) / len(precisions), 4) if precisions else 0.0,
        "k": k,
        "no_answer_correct": no_answer_ok,
        "no_answer_total": no_answer_n,
        "cases_path": str(CASES_PATH),
    }
    if args.latency and latencies_ms:
        summary["latency_mean_ms"] = round(statistics.mean(latencies_ms), 2)
        summary["latency_p95_ms"] = round(_p95(latencies_ms), 2)

    if args.json:
        print(json.dumps({"summary": summary, "rows": rows}, indent=2))
    else:
        line = (
            f"mode={summary['mode']} n={summary['n_scored']} "
            f"recall@{k}={summary['mean_recall_at_k']} "
            f"precision@{k}={summary['mean_precision_at_k']} "
            f"no_answer={summary['no_answer_correct']}/{summary['no_answer_total']}"
        )
        if args.latency and latencies_ms:
            line += (
                f" latency_mean_ms={summary['latency_mean_ms']} "
                f"latency_p95_ms={summary['latency_p95_ms']}"
            )
        print(line)
        misses = [r for r in rows if r.get("recall", 1) < 1.0 and "expect_no_answer" not in r]
        if misses:
            print(f"partial/miss ({len(misses)}):")
            for row in misses[:15]:
                print(f"  {row['id']}: expected={row['expected']} got={row['got']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
