"""KiCad MCP tools — direct and routed tool definitions."""

# Import modules to trigger tool registration via register_tool() calls
from . import analysis, direct, drc, export, manufacturer, mutation  # noqa: F401
from .registry import TOOL_REGISTRY, get_categories, register_tool
from .router import register_router_tools

__all__ = [
    "TOOL_REGISTRY",
    "get_categories",
    "register_router_tools",
    "register_tool",
]
