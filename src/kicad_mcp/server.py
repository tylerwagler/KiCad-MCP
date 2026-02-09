"""KiCad MCP Server — entry point."""

from __future__ import annotations

from fastmcp import FastMCP

from .prompts import register_prompts
from .resources import register_board_resources
from .tools import TOOL_REGISTRY, register_router_tools


def create_server() -> FastMCP:
    """Create and configure the KiCad MCP server."""
    mcp = FastMCP("kicad-mcp")

    # Register direct tools with FastMCP (always visible to the LLM)
    for spec in TOOL_REGISTRY.values():
        if spec.direct:
            mcp.tool(spec.handler, name=spec.name, description=spec.description)

    # Register the 4 router meta-tools
    register_router_tools(mcp)

    # Register MCP resources (read-only board state)
    register_board_resources(mcp)

    # Register MCP prompt templates
    register_prompts(mcp)

    return mcp


def main() -> None:
    """CLI entry point."""
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
