"""Normalize Quizzer roles for QUE policy checks."""

from __future__ import annotations

from typing import Literal

NormalizedRole = Literal["student", "teacher", "admin"]

_ALIASES: dict[str, NormalizedRole] = {
    "student": "student",
    "learner": "student",
    "teacher": "teacher",
    "educator": "teacher",
    "instructor": "teacher",
    "admin": "admin",
    "administrator": "admin",
    "staff": "admin",
}


def normalize_role(raw: str | None) -> NormalizedRole | None:
    """Return student|teacher|admin, or None when missing/unknown (fail closed)."""
    if raw is None:
        return None
    key = str(raw).strip().casefold()
    if not key:
        return None
    return _ALIASES.get(key)
