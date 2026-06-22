"""Headless copper-zone fill — IPC-first, pcbnew fallback.

Zone fill has no ``kicad-cli`` command, so it needs one of two engines:

* the **IPC API** (kipy ``refill_zones``/``save``) — the forward path, and the
  *only* path on KiCad 11, where the SWIG ``pcbnew`` module is removed;
* **pcbnew** ``ZONE_FILLER`` — the legacy path, the only headless option on
  KiCad <= 10 (whose ``kicad-cli`` has no ``api-server``).

This module tries IPC first and falls back to pcbnew, so a single call does the
right thing on both KiCad 10 and 11 installs.
"""

from __future__ import annotations

from typing import Any

from . import ipc_fill, pcbnew_fill


def fill_zones(board_path: str) -> dict[str, Any]:
    """Fill every copper zone on the board file, in place.

    Returns ``{"filled": <count>, "backend": "ipc"|"pcbnew"}``.

    Raises:
        RuntimeError: if neither the IPC API nor pcbnew can fill (e.g. KiCad 11
            present but no ``api-server``/kipy, or KiCad <= 10 with no pcbnew).
    """
    ipc_result = ipc_fill.fill_zones(board_path)
    if ipc_result is not None:
        return ipc_result
    return pcbnew_fill.fill_zones(board_path)
