"""Placement tools — component placement, rotation, flip, deletion."""

from __future__ import annotations

from typing import Any

from .registry import register_tool

# Reuse the module-level session manager from mutation.py
_session_manager = None


def _get_manager():
    global _session_manager
    if _session_manager is None:
        from ..session import SessionManager

        _session_manager = SessionManager()
    return _session_manager


def _get_session(session_id: str):
    from .mutation import _get_manager as _get_mutation_manager

    return _get_mutation_manager().get_session(session_id)


def _get_mgr():
    """Get the mutation module's session manager (shared singleton)."""
    from .mutation import _get_manager as _get_mutation_manager

    return _get_mutation_manager()


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
    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
        record = mgr.place_from_kicad_mod(
            session, kicad_mod_path, reference, value, x, y, layer
        )
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
            mgr.apply_edit_component(
                session, ref, {"Group": group_name}
            )
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
