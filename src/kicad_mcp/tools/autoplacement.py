"""Auto-placement tools — force-directed optimization, evaluation, spreading."""

from __future__ import annotations

from typing import Any

from ..session.manager import SessionManager
from .registry import register_tool


def _get_mgr() -> SessionManager:
    from .mutation import _get_manager

    return _get_manager()


# ── Handlers ────────────────────────────────────────────────────────


def _optimize_placement_handler(
    session_id: str,
    locked_references: list[str] | None = None,
    max_iterations: int = 500,
    min_clearance: float = 0.5,
    apply: bool = False,
) -> dict[str, Any]:
    """Optimize component placement using force-directed algorithm.

    Args:
        session_id: Active session ID.
        locked_references: Components to keep fixed (e.g., connectors).
        max_iterations: Maximum solver iterations. Default: 500.
        min_clearance: Minimum clearance between components (mm). Default: 0.5.
        apply: If True, apply moves to session. Default: False (preview).
    """
    from ..algorithms.placement import force_directed_placement
    from ..schema.extract import extract_board_outline, extract_footprints

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    assert session._working_doc is not None
    doc = session._working_doc

    footprints = extract_footprints(doc)
    board_bbox = extract_board_outline(doc)

    if board_bbox is None:
        return {"error": "No board outline (Edge.Cuts) found"}

    if not footprints:
        return {"error": "No components found on the board"}

    result = force_directed_placement(
        footprints=footprints,
        board_bbox=board_bbox,
        locked_references=locked_references,
        max_iterations=max_iterations,
        min_clearance=min_clearance,
    )

    if apply and result.movements:
        changes = 0
        for move in result.movements:
            try:
                mgr.apply_move(session, move["reference"], move["to_x"], move["to_y"])
                changes += 1
            except (ValueError, RuntimeError):
                pass
        return {
            "status": "applied",
            "result": result.to_dict(),
            "changes_applied": changes,
        }

    return {"status": "preview", "result": result.to_dict()}


def _evaluate_placement_handler(
    session_id: str,
    min_clearance: float = 0.5,
) -> dict[str, Any]:
    """Evaluate current placement quality (read-only).

    Args:
        session_id: Active session ID.
        min_clearance: Clearance for overlap detection (mm). Default: 0.5.
    """
    from ..algorithms.placement import evaluate_placement
    from ..schema.extract import extract_board_outline, extract_footprints

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    assert session._working_doc is not None
    doc = session._working_doc

    footprints = extract_footprints(doc)
    board_bbox = extract_board_outline(doc)

    if board_bbox is None:
        return {"error": "No board outline (Edge.Cuts) found"}

    evaluation = evaluate_placement(
        footprints=footprints,
        board_bbox=board_bbox,
        min_clearance=min_clearance,
    )

    return {"status": "evaluated", "result": evaluation.to_dict()}


def _spread_components_handler(
    session_id: str,
    min_clearance: float = 0.5,
    apply: bool = False,
) -> dict[str, Any]:
    """Quick overlap resolution — pushes overlapping components apart.

    Args:
        session_id: Active session ID.
        min_clearance: Minimum clearance between components (mm). Default: 0.5.
        apply: If True, apply moves to session. Default: False (preview).
    """
    from ..algorithms.placement import spread_components
    from ..schema.extract import extract_board_outline, extract_footprints

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    assert session._working_doc is not None
    doc = session._working_doc

    footprints = extract_footprints(doc)
    board_bbox = extract_board_outline(doc)

    if board_bbox is None:
        return {"error": "No board outline (Edge.Cuts) found"}

    if not footprints:
        return {"error": "No components found on the board"}

    result = spread_components(
        footprints=footprints,
        board_bbox=board_bbox,
        min_clearance=min_clearance,
    )

    if apply and result.movements:
        changes = 0
        for move in result.movements:
            try:
                mgr.apply_move(session, move["reference"], move["to_x"], move["to_y"])
                changes += 1
            except (ValueError, RuntimeError):
                pass
        return {
            "status": "applied",
            "result": result.to_dict(),
            "changes_applied": changes,
        }

    return {"status": "preview", "result": result.to_dict()}


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="optimize_placement",
    description=(
        "Optimize component placement using force-directed algorithm with simulated annealing."
    ),
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "locked_references": {
            "type": "array",
            "description": "Component references to keep fixed.",
        },
        "max_iterations": {
            "type": "integer",
            "description": "Max solver iterations. Default: 500.",
        },
        "min_clearance": {
            "type": "number",
            "description": "Min clearance between components (mm). Default: 0.5.",
        },
        "apply": {
            "type": "boolean",
            "description": "Apply to session. Default: false.",
        },
    },
    handler=_optimize_placement_handler,
    category="autoplacement",
)

register_tool(
    name="evaluate_placement",
    description="Evaluate current placement quality: HPWL, overlaps, density, per-net wirelength.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "min_clearance": {
            "type": "number",
            "description": "Clearance for overlap detection (mm). Default: 0.5.",
        },
    },
    handler=_evaluate_placement_handler,
    category="autoplacement",
)

register_tool(
    name="spread_components",
    description=(
        "Quick overlap resolution — push overlapping components apart using repulsive forces."
    ),
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "min_clearance": {
            "type": "number",
            "description": "Min clearance (mm). Default: 0.5.",
        },
        "apply": {
            "type": "boolean",
            "description": "Apply to session. Default: false.",
        },
    },
    handler=_spread_components_handler,
    category="autoplacement",
)
