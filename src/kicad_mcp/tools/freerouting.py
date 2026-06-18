"""Freerouting autorouter tools — DSN export, SES import, and full autoroute.

Pipeline: board → Specctra DSN → Freerouting (headless) → SES → apply traces/vias
into the active session (undoable like any other mutation).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ..session.manager import Session, SessionManager
from .registry import register_tool


def _get_mgr() -> SessionManager:
    from .mutation import _get_manager

    return _get_manager()


def _known_positions(doc: Any) -> dict[str, tuple[float, float]]:
    from ..schema.extract import extract_footprints

    return {fp.reference: (fp.position.x, fp.position.y) for fp in extract_footprints(doc)}


def _net_numbers(doc: Any) -> dict[str, int]:
    from ..schema.extract import extract_nets

    return {n.name: n.number for n in extract_nets(doc) if n.name}


def _live_outline_points() -> list[tuple[float, float]] | None:
    """Real board outline from a connected KiCad, or None (DSN then uses the file)."""
    from ..backends.ipc_api import IpcBackend

    ipc = IpcBackend.get()
    if not ipc.is_connected():
        return None
    from .. import board_provider

    return board_provider.live_outline_points(ipc)


# ── check_freerouting ──────────────────────────────────────────────


def _check_freerouting_handler() -> dict[str, Any]:
    """Report whether a Freerouting runtime is available and how to install one."""
    from ..backends import freerouting

    return freerouting.runtime_info()


# ── export_dsn ─────────────────────────────────────────────────────


def _export_dsn_handler(
    output_path: str,
    session_id: str | None = None,
    trace_width: float = 0.25,
    clearance: float = 0.2,
    via_diameter: float = 0.8,
    via_drill: float = 0.4,
) -> dict[str, Any]:
    """Export the board to a Specctra DSN file (Freerouting input).

    Args:
        output_path: Path for the .dsn file.
        session_id: Active session to export from. Falls back to the loaded board.
        trace_width: Default trace width (mm) written into the design rules.
        clearance: Default clearance (mm).
        via_diameter: Default via pad diameter (mm).
        via_drill: Default via drill diameter (mm).
    """
    from ..security import SecurityError, get_validator
    from ..specctra import DsnExportError, DsnOptions, board_to_dsn

    try:
        get_validator().validate_output(output_path)
    except SecurityError as exc:
        return {"error": f"Security error: {exc}"}

    doc = _resolve_doc(session_id)
    if isinstance(doc, dict):
        return doc  # error dict

    opts = DsnOptions(
        trace_width=trace_width,
        clearance=clearance,
        via_diameter=via_diameter,
        via_drill=via_drill,
    )
    try:
        dsn = board_to_dsn(
            doc, opts, name=Path(output_path).stem, outline_points=_live_outline_points()
        )
    except DsnExportError as exc:
        return {"error": str(exc)}

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(dsn, encoding="utf-8")
    return {"status": "exported", "dsn_path": output_path, "bytes": len(dsn)}


def _resolve_doc(session_id: str | None) -> Any:
    """Return the working doc for a session, or the loaded board; else an error dict."""
    if session_id:
        mgr = _get_mgr()
        try:
            session = mgr.get_session(session_id)
        except KeyError:
            return {"error": f"Session {session_id!r} not found"}
        if session._working_doc is None:
            return {"error": "Session has no working document"}
        return session._working_doc

    from .. import state

    if not state.is_loaded():
        return {"error": "No board loaded. Use open_project or pass a session_id."}
    return state.get_document()


# ── import_ses ─────────────────────────────────────────────────────


def _import_ses_handler(session_id: str, ses_path: str) -> dict[str, Any]:
    """Import a Specctra SES file and apply its routes to the session.

    Args:
        session_id: Active session to apply routes into.
        ses_path: Path to the .ses file produced by Freerouting.
    """
    from ..security import SecurityError, get_validator

    try:
        get_validator().validate_import(ses_path)
    except SecurityError as exc:
        return {"error": f"Security error: {exc}"}

    if not Path(ses_path).is_file():
        return {"error": f"SES file not found: {ses_path}"}

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    text = Path(ses_path).read_text(encoding="utf-8")
    return _apply_ses_text(mgr, session, text)


def _apply_ses_text(mgr: SessionManager, session: Session, text: str) -> dict[str, Any]:
    """Calibrate, parse, and apply SES geometry into the session."""
    from ..specctra import SesParseError, infer_units_per_mm, parse_ses

    assert session._working_doc is not None
    doc = session._working_doc

    known = _known_positions(doc)
    net_numbers = _net_numbers(doc)

    try:
        scale = infer_units_per_mm(text, known)
        route = parse_ses(text, units_per_mm=scale)
    except SesParseError as exc:
        return {"error": str(exc)}

    trace_changes = 0
    via_changes = 0
    skipped_nets: set[str] = set()

    for wire in route.wires:
        net_no = net_numbers.get(wire.net_name)
        if net_no is None:
            skipped_nets.add(wire.net_name)
            continue
        for i in range(1, len(wire.points)):
            x1, y1 = wire.points[i - 1]
            x2, y2 = wire.points[i]
            mgr.apply_route_trace(session, x1, y1, x2, y2, wire.width, wire.layer, net_no)
            trace_changes += 1

    for via in route.vias:
        net_no = net_numbers.get(via.net_name)
        if net_no is None:
            skipped_nets.add(via.net_name)
            continue
        mgr.apply_add_via(session, via.x, via.y, net_no)
        via_changes += 1

    return {
        "status": "imported",
        "calibrated_units_per_mm": scale,
        "traces_added": trace_changes,
        "vias_added": via_changes,
        "skipped_nets": sorted(skipped_nets),
    }


# ── autoroute_freerouting ──────────────────────────────────────────


def _autoroute_freerouting_handler(
    session_id: str,
    trace_width: float = 0.25,
    clearance: float = 0.2,
    via_diameter: float = 0.8,
    via_drill: float = 0.4,
    max_passes: int = 10,
    threads: int = 1,
    timeout: int = 300,
    apply: bool = False,
) -> dict[str, Any]:
    """Autoroute the board with Freerouting and optionally apply the result.

    Generates a DSN from the session, runs Freerouting headless, parses the SES,
    and (if ``apply``) inserts the routed traces/vias into the session.

    Args:
        session_id: Active session ID.
        trace_width: Default trace width (mm).
        clearance: Default clearance (mm).
        via_diameter: Default via pad diameter (mm).
        via_drill: Default via drill diameter (mm).
        max_passes: Freerouting optimizer pass limit.
        threads: Freerouting optimization threads.
        timeout: Max seconds to wait for Freerouting.
        apply: If True, apply routes to the session. Default: False (preview).
    """
    from ..backends import freerouting
    from ..specctra import DsnExportError, DsnOptions, board_to_dsn

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}
    if session._working_doc is None:
        return {"error": "Session has no working document"}
    doc = session._working_doc

    if not freerouting.is_available():
        info = freerouting.runtime_info()
        return {"error": "Freerouting not available", "details": info}

    opts = DsnOptions(
        trace_width=trace_width,
        clearance=clearance,
        via_diameter=via_diameter,
        via_drill=via_drill,
    )
    try:
        dsn = board_to_dsn(doc, opts, name="autoroute", outline_points=_live_outline_points())
    except DsnExportError as exc:
        return {"error": str(exc)}

    with tempfile.TemporaryDirectory(prefix="freerouting_") as tmp:
        dsn_path = str(Path(tmp) / "board.dsn")
        ses_path = str(Path(tmp) / "board.ses")
        Path(dsn_path).write_text(dsn, encoding="utf-8")

        try:
            run = freerouting.route(
                dsn_path,
                ses_path,
                max_passes=max_passes,
                threads=threads,
                timeout=timeout,
            )
        except freerouting.FreeroutingNotFound as exc:
            return {"error": str(exc)}
        except freerouting.FreeroutingError as exc:
            return {"error": f"Freerouting failed: {exc}"}

        ses_text = Path(ses_path).read_text(encoding="utf-8")

    if not apply:
        from ..specctra import infer_units_per_mm, parse_ses

        scale = infer_units_per_mm(ses_text, _known_positions(doc))
        route = parse_ses(ses_text, units_per_mm=scale)
        return {
            "status": "preview",
            "freerouting": run,
            "routed_traces": route.segment_count,
            "routed_vias": len(route.vias),
            "calibrated_units_per_mm": scale,
        }

    result = _apply_ses_text(mgr, session, ses_text)
    result["freerouting"] = run
    result["status"] = "applied"
    return result


# ── Registration ───────────────────────────────────────────────────

register_tool(
    name="check_freerouting",
    description="Check whether the Freerouting autorouter is available (jar/native/docker).",
    parameters={},
    handler=_check_freerouting_handler,
    category="freerouting",
)

register_tool(
    name="export_dsn",
    description="Export the board to a Specctra DSN file (Freerouting input format).",
    parameters={
        "output_path": {"type": "string", "description": "Output .dsn path."},
        "session_id": {
            "type": "string",
            "description": "Active session to export (optional; defaults to loaded board).",
        },
        "trace_width": {"type": "number", "description": "Default trace width (mm). Default 0.25."},
        "clearance": {"type": "number", "description": "Default clearance (mm). Default 0.2."},
        "via_diameter": {"type": "number", "description": "Via pad diameter (mm). Default 0.8."},
        "via_drill": {"type": "number", "description": "Via drill (mm). Default 0.4."},
    },
    handler=_export_dsn_handler,
    category="freerouting",
)

register_tool(
    name="import_ses",
    description="Import a Specctra SES routing result and apply its traces/vias to a session.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "ses_path": {"type": "string", "description": "Path to the .ses file."},
    },
    handler=_import_ses_handler,
    category="freerouting",
)

register_tool(
    name="autoroute_freerouting",
    description=(
        "Autoroute the board with Freerouting (DSN→route→SES) and optionally apply "
        "the traces/vias to the session."
    ),
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "trace_width": {"type": "number", "description": "Trace width (mm). Default 0.25."},
        "clearance": {"type": "number", "description": "Clearance (mm). Default 0.2."},
        "via_diameter": {"type": "number", "description": "Via pad diameter (mm). Default 0.8."},
        "via_drill": {"type": "number", "description": "Via drill (mm). Default 0.4."},
        "max_passes": {"type": "integer", "description": "Optimizer pass limit. Default 10."},
        "threads": {"type": "integer", "description": "Optimization threads. Default 1."},
        "timeout": {"type": "integer", "description": "Max seconds to wait. Default 300."},
        "apply": {"type": "boolean", "description": "Apply routes to session. Default false."},
    },
    handler=_autoroute_freerouting_handler,
    category="freerouting",
)
