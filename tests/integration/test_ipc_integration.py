"""Live IPC integration test — runs only against a real, reachable KiCad.

Skipped everywhere a KiCad IPC server is not reachable (CI, headless dev boxes).
To exercise it: open KiCad with a PCB, enable Preferences → Plugins → IPC API
Server, then run `uv run pytest tests/integration/test_ipc_integration.py`.

For a richer manual check, use `scripts/verify_kipy.py`.
"""

from __future__ import annotations

import pytest

from kicad_mcp.backends.ipc_api import IpcBackend

# Probe once at collection time; connect() does a real round-trip so this is
# False unless KiCad is actually reachable.
_ipc = IpcBackend.get()
_LIVE = _ipc.connect()


def _board_reachable() -> bool:
    """True only if the connected socket can actually serve a PCB document.

    A bare connection may land on the project-manager socket (no board), where
    board reads have no handler — those tests should skip, not fail.
    """
    if not _LIVE:
        return False
    try:
        _ipc.get_board_state()
        return True
    except Exception:
        return False


_BOARD = _board_reachable()

needs_connection = pytest.mark.skipif(not _LIVE, reason="No live KiCad IPC connection")
needs_board = pytest.mark.skipif(not _BOARD, reason="No PCB open in a live KiCad PCB editor")


@needs_connection
def test_version_info_reports_live_kicad() -> None:
    info = _ipc.version_info()
    assert info["connected"] is True
    assert info["kicad_version"]


@needs_board
def test_live_footprints_via_provider() -> None:
    from kicad_mcp import board_provider

    assert board_provider.active_source() == "ipc"
    fps = board_provider.get_footprints()
    assert isinstance(fps, list)  # may be empty if the open board has no footprints


@needs_board
def test_live_summary_counts() -> None:
    from kicad_mcp import board_provider

    summary = board_provider.get_summary()
    assert summary.generator == "kicad-ipc"
    assert summary.footprint_count >= 0
