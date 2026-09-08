"""In-process TTL store for write-tool confirmations (human-in-the-loop).

Same tradeoff as the existing in-process cache / budget / circuit-breaker
modules: process-local, not shared across workers or restarts. A stale
pending action just means the user has to re-ask — never a silent
mutation, so this is a safe default for a single/few-instance deployment.

One pending action per conversation thread. Proposing a new write action
replaces any previous one for that thread (the user can only be asked to
confirm the most recent request).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field

_DEFAULT_TTL_SECONDS = 300.0  # 5 minutes — long enough for a real reply, short
# enough that a "yes" days later never fires a stale mutation.

_lock = threading.Lock()


@dataclass(frozen=True)
class PendingAction:
    thread_key: str
    tool_name: str
    args: dict = field(default_factory=dict)
    user_id: str | None = None
    role: str | None = None
    idempotency_key: str = ""
    confirmation_prompt: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0


_pending: dict[str, PendingAction] = {}


def reset_pending_actions() -> None:
    """Test-only: clear all pending confirmations."""
    with _lock:
        _pending.clear()


def _sweep_locked(now: float) -> None:
    expired = [key for key, action in _pending.items() if action.expires_at <= now]
    for key in expired:
        _pending.pop(key, None)


def make_idempotency_key(thread_key: str, tool_name: str, args: dict) -> str:
    """Stable-ish key so a retried/duplicated confirm never double-executes."""
    blob = json.dumps({"t": thread_key, "tool": tool_name, "args": args}, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
    return f"{digest}-{uuid.uuid4().hex[:8]}"


def propose_action(
    *,
    thread_key: str,
    tool_name: str,
    args: dict,
    user_id: str | None,
    role: str | None,
    confirmation_prompt: str,
    ttl_seconds: float = _DEFAULT_TTL_SECONDS,
) -> PendingAction:
    now = time.time()
    action = PendingAction(
        thread_key=thread_key,
        tool_name=tool_name,
        args=dict(args or {}),
        user_id=user_id,
        role=role,
        idempotency_key=make_idempotency_key(thread_key, tool_name, args or {}),
        confirmation_prompt=confirmation_prompt,
        created_at=now,
        expires_at=now + max(30.0, float(ttl_seconds or _DEFAULT_TTL_SECONDS)),
    )
    with _lock:
        _sweep_locked(now)
        _pending[thread_key] = action
    return action


def get_pending(thread_key: str | None) -> PendingAction | None:
    if not thread_key:
        return None
    now = time.time()
    with _lock:
        _sweep_locked(now)
        return _pending.get(thread_key)


def clear_pending(thread_key: str | None) -> None:
    if not thread_key:
        return
    with _lock:
        _pending.pop(thread_key, None)


_AFFIRM_RE_SRC = (
    r"^\s*(?:yes|yeah|yep|yup|confirm(?:ed)?|go ahead|do it|proceed|okay|ok|sure)"
    r"(?:,?\s*(?:do it|go ahead|confirm(?:ed)?|please))?\s*[.!]?\s*$"
)
_DENY_RE_SRC = (
    r"^\s*(?:no|nope|nah|cancel|stop|don'?t(?: do (?:it|that))?|never ?mind)\s*[.!]?\s*$"
)

_AFFIRM_RE = re.compile(_AFFIRM_RE_SRC, re.I)
_DENY_RE = re.compile(_DENY_RE_SRC, re.I)


def is_affirmative_reply(text: str) -> bool:
    """Tight match only — a short standalone 'yes'-shaped reply.

    Deliberately strict: any extra wording (which could carry injected
    instructions) falls through to "ambiguous" and abandons the pending
    action rather than executing it.
    """
    return bool(_AFFIRM_RE.match((text or "").strip()))


def is_negative_reply(text: str) -> bool:
    return bool(_DENY_RE.match((text or "").strip()))
