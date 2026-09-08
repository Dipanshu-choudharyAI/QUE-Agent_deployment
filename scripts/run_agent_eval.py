#!/usr/bin/env python3
"""Score Phase 7 workflow-vs-agent routing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "agent_cases.json"


def main() -> int:
    from app.core.config import Settings
    from app.orchestration.runtime_mode import decide_runtime_mode
    from app.orchestration.understanding import classify_request

    settings = Settings(
        APP_ENV="local",
        QUE_TOOLS_ENABLED=True,
        QUIZZER_INTERNAL_BASE_URL="http://127.0.0.1:9",
        QUE_SERVICE_KEY="test-service-key-not-for-production",
        QUE_JWT_SECRET="test-que-jwt-secret-not-for-production-32c",
    )
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    cases = list(payload.get("cases") or [])
    hits = 0
    misses = []
    for case in cases:
        ui = {"current_page": case.get("page") or "unknown"}
        if case.get("exam_id"):
            ui["current_exam_id"] = case["exam_id"]
        if case.get("role"):
            ui["user_role"] = case["role"]
        u = classify_request(case["query"])
        mode, reason, _sel = decide_runtime_mode(
            query=case["query"],
            ui_context=ui,
            route=u.route,
            data_need=u.data_need,
            complexity=u.complexity,
            settings=settings,
        )
        exp = case["expected_mode"]
        if mode == exp:
            hits += 1
        else:
            misses.append(
                {
                    "id": case["id"],
                    "expected": exp,
                    "got": mode,
                    "reason": reason,
                    "complexity": u.complexity,
                    "route": u.route,
                }
            )
    n = len(cases) or 1
    acc = hits / n
    print(f"agent_runtime_mode_accuracy={acc:.4f} hits={hits}/{n}")
    for m in misses:
        print(f"  miss {m}")
    return 0 if acc >= 0.85 else 1


if __name__ == "__main__":
    sys.exit(main())
