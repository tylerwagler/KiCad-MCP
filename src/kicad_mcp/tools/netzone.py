"""Net and zone tools — create nets, assign to pads, create copper zones."""

from __future__ import annotations

from typing import Any

from .registry import register_tool


def _get_mgr():
    from .mutation import _get_manager

    return _get_manager()


# ── Handlers ────────────────────────────────────────────────────────


def _create_net_handler(session_id: str, net_name: str) -> dict[str, Any]:
    """Create a new net on the board.

    Args:
        session_id: Active session ID.
        net_name: Name for the new net (e.g., "VCC_3V3").
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_create_net(session, net_name)
        return {"status": "created", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _delete_net_handler(session_id: str, net_name: str) -> dict[str, Any]:
    """Delete a net from the board.

    Args:
        session_id: Active session ID.
        net_name: Name of the net to delete.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_delete_net(session, net_name)
        return {"status": "deleted", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _assign_net_to_pad_handler(
    session_id: str,
    reference: str,
    pad_number: str,
    net_name: str,
) -> dict[str, Any]:
    """Assign a net to a specific pad on a component.

    Args:
        session_id: Active session ID.
        reference: Component reference designator (e.g., "R1").
        pad_number: Pad number (e.g., "1").
        net_name: Net name to assign (must already exist).
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_assign_net(session, reference, pad_number, net_name)
        return {"status": "assigned", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _create_zone_handler(
    session_id: str,
    net_name: str,
    layer: str,
    points: list[list[float]],
    min_thickness: float = 0.25,
    priority: int = 0,
) -> dict[str, Any]:
    """Create a copper zone (pour) on the board.

    Args:
        session_id: Active session ID.
        net_name: Net to fill the zone with (e.g., "GND").
        layer: Copper layer (e.g., "F.Cu" or "B.Cu").
        points: List of [x, y] coordinate pairs defining the polygon outline (min 3).
        min_thickness: Minimum trace width in zone fill (mm). Default: 0.25.
        priority: Zone fill priority (higher fills first). Default: 0.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        tuples = [(p[0], p[1]) for p in points]
        record = mgr.apply_create_zone(session, net_name, layer, tuples, min_thickness, priority)
        return {"status": "created", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, IndexError) as exc:
        return {"error": str(exc)}


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="create_net",
    description="Create a new net on the board.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "net_name": {"type": "string", "description": "Name for the new net (e.g., 'VCC_3V3')."},
    },
    handler=_create_net_handler,
    category="netzone",
)

register_tool(
    name="delete_net",
    description="Delete a net from the board.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "net_name": {"type": "string", "description": "Name of the net to delete."},
    },
    handler=_delete_net_handler,
    category="netzone",
)

register_tool(
    name="assign_net_to_pad",
    description="Assign a net to a specific pad on a component.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "reference": {"type": "string", "description": "Component reference (e.g., 'R1')."},
        "pad_number": {"type": "string", "description": "Pad number (e.g., '1')."},
        "net_name": {"type": "string", "description": "Net name to assign (must exist)."},
    },
    handler=_assign_net_to_pad_handler,
    category="netzone",
)

register_tool(
    name="create_zone",
    description="Create a copper zone (pour) on a layer with a polygon outline.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "net_name": {"type": "string", "description": "Net for the zone fill (e.g., 'GND')."},
        "layer": {"type": "string", "description": "Copper layer (e.g., 'F.Cu')."},
        "points": {
            "type": "array",
            "description": "Polygon outline as [[x,y], ...] coordinate pairs (min 3 points).",
        },
        "min_thickness": {
            "type": "number",
            "description": "Min trace width in zone fill (mm). Default: 0.25.",
        },
        "priority": {
            "type": "integer",
            "description": "Fill priority (higher fills first). Default: 0.",
        },
    },
    handler=_create_zone_handler,
    category="netzone",
)


# ── Copper Pour / Net Class / Layer Constraints ────────────────────


def _add_copper_pour_handler(
    session_id: str,
    net_name: str,
    layer: str,
    priority: int = 0,
) -> dict[str, Any]:
    """Add a copper pour that fills the entire board outline.

    Uses the board's Edge.Cuts outline as the zone polygon.

    Args:
        session_id: Active session ID.
        net_name: Net for the pour (e.g., "GND").
        layer: Copper layer (e.g., "F.Cu").
        priority: Zone fill priority. Default: 0.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    # Extract board outline from Edge.Cuts gr_lines
    assert session._working_doc is not None
    points: list[tuple[float, float]] = []
    for child in session._working_doc.root.children:
        if child.name == "gr_line":
            layer_node = child.get("layer")
            if layer_node and layer_node.first_value == "Edge.Cuts":
                start = child.get("start")
                if start and len(start.atom_values) >= 2:
                    pt = (float(start.atom_values[0]), float(start.atom_values[1]))
                    if pt not in points:
                        points.append(pt)

    if len(points) < 3:
        return {"error": "Board outline not found or has fewer than 3 points on Edge.Cuts"}

    try:
        record = mgr.apply_create_zone(session, net_name, layer, points, priority=priority)
        return {"status": "created", "change": record.to_dict()}
    except ValueError as exc:
        return {"error": str(exc)}


def _add_net_class_handler(
    session_id: str,
    name: str,
    clearance: float = 0.2,
    trace_width: float = 0.25,
    via_dia: float = 0.8,
    via_drill: float = 0.4,
    nets: list[str] | None = None,
) -> dict[str, Any]:
    """Add a net class definition to the board.

    Args:
        session_id: Active session ID.
        name: Net class name (e.g., "Power").
        clearance: Minimum clearance in mm. Default: 0.2.
        trace_width: Default trace width in mm. Default: 0.25.
        via_dia: Via diameter in mm. Default: 0.8.
        via_drill: Via drill in mm. Default: 0.4.
        nets: List of net names to assign to this class. Optional.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_add_net_class(
            session, name, clearance, trace_width, via_dia, via_drill, nets
        )
        return {"status": "added", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _set_layer_constraints_handler(
    session_id: str,
    layer: str,
    min_width: float | None = None,
    min_clearance: float | None = None,
) -> dict[str, Any]:
    """Set per-layer constraints (min width, min clearance).

    Args:
        session_id: Active session ID.
        layer: Layer name (e.g., "F.Cu").
        min_width: Minimum trace width on this layer (mm). Optional.
        min_clearance: Minimum clearance on this layer (mm). Optional.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_set_layer_constraints(session, layer, min_width, min_clearance)
        return {"status": "set", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


register_tool(
    name="add_copper_pour",
    description="Add a copper pour filling the board outline on a layer.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "net_name": {"type": "string", "description": "Net for the pour (e.g., 'GND')."},
        "layer": {"type": "string", "description": "Copper layer (e.g., 'F.Cu')."},
        "priority": {"type": "integer", "description": "Fill priority. Default: 0."},
    },
    handler=_add_copper_pour_handler,
    category="netzone",
)

register_tool(
    name="add_net_class",
    description="Add a net class with clearance, trace width, and via settings.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "name": {"type": "string", "description": "Net class name (e.g., 'Power')."},
        "clearance": {"type": "number", "description": "Clearance (mm). Default: 0.2."},
        "trace_width": {"type": "number", "description": "Trace width (mm). Default: 0.25."},
        "via_dia": {"type": "number", "description": "Via diameter (mm). Default: 0.8."},
        "via_drill": {"type": "number", "description": "Via drill (mm). Default: 0.4."},
        "nets": {"type": "array", "description": "Net names to assign. Optional."},
    },
    handler=_add_net_class_handler,
    category="netzone",
)

register_tool(
    name="set_layer_constraints",
    description="Set per-layer minimum width and clearance constraints.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "layer": {"type": "string", "description": "Layer name (e.g., 'F.Cu')."},
        "min_width": {"type": "number", "description": "Min trace width (mm). Optional."},
        "min_clearance": {"type": "number", "description": "Min clearance (mm). Optional."},
    },
    handler=_set_layer_constraints_handler,
    category="netzone",
)
