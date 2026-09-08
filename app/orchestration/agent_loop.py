"""Bounded multi-tool agent loop (Phase 7).

Deterministic selection + Phase 5 policy. No LLM ReAct / planner.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

from app.core.config import Settings, get_settings
from app.obs.budget import allow_tool_call
from app.tools.executor import ToolExecution, invoke_tool_selection
from app.tools.registry import WRITE_TOOL_NAMES
from app.tools.select import select_tool_prefer_raw

logger = structlog.get_logger(__name__)

TerminationReason = Literal[
    "converged",
    "step_limit",
    "call_limit",
    "timeout",
    "token_budget",
    "clarify",
    "error",
]

PARTIAL_REASONS = frozenset({"step_limit", "call_limit", "timeout", "token_budget"})


def _has_another_tool(selection) -> bool:
    if selection.tool is None or selection.needs_clarify:
        return False
    # Page/route fallbacks are not a new intent — don't treat them as "still looping".
    if selection.reason.startswith(("page_", "tool_route_")):
        return False
    return True


@dataclass
class AgentStepLog:
    step: int
    tool_name: str | None
    reason: str
    ok: bool
    elapsed_ms: float
    error_code: str | None = None


@dataclass
class AgentLoopResult:
    executions: list[ToolExecution] = field(default_factory=list)
    steps: list[AgentStepLog] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    termination_reason: TerminationReason = "converged"
    system_messages: list[str] = field(default_factory=list)
    combined_chars: int = 0

    @property
    def successful_count(self) -> int:
        return sum(1 for ex in self.executions if ex.envelope is not None and not ex.error_code)


@dataclass
class AgentLoopEvent:
    kind: Literal["before", "after", "done"]
    step: int = 0
    tool_name: str | None = None
    ok: bool = True
    result: AgentLoopResult | None = None


def format_partial_note(reason: TerminationReason) -> str:
    return (
        f"AGENT_PARTIAL (stopped due to {reason}): Answer from TOOL_RESULT blocks "
        "already present. Do not invent missing live data. Say what you know and "
        "that some live details were not fetched."
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


async def iter_agent_loop(
    *,
    query: str,
    raw_query: str | None,
    ui_context: dict[str, Any] | None,
    user_id: str | None,
    route: str | None = None,
    request_id: str | None = None,
    settings: Settings | None = None,
) -> AsyncIterator[AgentLoopEvent]:
    """Yield before/after status events, then a done event with the result."""
    cfg = settings or get_settings()
    rid = request_id or uuid.uuid4().hex
    max_steps = max(1, int(cfg.que_agent_max_steps))
    max_calls = max(1, int(cfg.que_tool_max_calls))
    max_ms = max(1, int(cfg.que_agent_max_execution_ms))
    max_chars = max(1, int(cfg.que_agent_max_tool_chars))
    started = time.perf_counter()

    result = AgentLoopResult()
    used: list[str] = []
    termination: TerminationReason = "converged"

    for step in range(1, max_steps + 1):
        if _elapsed_ms(started) >= max_ms:
            termination = "timeout"
            break
        if len(used) >= max_calls:
            termination = "call_limit"
            break
        if result.combined_chars >= max_chars:
            termination = "token_budget"
            break
        ok_work, _deny = allow_tool_call(rid, settings=cfg)
        if not ok_work:
            termination = "token_budget"
            break

        selection = select_tool_prefer_raw(
            raw_query=raw_query or query,
            resolved_query=query,
            ui_context=ui_context,
            route=route,
            # Write tools never run in the chained agent loop — one mutation
            # per confirmed turn only (see runtime_mode.decide_runtime_mode).
            exclude_tools=set(used) | WRITE_TOOL_NAMES,
        )

        if selection.reason.startswith("policy_denied"):
            if not used:
                msg = selection.clarify_prompt or "I can't look that up for your role."
                result.system_messages.append(
                    f"TOOL_CLARIFY (ask the user; do not invent live data):\n{msg}"
                    if selection.clarify_prompt
                    else (
                        "TOOL_ERROR (untrusted; do not invent numbers):\n"
                        '{"code":"forbidden","message":"policy_denied"}\n'
                        "Say Quizzer live data is temporarily unavailable and suggest opening the relevant screen."
                    )
                )
                result.steps.append(
                    AgentStepLog(
                        step=step,
                        tool_name=None,
                        reason=selection.reason,
                        ok=False,
                        elapsed_ms=0.0,
                        error_code="forbidden",
                    )
                )
                termination = "error"
            else:
                termination = "converged"
            break

        if selection.needs_clarify or selection.tool is None:
            if not used:
                execution = await invoke_tool_selection(
                    selection,
                    user_id=user_id,
                    request_id=rid,
                    ui_context=ui_context,
                    calls_used=len(used),
                    settings=cfg,
                )
                result.executions.append(execution)
                result.system_messages.append(execution.system_message)
                result.combined_chars += len(execution.system_message)
                result.steps.append(
                    AgentStepLog(
                        step=step,
                        tool_name=None,
                        reason=selection.reason,
                        ok=False,
                        elapsed_ms=execution.latency_ms,
                        error_code=execution.error_code,
                    )
                )
                termination = "clarify"
            else:
                termination = "converged"
            break

        tool_name = selection.tool.name
        yield AgentLoopEvent(kind="before", step=step, tool_name=tool_name)

        execution = await invoke_tool_selection(
            selection,
            user_id=user_id,
            request_id=rid,
            ui_context=ui_context,
            calls_used=len(used),
            settings=cfg,
        )
        ok = execution.envelope is not None and not execution.error_code
        result.executions.append(execution)
        result.system_messages.append(execution.system_message)
        result.combined_chars += len(execution.system_message)
        result.steps.append(
            AgentStepLog(
                step=step,
                tool_name=tool_name,
                reason=selection.reason,
                ok=ok,
                elapsed_ms=execution.latency_ms,
                error_code=execution.error_code,
            )
        )
        logger.info(
            "que_agent_step",
            request_id=rid,
            step=step,
            tool_name=tool_name,
            reason=selection.reason,
            ok=ok,
            elapsed_ms=round(execution.latency_ms, 2),
            error_code=execution.error_code,
        )
        yield AgentLoopEvent(kind="after", step=step, tool_name=tool_name, ok=ok)

        if execution.error_code:
            used.append(tool_name)
            termination = "error"
            break

        used.append(tool_name)

        if _elapsed_ms(started) >= max_ms:
            termination = "timeout"
            break
        if result.combined_chars >= max_chars:
            termination = "token_budget"
            break
        if len(used) >= max_calls:
            nxt = select_tool_prefer_raw(
                raw_query=raw_query or query,
                resolved_query=query,
                ui_context=ui_context,
                route=route,
                exclude_tools=set(used) | WRITE_TOOL_NAMES,
            )
            if _has_another_tool(nxt):
                termination = "call_limit"
            else:
                termination = "converged"
            break
        if step >= max_steps:
            nxt = select_tool_prefer_raw(
                raw_query=raw_query or query,
                resolved_query=query,
                ui_context=ui_context,
                route=route,
                exclude_tools=set(used) | WRITE_TOOL_NAMES,
            )
            if _has_another_tool(nxt):
                termination = "step_limit"
            else:
                termination = "converged"
            break

    result.tools_used = list(used)
    result.termination_reason = termination
    if (
        termination in PARTIAL_REASONS
        and result.successful_count >= 1
    ):
        result.system_messages.append(format_partial_note(termination))

    logger.info(
        "que_agent_done",
        request_id=rid,
        steps=len(result.steps),
        tools_used=result.tools_used,
        termination=termination,
        elapsed_ms=round(_elapsed_ms(started), 2),
        combined_chars=result.combined_chars,
    )
    yield AgentLoopEvent(kind="done", result=result)


async def run_agent_loop(
    *,
    query: str,
    raw_query: str | None,
    ui_context: dict[str, Any] | None,
    user_id: str | None,
    route: str | None = None,
    request_id: str | None = None,
    settings: Settings | None = None,
) -> AgentLoopResult:
    result: AgentLoopResult | None = None
    async for event in iter_agent_loop(
        query=query,
        raw_query=raw_query,
        ui_context=ui_context,
        user_id=user_id,
        route=route,
        request_id=request_id,
        settings=settings,
    ):
        if event.kind == "done" and event.result is not None:
            result = event.result
    return result or AgentLoopResult(termination_reason="error")
