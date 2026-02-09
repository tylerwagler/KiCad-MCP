"""MCP Resources — read-only board state exposed to LLMs.

Resources provide structured data that LLMs can read without executing tools.
They're ideal for frequently-accessed, relatively static information.
"""

from __future__ import annotations

import json

from fastmcp import FastMCP


def register_board_resources(mcp: FastMCP) -> None:
    """Register board-related MCP resources."""

    @mcp.resource("kicad://board/summary")
    def board_summary() -> str:
        """Summary of the currently loaded PCB board.

        Includes nets, layers, and component counts.
        """
        from .. import state

        if not state.is_loaded():
            return json.dumps({"error": "No board loaded. Use open_project first."})
        return json.dumps(state.get_summary().to_dict(), indent=2)

    @mcp.resource("kicad://board/components")
    def board_components() -> str:
        """List of all components on the board with reference, value, library, and position."""
        from .. import state

        if not state.is_loaded():
            return json.dumps({"error": "No board loaded. Use open_project first."})
        footprints = state.get_footprints()
        return json.dumps(
            {
                "count": len(footprints),
                "components": [
                    {
                        "reference": fp.reference,
                        "value": fp.value,
                        "library": fp.library,
                        "layer": fp.layer,
                    }
                    for fp in footprints
                ],
            },
            indent=2,
        )

    @mcp.resource("kicad://board/nets")
    def board_nets() -> str:
        """List of all nets on the board."""
        from .. import state

        if not state.is_loaded():
            return json.dumps({"error": "No board loaded. Use open_project first."})
        summary = state.get_summary()
        return json.dumps(
            {"count": len(summary.nets), "nets": [n.to_dict() for n in summary.nets]},
            indent=2,
        )

    @mcp.resource("kicad://component/{reference}")
    def component_detail(reference: str) -> str:
        """Detailed information about a specific component by reference designator."""
        from .. import state

        if not state.is_loaded():
            return json.dumps({"error": "No board loaded. Use open_project first."})
        footprints = state.get_footprints()
        matches = [fp for fp in footprints if fp.reference == reference]
        if not matches:
            return json.dumps({"error": f"No component with reference '{reference}'"})
        return json.dumps(matches[0].to_dict(), indent=2)
