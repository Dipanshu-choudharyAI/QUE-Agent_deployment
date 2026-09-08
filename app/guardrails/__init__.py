"""Phase 10 guardrails — layered input/output checks on top of Phase 5 policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailHit:
    layer: str  # input | output | retrieved
    reason: str
    pattern: str = ""


INPUT_REFUSAL = (
    "I can't follow instructions that try to override QUE's rules or dump private data. "
    "Ask a Quizzer product question — for example how to create, publish, or monitor an exam."
)

OUTPUT_REFUSAL = (
    "I can't share that. Ask a Quizzer how-to, or open the relevant screen in the app "
    "for account-specific numbers."
)
