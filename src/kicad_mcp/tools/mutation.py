"""Mutation tools — session-based board modifications with undo/rollback."""

from __future__ import annotations

from typing import Any

from .registry import register_tool

# Module-level session manager instance
_session_manager = None


def _get_manager():
    global _session_manager
    if _session_manager is None:
        from ..session import SessionManager

        _session_manager = SessionManager()
    return _session_manager


def _start_session_handler() -> dict[str, Any]:
    """Start a new mutation session for the currently loaded board.

    A session allows you to preview, apply, undo, and commit/rollback changes.
    """
    from .. import state

    doc = state.get_document()
    mgr = _get_manager()
    session = mgr.start_session(doc)
    return {
        "status": "session_started",
        "session_id": session.session_id,
        "board_path": session.board_path,
    }


def _commit_session_handler(session_id: str) -> dict[str, Any]:
    """Commit all applied changes in a session to disk.

    Args:
        session_id: The session ID returned by start_session.
    """
    mgr = _get_manager()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    return mgr.commit(session)


def _rollback_session_handler(session_id: str) -> dict[str, Any]:
    """Rollback all changes in a session, discarding modifications.

    Args:
        session_id: The session ID.
    """
    mgr = _get_manager()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    return mgr.rollback(session)


def _query_move_handler(session_id: str, reference: str, x: float, y: float) -> dict[str, Any]:
    """Preview moving a component without applying the change.

    Args:
        session_id: Active session ID.
        reference: Component reference designator (e.g., 'R1').
        x: New X coordinate (mm).
        y: New Y coordinate (mm).
    """
    mgr = _get_manager()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    return mgr.query_move(session, reference, x, y)


def _apply_move_handler(session_id: str, reference: str, x: float, y: float) -> dict[str, Any]:
    """Apply a component move within a session.

    Args:
        session_id: Active session ID.
        reference: Component reference designator.
        x: New X coordinate (mm).
        y: New Y coordinate (mm).
    """
    mgr = _get_manager()
    try:
        session = mgr.get_session(session_id)
        record = mgr.apply_move(session, reference, x, y)
        return {
            "status": "applied",
            "change": record.to_dict(),
        }
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}


def _undo_change_handler(session_id: str) -> dict[str, Any]:
    """Undo the last applied change in a session.

    Args:
        session_id: Active session ID.
    """
    mgr = _get_manager()
    try:
        session = mgr.get_session(session_id)
        record = mgr.undo(session)
        if record is None:
            return {"status": "nothing_to_undo"}
        return {"status": "undone", "change": record.to_dict()}
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    except RuntimeError as e:
        return {"error": str(e)}


def _get_session_status_handler(session_id: str) -> dict[str, Any]:
    """Get the current status of a session including all changes.

    Args:
        session_id: Session ID.
    """
    mgr = _get_manager()
    try:
        session = mgr.get_session(session_id)
        return session.to_dict()
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}


# Direct tools (always visible)
register_tool(
    name="start_session",
    description=(
        "Start a new mutation session for the loaded board. Required before making changes."
    ),
    parameters={},
    handler=_start_session_handler,
    category="session",
    direct=True,
)

register_tool(
    name="commit_session",
    description="Commit all applied changes in a session to disk.",
    parameters={"session_id": {"type": "string", "description": "Session ID from start_session."}},
    handler=_commit_session_handler,
    category="session",
    direct=True,
)

# Routed tools
register_tool(
    name="rollback_session",
    description="Rollback all changes in a session, discarding all modifications.",
    parameters={"session_id": {"type": "string", "description": "Session ID."}},
    handler=_rollback_session_handler,
    category="session",
)

register_tool(
    name="query_move",
    description="Preview moving a component without applying (dry-run).",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "reference": {"type": "string", "description": "Component reference (e.g., 'R1')."},
        "x": {"type": "number", "description": "New X coordinate (mm)."},
        "y": {"type": "number", "description": "New Y coordinate (mm)."},
    },
    handler=_query_move_handler,
    category="session",
)

register_tool(
    name="apply_move",
    description="Move a component to a new position within a session.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "reference": {"type": "string", "description": "Component reference (e.g., 'R1')."},
        "x": {"type": "number", "description": "New X coordinate (mm)."},
        "y": {"type": "number", "description": "New Y coordinate (mm)."},
    },
    handler=_apply_move_handler,
    category="session",
)

register_tool(
    name="undo_change",
    description="Undo the last applied change in a session.",
    parameters={"session_id": {"type": "string", "description": "Active session ID."}},
    handler=_undo_change_handler,
    category="session",
)

register_tool(
    name="get_session_status",
    description="Get the current status and change history of a session.",
    parameters={"session_id": {"type": "string", "description": "Session ID."}},
    handler=_get_session_status_handler,
    category="session",
)
