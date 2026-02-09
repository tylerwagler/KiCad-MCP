"""Tool router — meta-tools for dynamic tool discovery and execution.

Instead of exposing 50+ tools directly (which overwhelms LLM context windows),
we expose ~15 core "direct" tools plus 4 router meta-tools:
  - list_tool_categories
  - get_category_tools
  - execute_tool
  - search_tools

The LLM discovers and invokes specialized tools on-demand, reducing context by ~70%.
"""

from __future__ import annotations

import inspect
from typing import Any

from fastmcp import FastMCP

from .registry import TOOL_REGISTRY, get_categories


def register_router_tools(mcp: FastMCP) -> None:
    """Register the 4 router meta-tools with the FastMCP server."""

    @mcp.tool()
    def list_tool_categories() -> dict[str, Any]:
        """List all available tool categories with tool counts.

        Use this to discover what specialized tools are available,
        then use get_category_tools to see tools in a specific category.
        """
        categories = get_categories()
        result: dict[str, Any] = {}
        for cat_name, tools in sorted(categories.items()):
            # Only include routed (non-direct) tools in category listings
            routed = [t for t in tools if not t.direct]
            if routed:
                result[cat_name] = {
                    "tool_count": len(routed),
                    "tools": [t.name for t in routed],
                }
        return {"categories": result}

    @mcp.tool()
    def get_category_tools(category: str) -> dict[str, Any]:
        """Get detailed information about all tools in a category.

        Args:
            category: Category name from list_tool_categories.

        Returns tool names, descriptions, and parameter schemas.
        """
        categories = get_categories()
        if category not in categories:
            return {
                "error": (
                    f"Unknown category: {category!r}."
                    " Use list_tool_categories to see available categories."
                ),
            }
        tools = [t for t in categories[category] if not t.direct]
        if not tools:
            return {"error": f"No routed tools in category {category!r}."}
        return {
            "category": category,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
                for t in tools
            ],
        }

    @mcp.tool()
    def execute_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a tool by name with the given arguments.

        Use list_tool_categories and get_category_tools to discover available tools,
        then call them through this meta-tool.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments as a JSON object (optional).
        """
        if tool_name not in TOOL_REGISTRY:
            return {
                "error": (
                    f"Unknown tool: {tool_name!r}."
                    " Use search_tools or list_tool_categories to find tools."
                ),
            }

        spec = TOOL_REGISTRY[tool_name]
        args = arguments or {}

        try:
            # Call the handler, supporting both sync and async
            result = spec.handler(**args)
            if inspect.isawaitable(result):
                import asyncio

                result = asyncio.get_event_loop().run_until_complete(result)
            return result  # type: ignore[no-any-return]
        except TypeError as e:
            return {"error": f"Invalid arguments for {tool_name}: {e}"}
        except Exception as e:
            return {"error": f"Tool {tool_name} failed: {e}"}

    @mcp.tool()
    def search_tools(query: str) -> dict[str, Any]:
        """Search for tools by name or description.

        Args:
            query: Search term (e.g., 'gerber', 'zone', 'export', 'drc').
        """
        query_lower = query.lower()
        results: list[dict[str, Any]] = []
        for tool in TOOL_REGISTRY.values():
            if query_lower in tool.name.lower() or query_lower in tool.description.lower():
                results.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "category": tool.category,
                        "direct": tool.direct,
                    }
                )
        return {"query": query, "result_count": len(results), "tools": results}
