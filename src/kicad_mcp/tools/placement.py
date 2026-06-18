"""Placement tools — component placement, rotation, flip, deletion."""

from __future__ import annotations

from typing import Any

from ..session import SessionManager
from ..validation import (
    validate_coordinate_pair,
    validate_layer_name,
    validate_reference,
)
from .registry import register_tool


def _get_mgr() -> SessionManager:
    """Get the mutation module's session manager (shared singleton)."""
    from .mutation import _get_manager

    return _get_manager()


# ── Handlers ────────────────────────────────────────────────────────


def _place_component_handler(
    session_id: str,
    footprint_library: str,
    reference: str,
    value: str,
    x: float,
    y: float,
    layer: str = "F.Cu",
) -> dict[str, Any]:
    """Place a new component on the board.

    Args:
        session_id: Active session ID.
        footprint_library: Library identifier (e.g., "Resistor_SMD:R_0402_1005Metric").
        reference: Reference designator (e.g., "R1").
        value: Component value (e.g., "10k").
        x: X position in mm.
        y: Y position in mm.
        layer: Target layer ("F.Cu" or "B.Cu"). Defaults to "F.Cu".
    """
    # Validate inputs
    ref_result = validate_reference(reference)
    if not ref_result.valid:
        return {"error": f"Invalid reference: {ref_result.error}"}

    coord_result = validate_coordinate_pair(x, y, ("x", "y"))
    if not coord_result.valid:
        return {"error": f"Invalid coordinates: {coord_result.error}"}

    layer_result = validate_layer_name(layer)
    if not layer_result.valid:
        return {"error": f"Invalid layer: {layer_result.error}"}

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_place(session, footprint_library, reference, value, x, y, layer)
        return {"status": "placed", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, FileNotFoundError) as exc:
        return {"error": str(exc)}


def _place_from_library_handler(
    session_id: str,
    kicad_mod_path: str,
    reference: str,
    value: str,
    x: float,
    y: float,
    layer: str = "F.Cu",
) -> dict[str, Any]:
    """Place a component from a .kicad_mod footprint file.

    Args:
        session_id: Active session ID.
        kicad_mod_path: Path to a .kicad_mod file.
        reference: Reference designator (e.g., "R1").
        value: Component value (e.g., "10k").
        x: X position in mm.
        y: Y position in mm.
        layer: Target layer. Defaults to "F.Cu".
    """
    from ..security import SecurityError, get_validator

    try:
        get_validator().validate_input(kicad_mod_path)
    except SecurityError as exc:
        return {"error": f"Security error: {exc}"}

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.place_from_kicad_mod(session, kicad_mod_path, reference, value, x, y, layer)
        return {"status": "placed", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, FileNotFoundError) as exc:
        return {"error": str(exc)}


def _rotate_component_handler(
    session_id: str,
    reference: str,
    angle: float,
) -> dict[str, Any]:
    """Rotate a component to a specified angle.

    Args:
        session_id: Active session ID.
        reference: Component reference designator (e.g., "R1").
        angle: Rotation angle in degrees (0-360).
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_rotate(session, reference, angle)
        return {"status": "rotated", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, RuntimeError) as exc:
        return {"error": str(exc)}


def _flip_component_handler(
    session_id: str,
    reference: str,
) -> dict[str, Any]:
    """Flip a component to the opposite side of the board.

    Args:
        session_id: Active session ID.
        reference: Component reference designator (e.g., "R1").
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_flip(session, reference)
        return {"status": "flipped", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, RuntimeError) as exc:
        return {"error": str(exc)}


def _delete_component_handler(
    session_id: str,
    reference: str,
) -> dict[str, Any]:
    """Delete a component from the board.

    Args:
        session_id: Active session ID.
        reference: Component reference designator (e.g., "R1").
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_delete(session, reference)
        return {"status": "deleted", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, RuntimeError) as exc:
        return {"error": str(exc)}


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="place_component",
    description="Place a new component on the board within a session.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "footprint_library": {
            "type": "string",
            "description": "Library:Footprint identifier (e.g., 'Resistor_SMD:R_0402_1005Metric').",
        },
        "reference": {"type": "string", "description": "Reference designator (e.g., 'R1')."},
        "value": {"type": "string", "description": "Component value (e.g., '10k')."},
        "x": {"type": "number", "description": "X position in mm."},
        "y": {"type": "number", "description": "Y position in mm."},
        "layer": {
            "type": "string",
            "description": "Target layer ('F.Cu' or 'B.Cu'). Default: 'F.Cu'.",
        },
    },
    handler=_place_component_handler,
    category="placement",
)

register_tool(
    name="place_from_library",
    description="Place a component from a .kicad_mod footprint file.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "kicad_mod_path": {"type": "string", "description": "Path to .kicad_mod file."},
        "reference": {"type": "string", "description": "Reference designator (e.g., 'R1')."},
        "value": {"type": "string", "description": "Component value (e.g., '10k')."},
        "x": {"type": "number", "description": "X position in mm."},
        "y": {"type": "number", "description": "Y position in mm."},
        "layer": {
            "type": "string",
            "description": "Target layer ('F.Cu' or 'B.Cu'). Default: 'F.Cu'.",
        },
    },
    handler=_place_from_library_handler,
    category="placement",
)

register_tool(
    name="rotate_component",
    description="Rotate a component to a specified angle (degrees).",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "reference": {"type": "string", "description": "Component reference (e.g., 'R1')."},
        "angle": {"type": "number", "description": "Rotation angle in degrees (0-360)."},
    },
    handler=_rotate_component_handler,
    category="placement",
)

register_tool(
    name="flip_component",
    description="Flip a component to the opposite side of the board (F.Cu <-> B.Cu).",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "reference": {"type": "string", "description": "Component reference (e.g., 'R1')."},
    },
    handler=_flip_component_handler,
    category="placement",
)

register_tool(
    name="delete_component",
    description="Delete a component from the board.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "reference": {"type": "string", "description": "Component reference (e.g., 'R1')."},
    },
    handler=_delete_component_handler,
    category="placement",
)


# ── Edit / Replace / Group handlers ────────────────────────────────


def _edit_component_handler(
    session_id: str,
    reference: str,
    properties: dict[str, str],
) -> dict[str, Any]:
    """Edit properties of an existing component.

    Args:
        session_id: Active session ID.
        reference: Component reference designator (e.g., "R1").
        properties: Dict of property name to new value (e.g., {"Value": "22k"}).
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_edit_component(session, reference, properties)
        return {"status": "edited", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _replace_component_handler(
    session_id: str,
    reference: str,
    new_library: str,
    new_value: str,
) -> dict[str, Any]:
    """Replace a component with a different footprint, keeping its position.

    Args:
        session_id: Active session ID.
        reference: Reference designator of the component to replace.
        new_library: New library:footprint identifier.
        new_value: New component value.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_replace_component(session, reference, new_library, new_value)
        return {"status": "replaced", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except ValueError as exc:
        return {"error": str(exc)}


def _group_components_handler(
    session_id: str,
    references: list[str],
    group_name: str,
) -> dict[str, Any]:
    """Tag multiple components with a group label.

    Args:
        session_id: Active session ID.
        references: List of reference designators to group.
        group_name: Name for the group.
    """
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    grouped = []
    for ref in references:
        try:
            mgr.apply_edit_component(session, ref, {"Group": group_name})
            grouped.append(ref)
        except ValueError:
            pass

    return {
        "status": "grouped",
        "group_name": group_name,
        "grouped_count": len(grouped),
        "references": grouped,
    }


register_tool(
    name="edit_component",
    description="Edit properties of an existing component (Value, Footprint, etc.).",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "reference": {"type": "string", "description": "Component reference (e.g., 'R1')."},
        "properties": {
            "type": "object",
            "description": "Property name to new value dict (e.g., {'Value': '22k'}).",
        },
    },
    handler=_edit_component_handler,
    category="placement",
)

register_tool(
    name="replace_component",
    description="Replace a component with a different footprint, keeping position.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "reference": {"type": "string", "description": "Component reference (e.g., 'R1')."},
        "new_library": {
            "type": "string",
            "description": "New Library:Footprint identifier.",
        },
        "new_value": {"type": "string", "description": "New component value."},
    },
    handler=_replace_component_handler,
    category="placement",
)

register_tool(
    name="group_components",
    description="Tag multiple components with a group label.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "references": {
            "type": "array",
            "description": "List of reference designators to group.",
        },
        "group_name": {"type": "string", "description": "Group name."},
    },
    handler=_group_components_handler,
    category="placement",
)


# ── Convenience placement: duplicate / array / align ───────────────


def _duplicate_component_handler(
    session_id: str,
    reference: str,
    new_reference: str,
    x: float,
    y: float,
) -> dict[str, Any]:
    """Duplicate an existing component to a new reference at a new position.

    Args:
        session_id: Active session ID.
        reference: Reference designator of the component to copy (e.g., "R1").
        new_reference: Reference designator for the copy (e.g., "R2").
        x: X position in mm for the copy.
        y: Y position in mm for the copy.
    """
    ref_result = validate_reference(reference)
    if not ref_result.valid:
        return {"error": f"Invalid reference: {ref_result.error}"}

    new_ref_result = validate_reference(new_reference)
    if not new_ref_result.valid:
        return {"error": f"Invalid new_reference: {new_ref_result.error}"}

    coord_result = validate_coordinate_pair(x, y, ("x", "y"))
    if not coord_result.valid:
        return {"error": f"Invalid coordinates: {coord_result.error}"}

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_duplicate(session, reference, new_reference, x, y)
        return {"status": "duplicated", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, RuntimeError) as exc:
        return {"error": str(exc)}


def _place_component_array_handler(
    session_id: str,
    footprint_library: str,
    value: str,
    reference_prefix: str,
    start_number: int,
    columns: int,
    rows: int,
    start_x: float,
    start_y: float,
    spacing_x: float,
    spacing_y: float,
    layer: str = "F.Cu",
) -> dict[str, Any]:
    """Place a grid of identical components in a single operation.

    References are generated as ``{reference_prefix}{start_number + index}``,
    filling row by row. Each placement is an individually undoable change.

    Args:
        session_id: Active session ID.
        footprint_library: Library:Footprint identifier.
        value: Component value applied to every copy.
        reference_prefix: Reference letter prefix (e.g., "R").
        start_number: First reference number (e.g., 1 → R1).
        columns: Number of columns in the grid.
        rows: Number of rows in the grid.
        start_x: X position of the top-left component (mm).
        start_y: Y position of the top-left component (mm).
        spacing_x: Horizontal pitch between columns (mm).
        spacing_y: Vertical pitch between rows (mm).
        layer: Target layer. Defaults to "F.Cu".
    """
    if columns < 1 or rows < 1:
        return {"error": "columns and rows must each be >= 1"}
    if columns * rows > 1000:
        return {"error": "Array too large (max 1000 components)"}

    layer_result = validate_layer_name(layer)
    if not layer_result.valid:
        return {"error": f"Invalid layer: {layer_result.error}"}

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    placed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    index = 0
    for row in range(rows):
        for col in range(columns):
            ref = f"{reference_prefix}{start_number + index}"
            x = start_x + col * spacing_x
            y = start_y + row * spacing_y
            index += 1
            try:
                record = mgr.apply_place(session, footprint_library, ref, value, x, y, layer)
                placed.append(record.to_dict())
            except (ValueError, FileNotFoundError) as exc:
                errors.append({"reference": ref, "error": str(exc)})

    return {
        "status": "array_placed",
        "placed_count": len(placed),
        "changes": placed,
        "errors": errors,
    }


_ALIGN_MODES = (
    "left",
    "right",
    "top",
    "bottom",
    "center_x",
    "center_y",
    "distribute_x",
    "distribute_y",
)


def _align_components_handler(
    session_id: str,
    references: list[str],
    alignment: str,
) -> dict[str, Any]:
    """Align or distribute multiple components.

    Args:
        session_id: Active session ID.
        references: Reference designators to align (>= 2).
        alignment: One of left, right, top, bottom (edge align),
            center_x, center_y (align to group average), or
            distribute_x, distribute_y (even spacing between extremes).
    """
    if alignment not in _ALIGN_MODES:
        return {"error": f"Invalid alignment {alignment!r}. Valid: {', '.join(_ALIGN_MODES)}"}
    if len(references) < 2:
        return {"error": "Need at least 2 references to align"}

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    # Read current positions; skip references that don't exist.
    positions: dict[str, dict[str, float]] = {}
    missing: list[str] = []
    for ref in references:
        try:
            positions[ref] = mgr.read_position(session, ref)
        except (ValueError, RuntimeError):
            missing.append(ref)

    if len(positions) < 2:
        return {"error": "Fewer than 2 valid components found", "missing": missing}

    xs = [p["x"] for p in positions.values()]
    ys = [p["y"] for p in positions.values()]

    # Compute each component's target (x, y).
    targets: dict[str, tuple[float, float]] = {}
    if alignment in ("left", "right", "center_x"):
        tx = (
            min(xs)
            if alignment == "left"
            else max(xs)
            if alignment == "right"
            else sum(xs) / len(xs)
        )
        for ref, p in positions.items():
            targets[ref] = (tx, p["y"])
    elif alignment in ("top", "bottom", "center_y"):
        ty = (
            min(ys)
            if alignment == "top"
            else max(ys)
            if alignment == "bottom"
            else sum(ys) / len(ys)
        )
        for ref, p in positions.items():
            targets[ref] = (p["x"], ty)
    elif alignment == "distribute_x":
        ordered = sorted(positions.items(), key=lambda kv: kv[1]["x"])
        lo, hi = ordered[0][1]["x"], ordered[-1][1]["x"]
        step = (hi - lo) / (len(ordered) - 1)
        for i, (ref, p) in enumerate(ordered):
            targets[ref] = (lo + i * step, p["y"])
    else:  # distribute_y
        ordered = sorted(positions.items(), key=lambda kv: kv[1]["y"])
        lo, hi = ordered[0][1]["y"], ordered[-1][1]["y"]
        step = (hi - lo) / (len(ordered) - 1)
        for i, (ref, p) in enumerate(ordered):
            targets[ref] = (p["x"], lo + i * step)

    moved: list[dict[str, Any]] = []
    for ref, (tx, ty) in targets.items():
        cur = positions[ref]
        if abs(cur["x"] - tx) < 1e-6 and abs(cur["y"] - ty) < 1e-6:
            continue  # already in place
        try:
            record = mgr.apply_move(session, ref, tx, ty)
            moved.append(record.to_dict())
        except (ValueError, RuntimeError) as exc:
            missing.append(f"{ref}: {exc}")

    return {
        "status": "aligned",
        "alignment": alignment,
        "moved_count": len(moved),
        "changes": moved,
        "skipped": missing,
    }


register_tool(
    name="duplicate_component",
    description="Duplicate an existing component (with all pads/graphics) to a new reference.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "reference": {"type": "string", "description": "Component to copy (e.g., 'R1')."},
        "new_reference": {"type": "string", "description": "Reference for the copy (e.g., 'R2')."},
        "x": {"type": "number", "description": "X position for the copy (mm)."},
        "y": {"type": "number", "description": "Y position for the copy (mm)."},
    },
    handler=_duplicate_component_handler,
    category="placement",
)

register_tool(
    name="place_component_array",
    description="Place a grid (rows x columns) of identical components in one operation.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "footprint_library": {
            "type": "string",
            "description": "Library:Footprint identifier (e.g., 'Resistor_SMD:R_0402_1005Metric').",
        },
        "value": {"type": "string", "description": "Component value for every copy."},
        "reference_prefix": {"type": "string", "description": "Reference prefix (e.g., 'R')."},
        "start_number": {"type": "integer", "description": "First reference number (e.g., 1)."},
        "columns": {"type": "integer", "description": "Number of columns."},
        "rows": {"type": "integer", "description": "Number of rows."},
        "start_x": {"type": "number", "description": "X of top-left component (mm)."},
        "start_y": {"type": "number", "description": "Y of top-left component (mm)."},
        "spacing_x": {"type": "number", "description": "Horizontal pitch (mm)."},
        "spacing_y": {"type": "number", "description": "Vertical pitch (mm)."},
        "layer": {"type": "string", "description": "Target layer. Default: 'F.Cu'."},
    },
    handler=_place_component_array_handler,
    category="placement",
)

register_tool(
    name="align_components",
    description=(
        "Align or distribute components: left/right/top/bottom, center_x/center_y, "
        "or distribute_x/distribute_y."
    ),
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "references": {"type": "array", "description": "References to align (>= 2)."},
        "alignment": {
            "type": "string",
            "description": (
                "left, right, top, bottom, center_x, center_y, distribute_x, or distribute_y."
            ),
        },
    },
    handler=_align_components_handler,
    category="placement",
)
