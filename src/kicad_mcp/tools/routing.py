"""Routing tools — trace segments, vias, and ratsnest."""

from __future__ import annotations

from typing import Any

from .registry import register_tool


def _get_mgr():
    from .mutation import _get_manager

    return _get_manager()


# ── Handlers ────────────────────────────────────────────────────────


def _route_trace_handler(
    session_id: str,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    width: float,
    layer: str,
    net_number: int,
) -> dict[str, Any]:
    """Add a trace segment between two points.

    Args:
        session_id: Active session ID.
        start_x: Start X coordinate (mm).
        start_y: Start Y coordinate (mm).
        end_x: End X coordinate (mm).
        end_y: End Y coordinate (mm).
        width: Trace width (mm).
        layer: Copper layer (e.g., "F.Cu").
        net_number: Net number for the trace.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_route_trace(
            session, start_x, start_y, end_x, end_y, width, layer, net_number
        )
        # Extract full UUID from target "segment:<uuid>"
        seg_uuid = record.target.split(":", 1)[1] if ":" in record.target else ""
        result = record.to_dict()
        result["uuid"] = seg_uuid
        return {"status": "routed", "change": result}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, RuntimeError) as exc:
        return {"error": str(exc)}


def _add_via_handler(
    session_id: str,
    x: float,
    y: float,
    net_number: int,
    size: float = 0.8,
    drill: float = 0.4,
    start_layer: str = "F.Cu",
    end_layer: str = "B.Cu",
) -> dict[str, Any]:
    """Add a via at a specific point.

    Args:
        session_id: Active session ID.
        x: X coordinate (mm).
        y: Y coordinate (mm).
        net_number: Net number.
        size: Via pad size (mm). Default: 0.8.
        drill: Via drill diameter (mm). Default: 0.4.
        start_layer: Start copper layer. Default: "F.Cu".
        end_layer: End copper layer. Default: "B.Cu".
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_add_via(session, x, y, net_number, size, drill, (start_layer, end_layer))
        via_uuid = record.target.split(":", 1)[1] if ":" in record.target else ""
        result = record.to_dict()
        result["uuid"] = via_uuid
        return {"status": "added", "change": result}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, RuntimeError) as exc:
        return {"error": str(exc)}


def _delete_trace_handler(session_id: str, segment_uuid: str) -> dict[str, Any]:
    """Delete a trace segment by its UUID.

    Args:
        session_id: Active session ID.
        segment_uuid: UUID of the segment to delete.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_delete_trace(session, segment_uuid)
        return {"status": "deleted", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _delete_via_handler(session_id: str, via_uuid: str) -> dict[str, Any]:
    """Delete a via by its UUID.

    Args:
        session_id: Active session ID.
        via_uuid: UUID of the via to delete.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_delete_via(session, via_uuid)
        return {"status": "deleted", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _get_ratsnest_handler(session_id: str) -> dict[str, Any]:
    """Get unrouted connections (ratsnest) for the board.

    Args:
        session_id: Active session ID.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        unrouted = mgr.get_ratsnest(session)
        return {
            "unrouted_net_count": len(unrouted),
            "unrouted": unrouted,
        }
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="route_trace",
    description="Add a trace segment between two points on a copper layer.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "start_x": {"type": "number", "description": "Start X coordinate (mm)."},
        "start_y": {"type": "number", "description": "Start Y coordinate (mm)."},
        "end_x": {"type": "number", "description": "End X coordinate (mm)."},
        "end_y": {"type": "number", "description": "End Y coordinate (mm)."},
        "width": {"type": "number", "description": "Trace width (mm)."},
        "layer": {"type": "string", "description": "Copper layer (e.g., 'F.Cu')."},
        "net_number": {"type": "integer", "description": "Net number for the trace."},
    },
    handler=_route_trace_handler,
    category="routing",
)

register_tool(
    name="add_via",
    description="Add a via at a specific point to connect between layers.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "x": {"type": "number", "description": "X coordinate (mm)."},
        "y": {"type": "number", "description": "Y coordinate (mm)."},
        "net_number": {"type": "integer", "description": "Net number."},
        "size": {"type": "number", "description": "Via pad size (mm). Default: 0.8."},
        "drill": {"type": "number", "description": "Drill diameter (mm). Default: 0.4."},
        "start_layer": {"type": "string", "description": "Start layer. Default: 'F.Cu'."},
        "end_layer": {"type": "string", "description": "End layer. Default: 'B.Cu'."},
    },
    handler=_add_via_handler,
    category="routing",
)

register_tool(
    name="delete_trace",
    description="Delete a trace segment by UUID.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "segment_uuid": {"type": "string", "description": "UUID of the segment to delete."},
    },
    handler=_delete_trace_handler,
    category="routing",
)

register_tool(
    name="delete_via",
    description="Delete a via by UUID.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "via_uuid": {"type": "string", "description": "UUID of the via to delete."},
    },
    handler=_delete_via_handler,
    category="routing",
)

register_tool(
    name="get_ratsnest",
    description="Get unrouted connections (ratsnest) showing nets that need routing.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
    },
    handler=_get_ratsnest_handler,
    category="routing",
)
