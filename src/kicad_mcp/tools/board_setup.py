"""Board setup tools — design rules, board size, outline, mounting holes, text."""

from __future__ import annotations

from typing import Any

from ..session.board_setup_ops import _VALID_SETUP_RULES
from ..session.manager import SessionManager
from .mutation import _get_manager
from .registry import register_tool


def _get_mgr() -> SessionManager:
    return _get_manager()


# ── Handlers ────────────────────────────────────────────────────────


def _get_design_rules_handler() -> dict[str, Any]:
    """Get the current design rules from the board setup section.

    Returns only the design-rule keys valid in KiCad 9's setup section:
    pad_to_mask_clearance, solder_mask_min_width, pad_to_paste_clearance,
    pad_to_paste_clearance_ratio.
    """
    from .. import state

    doc = state.get_document()
    setup_node = doc.root.get("setup")
    if setup_node is None:
        return {"error": "Board has no setup section"}

    rules: dict[str, Any] = {}
    for child in setup_node.children:
        if child.name in _VALID_SETUP_RULES and child.atom_values:
            # child.name is str (list nodes always have a name), child.atom_values is list[str]
            rules[child.name] = child.atom_values[0]
    return {"rules": rules}


def _set_design_rules_handler(
    session_id: str,
    rules: dict[str, float],
) -> dict[str, Any]:
    """Set design rules in the board setup section.

    Only rules valid in KiCad 9's (setup ...) section are accepted:
    pad_to_mask_clearance, solder_mask_min_width, pad_to_paste_clearance,
    pad_to_paste_clearance_ratio. Rules like min_track_width belong in
    the .kicad_dru file and will be rejected.

    Args:
        session_id: Active session ID.
        rules: Dict of rule name to value (e.g., {"pad_to_mask_clearance": 0.1}).
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_set_design_rules(session, rules)
        return {"status": "updated", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _set_layer_stack_handler(
    session_id: str,
    copper_layers: int = 4,
    dielectrics: list[dict[str, Any]] | None = None,
    copper_thickness: float = 0.035,
) -> dict[str, Any]:
    """Set the board copper-layer count and dielectric stackup.

    Converts the board to ``copper_layers`` coppers (2/4/6/8…, even) with KiCad
    numbering (F.Cu=0, In1.Cu=1, …, B.Cu=31) and writes a matching
    ``(setup (stackup …))``. Non-copper layers are preserved.

    Args:
        session_id: Active session ID.
        copper_layers: Number of copper layers (even, 2–32). Default: 4.
        dielectrics: Optional list of per-gap dicts (exactly copper_layers-1),
            each with optional keys type/thickness/material/epsilon_r/loss_tangent.
            Omit for a symmetric FR-4 default (4-layer → 0.2/1.0/0.2 mm).
        copper_thickness: Copper layer thickness in mm. Default: 0.035 (1 oz).
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_set_layer_stack(session, copper_layers, dielectrics, copper_thickness)
        return {"status": "updated", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _set_board_constraints_handler(
    session_id: str,
    rules: dict[str, float],
) -> dict[str, Any]:
    """Write board-level minimum constraints to the project's .kicad_pro.

    These are the global DRC minimums (min track width, clearance, via size,
    annular width, hole sizes) that live in board.design_settings.rules in the
    KiCad 7+ project file — where kicad-cli/run_drc reads them. This writes the
    .kicad_pro directly; it is not part of the session's undo stack.

    Args:
        session_id: Active session ID (used to locate the .kicad_pro).
        rules: Constraint name -> value in mm. Aliases accepted, e.g.
            min_track, min_space, min_annular_width, min_via_drill.
    """
    from ..session import project_settings

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    if not session.board_path:
        return {"error": "Session has no board path; cannot locate .kicad_pro"}
    try:
        result = project_settings.set_board_constraints(session.board_path, rules)
        return {"status": "updated", **result}
    except (ValueError, FileNotFoundError) as exc:
        return {"error": str(exc)}


def _set_board_size_handler(
    session_id: str,
    width: float,
    height: float,
) -> dict[str, Any]:
    """Set the board dimensions by creating a rectangular Edge.Cuts outline.

    Args:
        session_id: Active session ID.
        width: Board width in mm.
        height: Board height in mm.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_set_board_size(session, width, height)
        return {"status": "updated", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _add_board_outline_handler(
    session_id: str,
    points: list[list[float]],
) -> dict[str, Any]:
    """Add a custom board outline on the Edge.Cuts layer.

    Args:
        session_id: Active session ID.
        points: List of [x, y] coordinate pairs defining the outline (min 3).
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        tuples = [(p[0], p[1]) for p in points]
        record = mgr.apply_add_board_outline(session, tuples)
        return {"status": "added", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, IndexError) as exc:
        return {"error": str(exc)}


def _add_mounting_hole_handler(
    session_id: str,
    x: float,
    y: float,
    drill: float = 3.2,
    pad_dia: float = 6.0,
    reference: str | None = None,
) -> dict[str, Any]:
    """Add a mounting hole at the specified position.

    Args:
        session_id: Active session ID.
        x: X position in mm.
        y: Y position in mm.
        drill: Drill diameter in mm. Default: 3.2.
        pad_dia: Pad diameter in mm. Default: 6.0.
        reference: Reference designator. Defaults to the next free H<n>.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_add_mounting_hole(session, x, y, drill, pad_dia, reference)
        return {"status": "added", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _add_board_text_handler(
    session_id: str,
    text: str,
    x: float,
    y: float,
    layer: str = "F.SilkS",
    size: float = 1.0,
    angle: float = 0,
) -> dict[str, Any]:
    """Add a text element to the board.

    Args:
        session_id: Active session ID.
        text: Text string to add.
        x: X position in mm.
        y: Y position in mm.
        layer: Target layer. Default: "F.SilkS".
        size: Text height in mm. Default: 1.0.
        angle: Rotation angle in degrees. Default: 0.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_add_board_text(session, text, x, y, layer, size, angle)
        return {"status": "added", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


_active_layer: str = "F.Cu"


def _set_active_layer_handler(layer: str) -> dict[str, Any]:
    """Set the active working layer preference.

    Args:
        layer: Layer name (e.g., "F.Cu", "B.Cu", "F.SilkS").
    """
    global _active_layer
    _active_layer = layer
    return {"status": "set", "active_layer": layer}


def _get_active_layer() -> str:
    """Get the currently set active layer."""
    return _active_layer


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="get_design_rules",
    description="Get the current design rules from the board setup.",
    parameters={},
    handler=_get_design_rules_handler,
    category="board_setup",
)

register_tool(
    name="set_design_rules",
    description=(
        "Set design rules in the board setup section. "
        "Valid keys: pad_to_mask_clearance, solder_mask_min_width, "
        "pad_to_paste_clearance, pad_to_paste_clearance_ratio. "
        "Rules like min_track_width belong in the .kicad_dru file "
        "and are NOT accepted here."
    ),
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "rules": {
            "type": "object",
            "description": (
                "Dict of rule name to value, e.g. "
                "{'pad_to_mask_clearance': 0.1, 'solder_mask_min_width': 0.05}."
            ),
        },
    },
    handler=_set_design_rules_handler,
    category="board_setup",
)

register_tool(
    name="set_board_constraints",
    description=(
        "Set board-level DRC minimums (min track width, clearance, via "
        "diameter, via/hole drill, annular width, hole-to-hole) in the .kicad_pro "
        "project file, where run_drc reads them. Aliases: min_track, min_space, "
        "min_annular_width, min_via_drill. Writes the project file directly."
    ),
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "rules": {
            "type": "object",
            "description": (
                "Constraint name -> value in mm, e.g. "
                "{'min_track_width': 0.127, 'min_clearance': 0.127, "
                "'min_via_diameter': 0.4, 'min_via_drill': 0.2, "
                "'min_annular_width': 0.1}."
            ),
        },
    },
    handler=_set_board_constraints_handler,
    category="board_setup",
)

register_tool(
    name="set_layer_stack",
    description=(
        "Set the board copper-layer count (2/4/6/8…, even) and dielectric "
        "stackup. Renumbers copper (F.Cu=0, In1.Cu=1, …, B.Cu=31), preserves "
        "non-copper layers, and writes (setup (stackup …)). Omit 'dielectrics' "
        "for a symmetric FR-4 default (4-layer → 0.2/1.0/0.2 mm)."
    ),
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "copper_layers": {
            "type": "integer",
            "description": "Number of copper layers (even, 2–32). Default: 4.",
        },
        "dielectrics": {
            "type": "array",
            "description": (
                "Optional list of (copper_layers-1) dicts, each with optional "
                "keys type/thickness/material/epsilon_r/loss_tangent."
            ),
        },
        "copper_thickness": {
            "type": "number",
            "description": "Copper thickness in mm. Default: 0.035 (1 oz).",
        },
    },
    handler=_set_layer_stack_handler,
    category="board_setup",
)

register_tool(
    name="set_board_size",
    description="Set the board dimensions as a rectangular Edge.Cuts outline.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "width": {"type": "number", "description": "Board width in mm."},
        "height": {"type": "number", "description": "Board height in mm."},
    },
    handler=_set_board_size_handler,
    category="board_setup",
)

register_tool(
    name="add_board_outline",
    description="Add a custom board outline on Edge.Cuts with polygon points.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "points": {
            "type": "array",
            "description": "Outline as [[x,y], ...] coordinate pairs (min 3).",
        },
    },
    handler=_add_board_outline_handler,
    category="board_setup",
)

register_tool(
    name="add_mounting_hole",
    description="Add a mounting hole footprint at a position.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "x": {"type": "number", "description": "X position in mm."},
        "y": {"type": "number", "description": "Y position in mm."},
        "drill": {"type": "number", "description": "Drill diameter (mm). Default: 3.2."},
        "pad_dia": {"type": "number", "description": "Pad diameter (mm). Default: 6.0."},
        "reference": {
            "type": "string",
            "description": "Reference designator. Defaults to the next free H<n>.",
        },
    },
    handler=_add_mounting_hole_handler,
    category="board_setup",
)

register_tool(
    name="add_board_text",
    description="Add a text element to the board.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "text": {"type": "string", "description": "Text string to add."},
        "x": {"type": "number", "description": "X position in mm."},
        "y": {"type": "number", "description": "Y position in mm."},
        "layer": {"type": "string", "description": "Target layer. Default: 'F.SilkS'."},
        "size": {"type": "number", "description": "Text height in mm. Default: 1.0."},
        "angle": {"type": "number", "description": "Rotation degrees. Default: 0."},
    },
    handler=_add_board_text_handler,
    category="board_setup",
)

register_tool(
    name="set_active_layer",
    description="Set the active working layer preference (does not modify board file).",
    parameters={
        "layer": {"type": "string", "description": "Layer name (e.g., 'F.Cu')."},
    },
    handler=_set_active_layer_handler,
    category="board_setup",
)
