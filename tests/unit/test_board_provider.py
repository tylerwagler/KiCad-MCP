"""Tests for the live-preferred board read provider (Phase 2)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kicad_mcp import board_provider, state
from kicad_mcp.backends.ipc_api import IpcBackend

FIXTURE = Path(__file__).parent.parent / "fixtures" / "minimal_board.kicad_pcb"
BOARD = Path(os.environ.get("KICAD_TEST_BOARD", str(FIXTURE)))

pytestmark = pytest.mark.skipif(not BOARD.exists(), reason="Board fixture not available")


class _FakeIpc:
    """A connected IPC backend stand-in returning live board data."""

    def __init__(self) -> None:
        self._fps = [
            {
                "reference": "R1",
                "value": "10k",
                "position": {"x": 99.0, "y": 88.0},
                "rotation": 90,
                "layer": "B.Cu",
            }
        ]

    def is_connected(self) -> bool:
        return True

    def get_footprints(self):
        return self._fps

    def get_tracks(self):
        return [{}, {}, {}]

    def get_copper_layer_count(self):
        return 2

    def get_board_stackup(self):
        return {"layer_count": 2, "copper_layers": ["F.Cu", "B.Cu"]}

    def get_title_block_info(self):
        return {"title": "LiveBoard"}

    def live_board(self):
        class _Net:
            def __init__(self, code, name):
                self.code, self.name = code, name

        class _B:
            def get_nets(self):
                return [_Net(1, "VCC"), _Net(2, "GND")]

        return _B()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """Default to parser source and a clean singleton each test."""
    board_provider.set_prefer_ipc(True)
    IpcBackend.reset()
    yield
    IpcBackend.reset()
    board_provider.set_prefer_ipc(True)


def _use_live(monkeypatch) -> None:
    monkeypatch.setattr(IpcBackend, "get", classmethod(lambda cls: _FakeIpc()))


# ── Parser fallback (no IPC) ───────────────────────────────────────


class TestParserFallback:
    def test_footprints_from_parser(self) -> None:
        state.load_board(str(BOARD))
        fps = board_provider.get_footprints()
        refs = {fp.reference for fp in fps}
        assert {"R1", "C1", "U1"} <= refs

    def test_summary_from_parser(self) -> None:
        state.load_board(str(BOARD))
        summary = board_provider.get_summary()
        assert summary.footprint_count == 3
        assert summary.generator != "kicad-ipc"  # parser path

    def test_active_source_parser(self) -> None:
        state.load_board(str(BOARD))
        assert board_provider.active_source() == "parser"


# ── Live IPC source ────────────────────────────────────────────────


class TestLiveSource:
    def test_active_source_ipc(self, monkeypatch) -> None:
        _use_live(monkeypatch)
        assert board_provider.active_source() == "ipc"

    def test_footprints_from_live(self, monkeypatch) -> None:
        _use_live(monkeypatch)
        fps = board_provider.get_footprints()
        assert len(fps) == 1
        fp = fps[0]
        assert fp.reference == "R1"
        assert fp.position.x == 99.0
        assert fp.position.angle == 90.0
        assert fp.layer == "B.Cu"

    def test_summary_from_live(self, monkeypatch) -> None:
        _use_live(monkeypatch)
        summary = board_provider.get_summary()
        assert summary.generator == "kicad-ipc"
        assert summary.footprint_count == 1
        assert summary.net_count == 2
        assert summary.segment_count == 3
        assert summary.copper_layers == ["F.Cu", "B.Cu"]
        assert {n.name for n in summary.nets} == {"VCC", "GND"}

    def test_state_delegates_to_live(self, monkeypatch) -> None:
        _use_live(monkeypatch)
        assert state.get_footprints()[0].reference == "R1"
        assert state.is_loaded() is True

    def test_prefer_ipc_off_uses_parser(self, monkeypatch) -> None:
        state.load_board(str(BOARD))
        _use_live(monkeypatch)
        board_provider.set_prefer_ipc(False)
        # Even though "connected", policy forces the parser path.
        assert board_provider.active_source() == "parser"
        assert len(board_provider.get_footprints()) == 3


# ── Live failure falls back to parser ──────────────────────────────


class TestLiveFailureFallback:
    def test_live_error_falls_back(self, monkeypatch) -> None:
        state.load_board(str(BOARD))

        class _Broken(_FakeIpc):
            def get_footprints(self):
                raise RuntimeError("socket died")

        monkeypatch.setattr(IpcBackend, "get", classmethod(lambda cls: _Broken()))
        fps = board_provider.get_footprints()  # should not raise
        assert len(fps) == 3  # parser data
