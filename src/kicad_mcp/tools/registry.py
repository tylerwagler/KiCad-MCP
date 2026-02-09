"""Unified tool registry — single source of truth for all tool definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class ToolSpec:
    """Declarative specification for a single MCP tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    category: str = "general"
    direct: bool = False  # True = always visible to LLM; False = discoverable via router


TOOL_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    handler: Callable[..., Any],
    *,
    category: str = "general",
    direct: bool = False,
) -> None:
    """Register a tool in the global registry."""
    TOOL_REGISTRY[name] = ToolSpec(
        name=name,
        description=description,
        parameters=parameters,
        handler=handler,
        category=category,
        direct=direct,
    )


def get_categories() -> dict[str, list[ToolSpec]]:
    """Return tools grouped by category."""
    categories: dict[str, list[ToolSpec]] = {}
    for tool in TOOL_REGISTRY.values():
        categories.setdefault(tool.category, []).append(tool)
    return categories
