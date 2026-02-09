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
        record = mgr.apply_create_zone(
            session, net_name, layer, tuples, min_thickness, priority
        )
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
