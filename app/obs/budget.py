"""Turn and per-user LLM budgets that skip work instead of running up a bill."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.obs.cost import estimate_prompt_tokens
from app.obs.trace import hash_user_id

CAPACITY_REPLY = (
    "I've hit a usage limit for now. Ask a shorter Quizzer question in a moment, "
    "or try again shortly."
)


@dataclass
class TurnBudget:
    request_id: str
    user_hash: str
    llm_calls: int = 0
    tokens: int = 0
    usd: float = 0.0
    denied: str | None = None  # budget:turn | budget:user


_lock = threading.Lock()
_user_usd: dict[str, deque[tuple[float, float]]] = defaultdict(deque)
_turns: dict[str, TurnBudget] = {}
_user_writes: dict[str, deque[float]] = defaultdict(deque)


def reset_budgets() -> None:
    with _lock:
        _user_usd.clear()
        _turns.clear()
        _user_writes.clear()


def start_turn_budget(*, request_id: str, user_id: str | None) -> TurnBudget:
    budget = TurnBudget(request_id=request_id, user_hash=hash_user_id(user_id))
    with _lock:
        _turns[request_id] = budget
    return budget


def get_turn_budget(request_id: str) -> TurnBudget | None:
    with _lock:
        return _turns.get(request_id)


def finish_turn_budget(request_id: str) -> None:
    with _lock:
        _turns.pop(request_id, None)


def _hour_usd(user_hash: str, *, now: float) -> float:
    q = _user_usd[user_hash]
    cutoff = now - 3600.0
    while q and q[0][0] < cutoff:
        q.popleft()
    return sum(usd for _ts, usd in q)


def user_hour_exceeded(user_id: str | None, *, settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    cap = float(cfg.que_budget_usd_per_user_hour or 0.0)
    if cap <= 0:
        return False
    with _lock:
        return _hour_usd(hash_user_id(user_id), now=time.time()) >= cap


def record_user_usd(user_id: str | None, usd: float | None) -> None:
    if usd is None or usd <= 0:
        return
    with _lock:
        _user_usd[hash_user_id(user_id)].append((time.time(), float(usd)))


def allow_llm_call(
    request_id: str,
    *,
    messages: object | None = None,
    settings: Settings | None = None,
) -> tuple[bool, str | None]:
    """Return (ok, deny_reason). Deny before OpenRouter if the turn/user cap is hit."""
    cfg = settings or get_settings()
    with _lock:
        budget = _turns.get(request_id)
    if budget is None:
        return True, None
    cap_calls = max(1, int(cfg.que_budget_llm_calls_per_turn or 3))
    if budget.llm_calls >= cap_calls:
        budget.denied = "budget:turn"
        return False, "budget:turn"
    cap_tokens = max(1, int(cfg.que_budget_tokens_per_turn or 4000))
    est = estimate_prompt_tokens(messages) + int(cfg.llm_max_tokens or 0)
    if budget.tokens + est > cap_tokens:
        budget.denied = "budget:turn"
        return False, "budget:turn"
    hour_cap = float(cfg.que_budget_usd_per_user_hour or 0.0)
    if hour_cap > 0:
        with _lock:
            spent = _hour_usd(budget.user_hash, now=time.time())
        if spent >= hour_cap:
            budget.denied = "budget:user"
            return False, "budget:user"
    return True, None


def allow_tool_call(
    request_id: str,
    *,
    settings: Settings | None = None,
) -> tuple[bool, str | None]:
    """Stop further Quizzer hops when the turn/user budget already tripped."""
    cfg = settings or get_settings()
    with _lock:
        budget = _turns.get(request_id)
    if budget is None:
        return True, None
    if budget.denied:
        return False, budget.denied
    hour_cap = float(cfg.que_budget_usd_per_user_hour or 0.0)
    if hour_cap > 0:
        with _lock:
            spent = _hour_usd(budget.user_hash, now=time.time())
        if spent >= hour_cap:
            budget.denied = "budget:user"
            return False, "budget:user"
    return True, None


def allow_write_action(user_id: str | None, *, settings: Settings | None = None) -> tuple[bool, str | None]:
    """Stricter per-user cap on *confirmed* write-tool executions per hour.

    Independent of the general LLM/tool budgets — a compromised token or a
    confused user rapid-firing 'yes' should not be able to publish/notify/
    delete more than a handful of times per hour.
    """
    cfg = settings or get_settings()
    cap = max(0, int(getattr(cfg, "que_budget_write_actions_per_hour", 20) or 0))
    if cap <= 0:
        return True, None
    user_hash = hash_user_id(user_id)
    now = time.time()
    cutoff = now - 3600.0
    with _lock:
        q = _user_writes[user_hash]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= cap:
            return False, "budget:write_hourly"
    return True, None


def record_write_action(user_id: str | None) -> None:
    with _lock:
        _user_writes[hash_user_id(user_id)].append(time.time())


def note_llm_usage(
    request_id: str,
    *,
    tokens: int,
    usd: float | None,
    user_id: str | None = None,
) -> None:
    with _lock:
        budget = _turns.get(request_id)
        if budget is not None:
            budget.llm_calls += 1
            budget.tokens += max(0, int(tokens))
            if usd:
                budget.usd += float(usd)
    record_user_usd(user_id, usd)
