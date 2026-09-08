#!/usr/bin/env python3
"""Score Phase 4 insight tool selection accuracy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "tool_cases.json"


def main() -> int:
    from app.tools.select import select_tool

    payload = json.loads(CASES.read_text(encoding="utf-8"))
    cases = list(payload.get("cases") or [])
    hits = 0
    misses = []
    for case in cases:
        ui = {"current_page": case.get("page") or "unknown"}
        if case.get("exam_id"):
            ui["current_exam_id"] = case["exam_id"]
        sel = select_tool(query=case["query"], ui_context=ui)
        got = sel.tool.name if sel.tool else None
        exp = case["expected_tool"]
        if got == exp:
            hits += 1
        else:
            misses.append({"id": case["id"], "expected": exp, "got": got, "clarify": sel.needs_clarify})
    n = len(cases) or 1
    acc = hits / n
    print(f"tool_selection_accuracy={acc:.4f} hits={hits}/{n}")
    for m in misses:
        print(f"  miss {m}")
    return 0 if acc >= 0.85 else 1


if __name__ == "__main__":
    sys.exit(main())
