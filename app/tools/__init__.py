"""QUE Phase 4+ tools package."""

from app.tools.registry import REGISTRY, ToolSpec, get_tool

__all__ = [
    "REGISTRY",
    "ToolExecution",
    "ToolSelection",
    "ToolSpec",
    "execute_selected_tool",
    "get_tool",
    "select_tool",
    "select_tool_prefer_raw",
]


def __getattr__(name: str):
    if name in {"ToolSelection", "select_tool", "select_tool_prefer_raw"}:
        from app.tools.select import ToolSelection, select_tool, select_tool_prefer_raw

        return {
            "ToolSelection": ToolSelection,
            "select_tool": select_tool,
            "select_tool_prefer_raw": select_tool_prefer_raw,
        }[name]
    if name in {"ToolExecution", "execute_selected_tool"}:
        from app.tools.executor import ToolExecution, execute_selected_tool

        return {
            "ToolExecution": ToolExecution,
            "execute_selected_tool": execute_selected_tool,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
