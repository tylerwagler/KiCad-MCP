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
