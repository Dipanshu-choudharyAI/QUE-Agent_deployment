"""Phase 5 permission selection gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tools.select import select_tool  # noqa: E402


def main() -> int:
    cases = json.loads((ROOT / "evals" / "permission_cases.json").read_text(encoding="utf-8"))["cases"]
    hits = 0
    misses: list[str] = []
    for case in cases:
        ui = {"current_page": case.get("page") or "unknown"}
        if case.get("exam_id"):
            ui["current_exam_id"] = case["exam_id"]
        if case.get("role"):
            ui["user_role"] = case["role"]
        sel = select_tool(query=case["query"], ui_context=ui)
        denied = sel.reason.startswith("policy_denied")
        tool_name = sel.tool.name if sel.tool else None
        expect_denied = bool(case.get("expect_policy_denied"))
        expect_tool = case.get("expect_tool")
        ok = denied == expect_denied and tool_name == expect_tool
        if ok:
            hits += 1
        else:
            misses.append(
                f"{case['id']}: expected denied={expect_denied} tool={expect_tool} "
                f"got denied={denied} tool={tool_name} reason={sel.reason}"
            )
    n = len(cases)
    acc = hits / n if n else 0.0
    print(f"permission_gate_accuracy={acc:.4f} hits={hits}/{n}")
    for m in misses:
        print(f"  miss {m}")
    return 0 if acc >= 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
