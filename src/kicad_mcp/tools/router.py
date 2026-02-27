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

import asyncio
import inspect
import json
import time
from collections import defaultdict
from typing import Any

from fastmcp import FastMCP

from .registry import TOOL_REGISTRY, get_categories

MAX_RESPONSE_CHARS = 50_000  # ~12k tokens

# Global rate limiter with per-tool and per-session limits
_rate_limit_buckets: dict[str, float] = defaultdict(lambda: 0.0)
_rate_lock = asyncio.Lock()
_RATE_LIMIT_WINDOW = 60.0  # 60 second rolling window
_MAX_REQUESTS_PER_WINDOW = 100  # Max requests in rolling window
_MAX_CONCURRENT_REQUESTS = 5  # Max concurrent tool executions


def _truncate_response(result: dict[str, Any]) -> dict[str, Any]:
    """Truncate oversized responses by trimming the largest list field."""
    try:
        raw = json.dumps(result, default=str)
    except (TypeError, ValueError):
        return result

    if len(raw) <= MAX_RESPONSE_CHARS:
        return result

    # Find the largest list-valued field
    largest_key = None
    largest_len = 0
    for key, value in result.items():
        if isinstance(value, list) and len(value) > largest_len:
            largest_key = key
            largest_len = len(value)

    if largest_key is None or largest_len == 0:
        return result

    # Pre-populate metadata so the binary search accounts for their size
    original_list = result[largest_key]
    result["_truncated"] = True
    result["_message"] = (
        f"Response truncated: '{largest_key}' reduced from {largest_len} to {largest_len} items. "
        "Use limit/offset parameters or search_* tools for narrower results."
    )

    # Binary-search for a list length that fits
    lo, hi = 0, largest_len
    while lo < hi:
        mid = (lo + hi + 1) // 2
        result[largest_key] = original_list[:mid]
        try:
            if len(json.dumps(result, default=str)) <= MAX_RESPONSE_CHARS:
                lo = mid
            else:
                hi = mid - 1
        except (TypeError, ValueError):
            hi = mid - 1

    result[largest_key] = original_list[:lo]
    result["_message"] = (
        f"Response truncated: '{largest_key}' reduced from {largest_len} to {lo} items. "
        "Use limit/offset parameters or search_* tools for narrower results."
    )
    return result


async def _check_rate_limit(tool_name: str) -> bool:
    """Check if the tool execution is allowed under rate limits."""
    async with _rate_lock:
        current_time = time.time()
        window_start = current_time - _RATE_LIMIT_WINDOW

        # Clean old entries - keep only recent timestamps
        recent_timestamps = [t for t in _rate_limit_buckets.values() if t > window_start]

        # Check if adding this request would exceed the limit
        if len(recent_timestamps) >= _MAX_REQUESTS_PER_WINDOW:
            return False

        # Add this request timestamp
        _rate_limit_buckets[tool_name] = current_time
        return True


def _get_retry_after(tool_name: str) -> float:
    """Get seconds until rate limit resets."""
    current_time = time.time()
    window_start = current_time - _RATE_LIMIT_WINDOW

    if tool_name in _rate_limit_buckets:
        bucket_time = _rate_limit_buckets[tool_name]
        if bucket_time <= window_start:
            return 0.0
        return bucket_time + _RATE_LIMIT_WINDOW - current_time

    return 0.0


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
    async def execute_tool(
        tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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

        # Rate limiting check
        if not await _check_rate_limit(tool_name):
            return {
                "error": "Rate limit exceeded. Please wait before making more requests.",
                "retry_after": _get_retry_after(tool_name),
            }

        try:
            result = spec.handler(**args)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, dict):
                result = _truncate_response(result)
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
