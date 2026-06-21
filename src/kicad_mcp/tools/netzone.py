"""Net and zone tools — create nets, assign to pads, create copper zones."""

from __future__ import annotations

import contextlib
from typing import Any

from ..session import SessionManager
from .registry import register_tool


def _get_mgr() -> SessionManager:
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


def _fill_zones_handler(session_id: str | None = None) -> dict[str, Any]:
    """Fill all copper zones (compute filled_polygon) via pcbnew.

    create_zone/add_copper_pour write only the zone outline; a zone is
    electrically empty until filled, which throws off DRC, render, and routing.
    kicad-cli has no fill command, so this uses pcbnew's ZONE_FILLER on the board
    file. Commit the session first — fill operates on the on-disk board, not
    uncommitted session changes — and note pcbnew rewrites the file in canonical
    form. The in-memory board is refreshed afterward.

    Args:
        session_id: Optional session whose board to fill. Defaults to the
            currently open board.
    """
    from .. import state
    from ..backends import pcbnew_fill

    if session_id:
        mgr = _get_mgr()
        try:
            board_path: str | None = mgr.get_session(session_id).board_path
        except KeyError:
            return {"error": f"Session {session_id!r} not found"}
    else:
        board_path = state.get_board_path()
    if not board_path:
        return {"error": "No board loaded. Use open_project first."}

    try:
        result = pcbnew_fill.fill_zones(board_path)
    except RuntimeError as exc:
        return {"error": str(exc)}
    # Refresh the in-memory board with the filled (and canonicalized) file.
    with contextlib.suppress(OSError):
        state.load_board(board_path)
    return {"status": "filled", **result}


def _set_net_class_handler(
    session_id: str,
    name: str,
    clearance: float | None = None,
    track_width: float | None = None,
    via_diameter: float | None = None,
    via_drill: float | None = None,
    diff_pair_width: float | None = None,
    diff_pair_gap: float | None = None,
    microvia_diameter: float | None = None,
    microvia_drill: float | None = None,
    nets: list[str] | None = None,
    patterns: list[str] | None = None,
) -> dict[str, Any]:
    """Create or update a net class in the .kicad_pro and assign nets to it.

    KiCad 7+ stores net classes in the project file (net_settings.classes), which
    is where run_drc/kicad-cli read clearance, track width, and via rules. Use
    this (not the legacy in-board add_net_class) to make DRC enforce per-class
    intent — e.g. a wide-clearance class across an isolation barrier. Writes the
    .kicad_pro directly; it is not part of the session's undo stack.

    Args:
        session_id: Active session ID (used to locate the .kicad_pro).
        name: Net class name (created if absent, updated if present).
        clearance: Min clearance (mm).
        track_width: Default track width (mm).
        via_diameter: Via pad diameter (mm).
        via_drill: Via drill (mm).
        diff_pair_width: Differential pair width (mm).
        diff_pair_gap: Differential pair gap (mm).
        microvia_diameter: Microvia diameter (mm).
        microvia_drill: Microvia drill (mm).
        nets: Exact net names to assign to this class.
        patterns: Wildcard net patterns (e.g. '/ISO_*') to assign to this class.
    """
    from ..session import project_settings

    fields = {
        "clearance": clearance,
        "track_width": track_width,
        "via_diameter": via_diameter,
        "via_drill": via_drill,
        "diff_pair_width": diff_pair_width,
        "diff_pair_gap": diff_pair_gap,
        "microvia_diameter": microvia_diameter,
        "microvia_drill": microvia_drill,
    }
    fields = {k: v for k, v in fields.items() if v is not None}

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    if not session.board_path:
        return {"error": "Session has no board path; cannot locate .kicad_pro"}
    try:
        result = project_settings.set_net_class(
            session.board_path, name, fields, nets=nets, patterns=patterns
        )
        return {"status": "updated", **result}
    except (ValueError, FileNotFoundError) as exc:
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
    name="fill_zones",
    description=(
        "Fill all copper zones (compute filled_polygon) using pcbnew — kicad-cli "
        "has no fill command. Run after committing zone creation; operates on the "
        "on-disk board and refreshes the in-memory copy. Requires pcbnew."
    ),
    parameters={
        "session_id": {
            "type": "string",
            "description": "Optional session whose board to fill. Defaults to the open board.",
        },
    },
    handler=_fill_zones_handler,
    category="netzone",
)

register_tool(
    name="set_net_class",
    description=(
        "Create/update a net class in the .kicad_pro (net_settings.classes) and "
        "assign nets to it — the KiCad 7+ location run_drc reads. Use this for "
        "DRC-enforced per-class rules (e.g. a wide-clearance isolation class). "
        "Pass exact net names via 'nets' or wildcards via 'patterns'."
    ),
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "name": {"type": "string", "description": "Net class name."},
        "clearance": {"type": "number", "description": "Min clearance (mm)."},
        "track_width": {"type": "number", "description": "Track width (mm)."},
        "via_diameter": {"type": "number", "description": "Via pad diameter (mm)."},
        "via_drill": {"type": "number", "description": "Via drill (mm)."},
        "diff_pair_width": {"type": "number", "description": "Diff-pair width (mm)."},
        "diff_pair_gap": {"type": "number", "description": "Diff-pair gap (mm)."},
        "microvia_diameter": {"type": "number", "description": "Microvia diameter (mm)."},
        "microvia_drill": {"type": "number", "description": "Microvia drill (mm)."},
        "nets": {"type": "array", "description": "Exact net names to assign. Optional."},
        "patterns": {"type": "array", "description": "Wildcard net patterns. Optional."},
    },
    handler=_set_net_class_handler,
    category="netzone",
)

register_tool(
    name="add_net_class",
    description=(
        "Legacy: add a net class to the .kicad_pcb setup section (KiCad 6 and "
        "earlier). KiCad 7+ ignores in-board net classes — use set_net_class "
        "(writes the .kicad_pro) so run_drc honors it."
    ),
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
