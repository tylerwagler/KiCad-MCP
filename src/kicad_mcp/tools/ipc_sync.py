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

# Import IpcBackend for type annotations
# (lazy import in _get_ipc to avoid breaking when kipy is not installed)
from ..backends.ipc_api import IpcBackend
from .registry import register_tool


def _get_ipc() -> IpcBackend:
    """Get the singleton IpcBackend instance."""
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


def _push_single_change(ipc: IpcBackend, change: Any) -> None:
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


def _ipc_create_track_handler(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    width: float,
    layer: str,
    net_code: int = 0,
) -> dict[str, Any]:
    """Create a track segment in KiCad GUI.

    The track appears immediately in KiCad. This provides instant visual
    feedback without waiting for a session commit.

    Args:
        start_x: Start X coordinate in mm
        start_y: Start Y coordinate in mm
        end_x: End X coordinate in mm
        end_y: End Y coordinate in mm
        width: Track width in mm
        layer: Layer name (e.g., "F.Cu", "B.Cu")
        net_code: Net code (0 for no net)
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        uuid = ipc.create_track_segment(start_x, start_y, end_x, end_y, width, layer, net_code)
        return {
            "status": "created",
            "uuid": uuid,
            "type": "track",
            "start": {"x": start_x, "y": start_y},
            "end": {"x": end_x, "y": end_y},
            "width": width,
            "layer": layer,
        }
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_create_via_handler(
    x: float,
    y: float,
    size: float,
    drill: float,
    layer_start: str = "F.Cu",
    layer_end: str = "B.Cu",
    net_code: int = 0,
) -> dict[str, Any]:
    """Create a via in KiCad GUI.

    The via appears immediately in KiCad. This provides instant visual
    feedback without waiting for a session commit.

    Args:
        x: X coordinate in mm
        y: Y coordinate in mm
        size: Via size (diameter) in mm
        drill: Drill diameter in mm
        layer_start: Start layer (default: "F.Cu")
        layer_end: End layer (default: "B.Cu")
        net_code: Net code (0 for no net)
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        uuid = ipc.create_via(x, y, size, drill, (layer_start, layer_end), net_code)
        return {
            "status": "created",
            "uuid": uuid,
            "type": "via",
            "position": {"x": x, "y": y},
            "size": size,
            "drill": drill,
            "layers": {"start": layer_start, "end": layer_end},
        }
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_create_zone_handler(
    net_code: int,
    layer: str,
    outline_points: str,
    priority: int = 0,
    min_thickness: float = 0.25,
) -> dict[str, Any]:
    """Create a copper zone in KiCad GUI.

    The zone appears immediately in KiCad. This provides instant visual
    feedback without waiting for a session commit.

    Args:
        net_code: Net code for the zone
        layer: Layer name (e.g., "F.Cu", "B.Cu")
        outline_points: JSON array of [x, y] coordinate pairs defining the zone boundary
        priority: Zone priority (higher fills first, default: 0)
        min_thickness: Minimum copper thickness in mm (default: 0.25)
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    # Parse outline_points from JSON string
    import json

    try:
        points_list = json.loads(outline_points)
        points = [(pt[0], pt[1]) for pt in points_list]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        return {"error": f"Invalid outline_points format: {exc}"}

    ipc = _get_ipc()
    try:
        uuid = ipc.create_zone(net_code, layer, points, priority, min_thickness)
        return {
            "status": "created",
            "uuid": uuid,
            "type": "zone",
            "net_code": net_code,
            "layer": layer,
            "outline_points": points,
            "priority": priority,
        }
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_refill_zones_handler() -> dict[str, Any]:
    """Trigger zone refill in KiCad.

    Updates all copper pours. Should be called after adding/modifying
    tracks or vias to ensure zone fills are current for DRC checks.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        ipc.refill_zones()
        return {"status": "refilled", "message": "Zone fills updated"}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


# ── Metadata handlers ────────────────────────────────────────────


def _ipc_get_stackup_handler() -> dict[str, Any]:
    """Get board layer stackup information.

    Returns layer count and stackup details.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        return ipc.get_board_stackup()
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_get_net_classes_handler() -> dict[str, Any]:
    """Get net class definitions from the board.

    Returns clearance, width, via settings for each net class.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        net_classes = ipc.get_net_classes()
        return {"net_classes": net_classes, "count": len(net_classes)}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_get_title_block_handler() -> dict[str, Any]:
    """Get title block fields from the board.

    Returns title, revision, date, company, and comments.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        return ipc.get_title_block_info()
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_get_text_vars_handler() -> dict[str, Any]:
    """Get project text variables.

    Returns variables like ${REVISION}, ${DATE}, etc.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        variables = ipc.get_text_variables()
        return {"variables": variables, "count": len(variables)}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_set_text_vars_handler(variables: str) -> dict[str, Any]:
    """Set project text variables.

    Args:
        variables: JSON object mapping variable names to values
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    # Parse variables from JSON string
    import json

    try:
        vars_dict = json.loads(variables)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid variables format: {exc}"}

    ipc = _get_ipc()
    try:
        ipc.set_text_variables(vars_dict)
        return {"status": "updated", "count": len(vars_dict)}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


# ── Board operation handlers ─────────────────────────────────────


def _ipc_save_board_handler() -> dict[str, Any]:
    """Save board via IPC.

    Saves the board without needing kicad-cli.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        ipc.save_board()
        return {"status": "saved", "message": "Board saved successfully"}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_revert_board_handler() -> dict[str, Any]:
    """Revert board to last saved state.

    Discards all unsaved changes in KiCad GUI.
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        ipc.revert_board()
        return {"status": "reverted", "message": "Board reverted to last saved state"}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


# ── GUI control handlers ─────────────────────────────────────────


def _ipc_get_active_layer_handler() -> dict[str, Any]:
    """Get currently active layer in KiCad GUI.

    Returns the layer name (e.g., 'F.Cu', 'B.Cu').
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        layer = ipc.get_active_layer()
        return {"layer": layer}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_set_active_layer_handler(layer: str) -> dict[str, Any]:
    """Set active layer in KiCad GUI.

    Args:
        layer: Layer name (e.g., 'F.Cu', 'B.Cu')
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    ipc = _get_ipc()
    try:
        ipc.set_active_layer(layer)
        return {"status": "updated", "layer": layer}
    except (IpcNotAvailable, IpcError) as exc:
        return _ipc_error_response(exc)


def _ipc_set_visible_layers_handler(layers: str) -> dict[str, Any]:
    """Control layer visibility in KiCad GUI.

    Args:
        layers: JSON array of layer names to make visible
    """
    from ..backends.ipc_api import IpcError, IpcNotAvailable

    err = _ensure_connected()
    if err:
        return err

    # Parse layers from JSON string
    import json

    try:
        layers_list = json.loads(layers)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid layers format: {exc}"}

    ipc = _get_ipc()
    try:
        ipc.set_visible_layers(layers_list)
        return {"status": "updated", "count": len(layers_list)}
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

register_tool(
    name="ipc_create_track",
    description=(
        "Create a track segment in KiCad GUI. "
        "The track appears immediately without waiting for session commit."
    ),
    parameters={
        "start_x": {"type": "number", "description": "Start X coordinate in mm"},
        "start_y": {"type": "number", "description": "Start Y coordinate in mm"},
        "end_x": {"type": "number", "description": "End X coordinate in mm"},
        "end_y": {"type": "number", "description": "End Y coordinate in mm"},
        "width": {"type": "number", "description": "Track width in mm"},
        "layer": {"type": "string", "description": "Layer name (e.g., 'F.Cu', 'B.Cu')"},
        "net_code": {"type": "integer", "description": "Net code (0 for no net)", "default": 0},
    },
    handler=_ipc_create_track_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_create_via",
    description=(
        "Create a via in KiCad GUI. The via appears immediately without waiting for session commit."
    ),
    parameters={
        "x": {"type": "number", "description": "X coordinate in mm"},
        "y": {"type": "number", "description": "Y coordinate in mm"},
        "size": {"type": "number", "description": "Via size (diameter) in mm"},
        "drill": {"type": "number", "description": "Drill diameter in mm"},
        "layer_start": {
            "type": "string",
            "description": "Start layer",
            "default": "F.Cu",
        },
        "layer_end": {
            "type": "string",
            "description": "End layer",
            "default": "B.Cu",
        },
        "net_code": {"type": "integer", "description": "Net code (0 for no net)", "default": 0},
    },
    handler=_ipc_create_via_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_create_zone",
    description=(
        "Create a copper zone in KiCad GUI. "
        "The zone appears immediately without waiting for session commit."
    ),
    parameters={
        "net_code": {"type": "integer", "description": "Net code for the zone"},
        "layer": {"type": "string", "description": "Layer name (e.g., 'F.Cu', 'B.Cu')"},
        "outline_points": {
            "type": "string",
            "description": "JSON array of [x, y] coordinate pairs defining zone boundary",
        },
        "priority": {
            "type": "integer",
            "description": "Zone priority (higher fills first)",
            "default": 0,
        },
        "min_thickness": {
            "type": "number",
            "description": "Minimum copper thickness in mm",
            "default": 0.25,
        },
    },
    handler=_ipc_create_zone_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_refill_zones",
    description=(
        "Trigger zone refill in KiCad. "
        "Updates all copper pours after adding/modifying tracks or vias."
    ),
    parameters={},
    handler=_ipc_refill_zones_handler,
    category="ipc_sync",
)

# ── Metadata tools ───────────────────────────────────────────────

register_tool(
    name="ipc_get_stackup",
    description="Get board layer stackup information (layer count, names, types, thickness).",
    parameters={},
    handler=_ipc_get_stackup_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_get_net_classes",
    description=(
        "Get net class definitions from the board. "
        "Returns clearance, width, via settings for each net class."
    ),
    parameters={},
    handler=_ipc_get_net_classes_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_get_title_block",
    description="Get title block fields (title, revision, date, company, comments).",
    parameters={},
    handler=_ipc_get_title_block_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_get_text_vars",
    description="Get project text variables like ${REVISION}, ${DATE}.",
    parameters={},
    handler=_ipc_get_text_vars_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_set_text_vars",
    description="Set project text variables.",
    parameters={
        "variables": {
            "type": "string",
            "description": "JSON object mapping variable names to values",
        },
    },
    handler=_ipc_set_text_vars_handler,
    category="ipc_sync",
)

# ── Board operation tools ────────────────────────────────────────

register_tool(
    name="ipc_save_board",
    description="Save board via IPC without needing kicad-cli.",
    parameters={},
    handler=_ipc_save_board_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_revert_board",
    description="Revert board to last saved state. Discards all unsaved changes in KiCad GUI.",
    parameters={},
    handler=_ipc_revert_board_handler,
    category="ipc_sync",
)

# ── GUI control tools ────────────────────────────────────────────

register_tool(
    name="ipc_get_active_layer",
    description="Get currently active layer in KiCad GUI.",
    parameters={},
    handler=_ipc_get_active_layer_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_set_active_layer",
    description="Set active layer in KiCad GUI.",
    parameters={
        "layer": {
            "type": "string",
            "description": "Layer name (e.g., 'F.Cu', 'B.Cu')",
        },
    },
    handler=_ipc_set_active_layer_handler,
    category="ipc_sync",
)

register_tool(
    name="ipc_set_visible_layers",
    description="Control layer visibility in KiCad GUI.",
    parameters={
        "layers": {
            "type": "string",
            "description": "JSON array of layer names to make visible",
        },
    },
    handler=_ipc_set_visible_layers_handler,
    category="ipc_sync",
)
