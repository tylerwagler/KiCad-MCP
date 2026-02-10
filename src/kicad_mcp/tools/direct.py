"""Direct tools — always visible to the LLM.

These are the ~15 most important tools that are registered directly
with FastMCP (not routed through meta-tools).
"""

from __future__ import annotations

from typing import Any

from ..tools.registry import register_tool


def _open_project_handler(board_path: str) -> dict[str, Any]:
    """Open a KiCad PCB board file for analysis.

    Args:
        board_path: Path to a .kicad_pcb file.
    """
    from .. import state

    summary = state.load_board(board_path)
    return {
        "status": "ok",
        "message": f"Loaded board: {summary.title or board_path}",
        "summary": summary.to_dict(),
    }


def _get_board_info_handler() -> dict[str, Any]:
    """Get summary information about the currently loaded board."""
    from .. import state

    summary = state.get_summary()
    return summary.to_dict()


def _list_components_handler(
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """List components (footprints) on the board with pagination.

    Args:
        limit: Maximum number of components to return. Default: 100.
        offset: Number of components to skip. Default: 0.
    """
    from .. import state

    footprints = state.get_footprints()
    total = len(footprints)
    page = footprints[offset : offset + limit]
    return {
        "count": total,
        "returned": len(page),
        "offset": offset,
        "has_more": offset + limit < total,
        "components": [
            {
                "reference": fp.reference,
                "value": fp.value,
                "library": fp.library,
                "layer": fp.layer,
                "position": fp.position.to_dict(),
            }
            for fp in page
        ],
    }


def _find_component_handler(reference: str) -> dict[str, Any]:
    """Find a specific component by its reference designator (e.g., 'R1', 'U1').

    Args:
        reference: The reference designator to search for.
    """
    from .. import state

    footprints = state.get_footprints()
    matches = [fp for fp in footprints if fp.reference == reference]
    if not matches:
        return {"found": False, "message": f"No component with reference '{reference}'"}
    fp = matches[0]
    return {"found": True, "component": fp.to_dict()}


# Register all direct tools
register_tool(
    name="open_project",
    description="Open a KiCad PCB board file (.kicad_pcb) for analysis and modification.",
    parameters={"board_path": {"type": "string", "description": "Path to .kicad_pcb file"}},
    handler=_open_project_handler,
    category="project",
    direct=True,
)

register_tool(
    name="get_board_info",
    description=(
        "Get summary information about the currently loaded board (nets, layers, components, etc.)."
    ),
    parameters={},
    handler=_get_board_info_handler,
    category="project",
    direct=True,
)

register_tool(
    name="list_components",
    description=(
        "List components (footprints) on the board with reference, value, and position (paginated)."
    ),
    parameters={
        "limit": {
            "type": "integer",
            "description": "Max components to return. Default: 100.",
        },
        "offset": {
            "type": "integer",
            "description": "Number of components to skip. Default: 0.",
        },
    },
    handler=_list_components_handler,
    category="project",
    direct=True,
)

register_tool(
    name="find_component",
    description=("Find a specific component by its reference designator (e.g., 'R1', 'U1', 'C3')."),
    parameters={
        "reference": {
            "type": "string",
            "description": "Reference designator (e.g., 'R1')",
        },
    },
    handler=_find_component_handler,
    category="project",
    direct=True,
)
