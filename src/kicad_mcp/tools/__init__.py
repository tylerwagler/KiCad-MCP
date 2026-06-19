"""KiCad MCP tools — direct and routed tool definitions."""

# Import modules to trigger tool registration via register_tool() calls
from . import (  # noqa: F401
    analysis,
    autoplacement,
    autoroute,
    board_setup,
    creation,
    direct,
    drc,
    export,
    freerouting,
    hierarchy,
    ipc_sync,
    jlcpcb,
    library,
    manufacturer,
    mutation,
    netzone,
    placement,
    project,
    routing,
    schematic,
    sync,
    visual,
)
from .registry import TOOL_REGISTRY, get_categories, register_tool
from .router import register_router_tools

__all__ = [
    "TOOL_REGISTRY",
    "get_categories",
    "register_router_tools",
    "register_tool",
]
