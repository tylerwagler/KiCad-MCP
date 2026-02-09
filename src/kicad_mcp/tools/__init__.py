"""KiCad MCP tools — direct and routed tool definitions."""

# Import modules to trigger tool registration via register_tool() calls
from . import (  # noqa: F401
    analysis,
    direct,
    drc,
    export,
    library,
    manufacturer,
    mutation,
    netzone,
    placement,
    routing,
    schematic,
)
from .registry import TOOL_REGISTRY, get_categories, register_tool
from .router import register_router_tools

__all__ = [
    "TOOL_REGISTRY",
    "get_categories",
    "register_router_tools",
    "register_tool",
]
