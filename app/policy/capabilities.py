"""Capability helpers — which tools a role may call."""

from __future__ import annotations

from app.policy.roles import NormalizedRole
from app.tools.registry import REGISTRY, ToolSpec, get_tool


def tool_allowed_for_role(spec: ToolSpec, role: NormalizedRole | None) -> bool:
    if role is None:
        return False
    allowed = {r.casefold() for r in spec.roles}
    if role == "admin":
        # Admin inherits teacher capabilities plus any admin-tagged tools.
        return "admin" in allowed or "teacher" in allowed
    return role in allowed


def allowed_tool_names(role: NormalizedRole | None) -> frozenset[str]:
    if role is None:
        return frozenset()
    return frozenset(
        name for name, spec in REGISTRY.items() if tool_allowed_for_role(spec, role)
    )


def is_tool_allowed(tool_name: str, role: NormalizedRole | None) -> bool:
    spec = get_tool(tool_name)
    if spec is None:
        return False
    return tool_allowed_for_role(spec, role)
