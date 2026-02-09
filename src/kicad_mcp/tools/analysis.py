"""Analysis tools — routed (discoverable via meta-tools).

These tools provide detailed board analysis capabilities and are
accessible through the tool router's execute_tool meta-tool.
"""

from __future__ import annotations

from typing import Any

from ..tools.registry import register_tool


def _get_net_list_handler() -> dict[str, Any]:
    """Get a list of all nets on the board with their numbers and names."""
    from .. import state

    summary = state.get_summary()
    return {
        "count": len(summary.nets),
        "nets": [n.to_dict() for n in summary.nets],
    }


def _get_layer_stack_handler() -> dict[str, Any]:
    """Get the complete layer stack of the board."""
    from .. import state

    summary = state.get_summary()
    return {
        "count": len(summary.layers),
        "copper_layers": summary.copper_layers,
        "layers": [lyr.to_dict() for lyr in summary.layers],
    }


def _get_board_extents_handler() -> dict[str, Any]:
    """Get the physical dimensions of the board (bounding box)."""
    from .. import state

    summary = state.get_summary()
    if summary.bounding_box:
        return {
            "has_outline": True,
            "bounding_box": summary.bounding_box.to_dict(),
        }
    return {"has_outline": False, "message": "No board outline found on Edge.Cuts layer"}


def _get_component_details_handler(reference: str) -> dict[str, Any]:
    """Get detailed information about a component including all pads and net connections.

    Args:
        reference: Reference designator of the component (e.g., 'U1').
    """
    from .. import state

    footprints = state.get_footprints()
    matches = [fp for fp in footprints if fp.reference == reference]
    if not matches:
        return {"found": False, "message": f"No component with reference '{reference}'"}
    fp = matches[0]
    return {
        "found": True,
        "component": fp.to_dict(),
        "pad_count": len(fp.pads),
        "connected_nets": list({p.net_name for p in fp.pads if p.net_name and p.net_name != ""}),
    }


def _get_net_connections_handler(net_name: str) -> dict[str, Any]:
    """Get all components and pads connected to a specific net.

    Args:
        net_name: Name of the net (e.g., 'VBUS', 'GND').
    """
    from .. import state

    footprints = state.get_footprints()
    connections: list[dict[str, Any]] = []
    for fp in footprints:
        for pad in fp.pads:
            if pad.net_name == net_name:
                connections.append(
                    {
                        "component": fp.reference,
                        "pad": pad.number,
                        "pad_type": pad.pad_type,
                        "position": pad.position.to_dict(),
                    }
                )
    return {
        "net_name": net_name,
        "connection_count": len(connections),
        "connections": connections,
    }


# Register all analysis tools (routed, not direct)
register_tool(
    name="get_net_list",
    description="Get a list of all nets on the board.",
    parameters={},
    handler=_get_net_list_handler,
    category="analysis",
)

register_tool(
    name="get_layer_stack",
    description="Get the complete layer stack of the board.",
    parameters={},
    handler=_get_layer_stack_handler,
    category="analysis",
)

register_tool(
    name="get_board_extents",
    description="Get the physical dimensions of the board.",
    parameters={},
    handler=_get_board_extents_handler,
    category="analysis",
)

register_tool(
    name="get_component_details",
    description="Get detailed information about a component including pads and net connections.",
    parameters={
        "reference": {
            "type": "string",
            "description": "Reference designator (e.g., 'U1')",
        },
    },
    handler=_get_component_details_handler,
    category="analysis",
)

register_tool(
    name="get_net_connections",
    description="Get all components and pads connected to a specific net.",
    parameters={"net_name": {"type": "string", "description": "Net name (e.g., 'VBUS')"}},
    handler=_get_net_connections_handler,
    category="analysis",
)
