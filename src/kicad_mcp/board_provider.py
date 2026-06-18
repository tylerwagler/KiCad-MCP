"""Live-preferred board read provider.

When KiCad is connected over IPC (kipy), board *reads* reflect the live — possibly
unsaved — board. Otherwise reads fall back to the parsed file held in :mod:`state`.

This is PCB-only: schematics have no IPC surface in KiCad 9/10 and always use the
parser. Likewise :func:`state.get_document` (the S-expression tree, needed for file
mutations and DSN export) is never sourced from IPC — only summaries/footprints/nets
become live here.

Net codes are deprecated in KiCad 10, so live nets are keyed by name; the numeric
``number`` is a best-effort echo of the (deprecated) code.
"""

from __future__ import annotations

import contextlib
import threading
from typing import TYPE_CHECKING

from .schema.board import BoardSummary, Footprint, Net
from .schema.common import Position

if TYPE_CHECKING:
    from .backends.ipc_api import IpcBackend

_lock = threading.Lock()
_prefer_ipc = True


def set_prefer_ipc(enabled: bool) -> None:
    """Enable/disable preferring the live IPC board for reads (default: enabled)."""
    global _prefer_ipc
    with _lock:
        _prefer_ipc = enabled


def prefer_ipc() -> bool:
    """Whether live IPC reads are preferred when KiCad is connected."""
    with _lock:
        return _prefer_ipc


def _live() -> IpcBackend | None:
    """Return the connected IPC backend if live reads are active, else None."""
    if not prefer_ipc():
        return None
    from .backends.ipc_api import IpcBackend

    ipc = IpcBackend.get()
    return ipc if ipc.is_connected() else None


def active_source() -> str:
    """Report where reads currently come from: 'ipc', 'parser', or 'none'."""
    if _live() is not None:
        return "ipc"
    from . import state

    return "parser" if state.is_parser_loaded() else "none"


# ── Live → schema mapping ──────────────────────────────────────────


def _live_footprints(ipc: IpcBackend) -> list[Footprint]:
    """Map the live board's footprints into typed schema objects.

    Pads are not populated on the live path (kipy exposes them separately and the
    pad-heavy consumers — DSN export, routing — use the parsed working doc instead).
    """
    out: list[Footprint] = []
    for d in ipc.get_footprints():
        pos = d.get("position", {})
        out.append(
            Footprint(
                library=d.get("library", ""),
                reference=d.get("reference", ""),
                value=d.get("value", ""),
                position=Position(
                    x=float(pos.get("x", 0.0)),
                    y=float(pos.get("y", 0.0)),
                    angle=float(d.get("rotation", 0.0) or 0.0),
                ),
                layer=d.get("layer", ""),
                pads=[],
            )
        )
    return out


def _live_nets(ipc: IpcBackend) -> list[Net]:
    """Map the live board's nets (keyed by name; number is best-effort)."""
    nets: list[Net] = []
    try:
        # Net codes are deprecated in KiCad 10 — bind by name; number stays 0.
        for net in ipc.live_board().get_nets():
            nets.append(Net(number=0, name=getattr(net, "name", "") or ""))
    except Exception:  # noqa: BLE001 — live net read is best-effort
        return []
    return nets


def _live_summary(ipc: IpcBackend) -> BoardSummary:
    """Build a board summary from the live board (counts + nets, best-effort fields)."""
    footprints = _live_footprints(ipc)
    nets = _live_nets(ipc)

    segment_count = 0
    try:
        segment_count = len(ipc.get_tracks())
    except Exception:  # noqa: BLE001
        segment_count = 0

    copper_layers: list[str] = []
    layer_count = 0
    with contextlib.suppress(Exception):
        layer_count = int(ipc.get_copper_layer_count())
    try:
        stackup = ipc.get_board_stackup()
        copper_layers = list(stackup.get("copper_layers", []))
        if not layer_count:
            layer_count = int(stackup.get("layer_count", len(copper_layers)))
    except Exception:  # noqa: BLE001
        pass

    title = ""
    with contextlib.suppress(Exception):
        title = ipc.get_title_block_info().get("title", "") or ""

    return BoardSummary(
        title=title,
        version="ipc",
        generator="kicad-ipc",
        thickness=0.0,
        layer_count=layer_count,
        copper_layers=copper_layers,
        net_count=len(nets),
        footprint_count=len(footprints),
        segment_count=segment_count,
        nets=nets,
        layers=[],
    )


# ── Public read API (state delegates here) ─────────────────────────


def get_footprints() -> list[Footprint]:
    """Footprints from the live board if connected, else the parsed file."""
    ipc = _live()
    if ipc is not None:
        # Any live failure falls back to the parser.
        with contextlib.suppress(Exception):
            return _live_footprints(ipc)
    from . import state

    return state.parser_footprints()


def live_outline_points(ipc: IpcBackend) -> list[tuple[float, float]] | None:
    """Real board outline polygon (mm) from the live KiCad Edge.Cuts, or None.

    Returns None if the outline isn't a chain of straight segments (e.g. it
    contains arcs) — callers then fall back to the parsed file / bounding box.
    """
    from .specctra.dsn import chain_outline_segments

    try:
        import kipy.util.board_layer as ubl

        segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for shape in ipc.live_board().get_shapes():
            try:
                if ubl.canonical_name(shape.layer) != "Edge.Cuts":
                    continue
            except Exception:  # noqa: BLE001
                continue
            if type(shape).__name__ != "BoardSegment":
                return None  # an arc/curve on the outline — fall back
            start, end = shape.start, shape.end
            segs.append(
                (
                    (ipc._nm_to_mm(start.x), ipc._nm_to_mm(start.y)),
                    (ipc._nm_to_mm(end.x), ipc._nm_to_mm(end.y)),
                )
            )
        return chain_outline_segments(segs)
    except Exception:  # noqa: BLE001 — live outline is best-effort
        return None


def get_summary() -> BoardSummary:
    """Board summary from the live board if connected, else the parsed file."""
    ipc = _live()
    if ipc is not None:
        # Any live failure falls back to the parser.
        with contextlib.suppress(Exception):
            return _live_summary(ipc)
    from . import state

    return state.parser_summary()
