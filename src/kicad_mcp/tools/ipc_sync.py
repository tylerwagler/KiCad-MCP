"""IPC sync tools — real-time KiCad UI interaction via IPC API.

Provides tools for connecting to KiCad, highlighting components,
reading GUI selection, pushing session changes live, and refreshing
board state from KiCad.

All tools gracefully degrade when kipy is not installed or KiCad
is not running.
"""

from __future__ import annotations

import contextlib
from typing import Any

from .registry import register_tool


def _get_ipc():
    from ..backends.ipc_api import IpcBackend

    return IpcBackend.get()


def _ipc_error_response(exc: Exception) -> dict[str, Any]:
    """Build a standard error response for IPC failures."""
    return {
        "error": str(exc),
        "hint": "Ensure KiCad 9+ is running with IPC enabled, and kipy is installed "
        "(pip install kicad-python).",
    }


def _ensure_connected() -> dict[str, Any] | None:
    """Auto-connect to IPC. Returns an error dict if connection fails, else None."""
    from ..backends.ipc_api import IpcNotAvailable

    ipc = _get_ipc()
    if not ipc.is_connected() and not ipc.connect():
        return _ipc_error_response(IpcNotAvailable("Not connected to KiCad IPC API"))
    return None


# ── Handlers ────────────────────────────────────────────────────────


def _ipc_connect_handler(socket_path: str = "") -> dict[str, Any]:
    """Connect to KiCad's IPC API for live UI sync.

    Args:
        socket_path: Optional socket/pipe path. Auto-detects if empty.
    """
    from ..backends.ipc_api import _KIPY_AVAILABLE

    if not _KIPY_AVAILABLE:
        return {
            "connected": False,
            "message": "kipy (kicad-python) is not installed. "
            "Install with: pip install kicad-python",
        }

    ipc = _get_ipc()
    path = socket_path if socket_path else None
    success = ipc.connect(path)

    if success:
        return {
            "connected": True,
            "message": "Connected to KiCad IPC API",
        }
    return {
        "connected": False,
        "message": "Could not connect to KiCad. Ensure KiCad 9+ is running with IPC enabled.",
    }


def _ipc_highlight_handler(references: str) -> dict[str, Any]:
    """Highlight components in KiCad GUI so the user can see them.

    Args:
        references: Comma-separated reference designators (e.g., "R1,R2,C3").
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    ref_list = [r.strip() for r in references.split(",") if r.strip()]
    if not ref_list:
        return {"error": "No references provided"}

    try:
        ipc.highlight_items(ref_list)
        return {"highlighted": ref_list}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_get_selection_handler() -> dict[str, Any]:
    """Read what the user has selected in KiCad GUI.

    Enables "work on what I've selected" workflows.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        items = ipc.get_selected()
        references = [item["reference"] for item in items if "reference" in item]
        return {
            "references": references,
            "count": len(references),
            "items": items,
        }
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_push_changes_handler(session_id: str) -> dict[str, Any]:
    """Push pending session changes to KiCad GUI without writing to disk.

    Changes appear live in KiCad. This is separate from commit_session
    which writes to file.

    Args:
        session_id: Session ID from start_session.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()

    from .mutation import _get_manager

    mgr = _get_manager()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    pushed = 0
    operations: list[dict[str, Any]] = []
    errors: list[str] = []

    for change in session.changes:
        if not change.applied:
            continue
        try:
            _push_single_change(ipc, change)
            pushed += 1
            operations.append(change.to_dict())
        except (IpcNotAvailable, IpcError) as exc:
            errors.append(f"{change.operation} on {change.target}: {exc}")

    if pushed > 0:
        with contextlib.suppress(IpcNotAvailable, IpcError):
            ipc.commit_to_undo()

    result: dict[str, Any] = {
        "pushed": pushed,
        "operations": operations,
        "message": f"Pushed {pushed} change(s) to KiCad GUI",
    }
    if errors:
        result["errors"] = errors
    return result


def _push_single_change(ipc: Any, change: Any) -> None:
    """Push a single ChangeRecord to KiCad via IPC."""
    op = change.operation
    if op == "move_component":
        # Parse target position from after_snapshot: (at X Y ...)
        x, y = _parse_at_from_snapshot(change.after_snapshot)
        if x is not None and y is not None:
            ipc.move_footprint(change.target, x, y)
    elif op == "rotate_component":
        # Parse angle from after_snapshot
        parts = change.after_snapshot.strip("()").split()
        if len(parts) >= 4:
            try:
                angle = float(parts[3])
                ipc.rotate_footprint(change.target, angle)
            except (ValueError, IndexError):
                pass
    elif op == "delete_component":
        ipc.delete_footprint(change.target)
    # place_component, create_zone, route_trace, etc. don't have
    # simple IPC equivalents yet — the file commit handles those.


def _parse_at_from_snapshot(snapshot: str) -> tuple[float | None, float | None]:
    """Extract x, y from an (at X Y ...) S-expression string."""
    # Simple parse: "(at 20.0 10.0)" or "(at 20.0 10.0 90)"
    stripped = snapshot.strip()
    if stripped.startswith("(at "):
        parts = stripped[1:-1].split()  # ["at", "20.0", "10.0", ...]
        if len(parts) >= 3:
            try:
                return float(parts[1]), float(parts[2])
            except ValueError:
                pass
    return None, None


def _ipc_refresh_board_handler() -> dict[str, Any]:
    """Re-read board state from KiCad, picking up manual GUI edits.

    Updates the in-memory state so subsequent tool calls reflect
    what KiCad currently shows.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        state = ipc.get_board_state()
        return {
            "status": "refreshed",
            "components": state.get("footprint_count", 0),
            "nets": state.get("net_count", 0),
        }
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_get_tracks_handler() -> dict[str, Any]:
    """Read all trace segments from the live KiCad board.

    Returns track start/end points, width, layer, and net information.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        tracks = ipc.get_tracks()
        return {"tracks": tracks, "count": len(tracks)}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_get_vias_handler() -> dict[str, Any]:
    """Read all vias from the live KiCad board.

    Returns via position, size, drill, layer span, and net information.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        vias = ipc.get_vias()
        return {"vias": vias, "count": len(vias)}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_get_zones_handler() -> dict[str, Any]:
    """Read all copper zones from the live KiCad board.

    Returns zone net, layer, fill status, priority, and outline.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        zones = ipc.get_zones()
        return {"zones": zones, "count": len(zones)}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_ping_handler() -> dict[str, Any]:
    """Verify connection to KiCad is alive.

    This actively checks the socket, not just the internal connection flag.
    Useful for detecting if KiCad closed or the socket dropped.
    """
    ipc = _get_ipc()
    if not ipc.is_connected():
        return {"alive": False, "message": "Not connected to KiCad"}

    alive = ipc.ping()
    if alive:
        return {"alive": True, "message": "Connection to KiCad is active"}
    return {"alive": False, "message": "Connection to KiCad dropped"}


def _ipc_get_version_handler() -> dict[str, Any]:
    """Get KiCad version information from the running instance.

    Returns version string and parsed major/minor/patch numbers.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        version_info = ipc.get_kicad_version()
        return version_info
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


# ── Tool Registration ───────────────────────────────────────────────

register_tool(
    name="ipc_connect",
    description=(
        "Connect to KiCad's IPC API for real-time UI sync (KiCad 9+ required). "
        "Auto-detects socket path. Optional — tools auto-connect on first use."
    ),
    parameters={
        "socket_path": {
            "type": "string",
            "description": "Optional socket/pipe path. Auto-detects if empty.",
            "default": "",
        },
    },
    handler=_ipc_connect_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_highlight",
    description=(
        "Highlight components in KiCad GUI so the user can see which parts the AI is referring to."
    ),
    parameters={
        "references": {
            "type": "string",
            "description": "Comma-separated reference designators (e.g., 'R1,R2,C3').",
        },
    },
    handler=_ipc_highlight_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_get_selection",
    description=(
        "Read what the user has selected in KiCad GUI. "
        "Enables 'work on what I've selected' workflows."
    ),
    parameters={},
    handler=_ipc_get_selection_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_push_changes",
    description=(
        "Push pending session changes to KiCad GUI without writing to disk. "
        "Changes appear live. Separate from commit_session which writes to file."
    ),
    parameters={
        "session_id": {
            "type": "string",
            "description": "Session ID from start_session.",
        },
    },
    handler=_ipc_push_changes_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_refresh_board",
    description=(
        "Re-read board state from KiCad, picking up manual GUI edits. "
        "Updates in-memory state so subsequent tool calls reflect what KiCad shows."
    ),
    parameters={},
    handler=_ipc_refresh_board_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_get_tracks",
    description=(
        "Read all trace segments from the live KiCad board. "
        "Returns track start/end points, width, layer, and net information."
    ),
    parameters={},
    handler=_ipc_get_tracks_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_get_vias",
    description=(
        "Read all vias from the live KiCad board. "
        "Returns via position, size, drill, layer span, and net information."
    ),
    parameters={},
    handler=_ipc_get_vias_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_get_zones",
    description=(
        "Read all copper zones from the live KiCad board. "
        "Returns zone net, layer, fill status, priority, and outline."
    ),
    parameters={},
    handler=_ipc_get_zones_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_ping",
    description=(
        "Verify connection to KiCad is alive. "
        "Actively checks the socket, not just the internal connection flag. "
        "Useful for detecting if KiCad closed or the socket dropped."
    ),
    parameters={},
    handler=_ipc_ping_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_get_version",
    description=(
        "Get KiCad version information from the running instance. "
        "Returns version string and parsed major/minor/patch numbers."
    ),
    parameters={},
    handler=_ipc_get_version_handler,
    category="ipc_sync",
)
