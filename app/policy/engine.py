"""Policy engine — can this role call this tool right now?"""

from __future__ import annotations

from dataclasses import dataclass

from app.policy.capabilities import tool_allowed_for_role
from app.policy.roles import NormalizedRole, normalize_role
from app.tools.registry import get_tool


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    reason: str
    requires_confirmation: bool = False
    normalized_role: NormalizedRole | None = None


def evaluate_tool_call(
    *,
    role: str | None,
    tool_name: str,
    risk_tier: str | None = None,
) -> PolicyDecision:
    """Fail-closed policy decision.

    Read tools never require confirmation. Non-read (write) tools always do —
    see app/tools/executor.py's propose/confirm split and
    app/orchestration/pending_actions.py for the human-in-the-loop flow.
    """
    normalized = normalize_role(role)
    if normalized is None:
        return PolicyDecision(
            allow=False,
            reason="missing_or_unknown_role",
            requires_confirmation=False,
            normalized_role=None,
        )

    spec = get_tool(tool_name)
    if spec is None:
        return PolicyDecision(
            allow=False,
            reason="unknown_tool",
            requires_confirmation=False,
            normalized_role=normalized,
        )

    tier = (risk_tier or spec.risk_tier or "read").strip().casefold()
    requires_confirmation = tier != "read"

    if not tool_allowed_for_role(spec, normalized):
        return PolicyDecision(
            allow=False,
            reason="role_not_permitted",
            requires_confirmation=False,
            normalized_role=normalized,
        )

    return PolicyDecision(
        allow=True,
        reason="allowed",
        requires_confirmation=requires_confirmation,
        normalized_role=normalized,
    )


POLICY_DENY_CLARIFY = (
    "Live exam and account insights are only available for teacher accounts. "
    "I can still help with how Quizzer works — ask a product question, or open "
    "the relevant screen in the app."
)
