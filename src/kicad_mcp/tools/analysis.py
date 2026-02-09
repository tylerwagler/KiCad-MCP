"""Analysis tools — routed (discoverable via meta-tools).

These tools provide detailed board analysis capabilities and are
accessible through the tool router's execute_tool meta-tool.
"""

from __future__ import annotations

import math
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


# ── Clearance check ─────────────────────────────────────────────────


def _check_clearance_handler(
    reference_a: str,
    reference_b: str,
) -> dict[str, Any]:
    """Check the minimum clearance distance between two components.

    Calculates the minimum distance between component bounding boxes.

    Args:
        reference_a: First component reference (e.g., 'U1').
        reference_b: Second component reference (e.g., 'C1').
    """
    from .. import state

    footprints = state.get_footprints()

    fp_a = next((fp for fp in footprints if fp.reference == reference_a), None)
    fp_b = next((fp for fp in footprints if fp.reference == reference_b), None)

    if fp_a is None:
        return {"error": f"Component {reference_a!r} not found"}
    if fp_b is None:
        return {"error": f"Component {reference_b!r} not found"}

    # Calculate center-to-center distance
    ax, ay = fp_a.position.x, fp_a.position.y
    bx, by = fp_b.position.x, fp_b.position.y
    center_dist = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)

    # Calculate pad-to-pad minimum distance
    min_dist = float("inf")
    closest_pair = None
    for pad_a in fp_a.pads:
        pa_x = ax + pad_a.position.x
        pa_y = ay + pad_a.position.y
        for pad_b in fp_b.pads:
            pb_x = bx + pad_b.position.x
            pb_y = by + pad_b.position.y
            dist = math.sqrt((pb_x - pa_x) ** 2 + (pb_y - pa_y) ** 2)
            if dist < min_dist:
                min_dist = dist
                closest_pair = (
                    f"{reference_a}:{pad_a.number}",
                    f"{reference_b}:{pad_b.number}",
                )

    if min_dist == float("inf"):
        min_dist = center_dist

    return {
        "reference_a": reference_a,
        "reference_b": reference_b,
        "center_distance_mm": round(center_dist, 4),
        "min_clearance_mm": round(min_dist, 4),
        "closest_pair": list(closest_pair) if closest_pair else None,
    }


register_tool(
    name="check_clearance",
    description="Check minimum clearance distance between two components.",
    parameters={
        "reference_a": {"type": "string", "description": "First component reference."},
        "reference_b": {"type": "string", "description": "Second component reference."},
    },
    handler=_check_clearance_handler,
    category="analysis",
)
