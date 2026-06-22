"""Tests for headless zone fill (IPC-first via zone_fill, pcbnew fallback)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp import state
from kicad_mcp.backends import ipc_fill, pcbnew_fill, zone_fill
from kicad_mcp.tools import TOOL_REGISTRY
from kicad_mcp.tools.project import _minimal_kicad_pcb


def _board_with_zone(tmp_path: Path) -> Path:
    board = tmp_path / "b.kicad_pcb"
    board.write_text(_minimal_kicad_pcb(60, 40))
    state.load_board(str(board))
    sid = TOOL_REGISTRY["start_session"].handler()["session_id"]
    TOOL_REGISTRY["create_net"].handler(session_id=sid, net_name="GND")
    TOOL_REGISTRY["create_zone"].handler(
        session_id=sid,
        net_name="GND",
        layer="F.Cu",
        points=[[1, 1], [59, 1], [59, 39], [1, 39]],
    )
    TOOL_REGISTRY["commit_session"].handler(session_id=sid)
    return board


class TestFillZonesWiring:
    def test_no_board_loaded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(state, "get_board_path", lambda: None)
        result = TOOL_REGISTRY["fill_zones"].handler()
        assert "error" in result and "No board" in result["error"]

    def test_unknown_session(self, tmp_path):
        result = TOOL_REGISTRY["fill_zones"].handler(session_id="deadbeef")
        assert "error" in result and "not found" in result["error"]

    def test_no_engine_reports_clearly(self, tmp_path, monkeypatch):
        board = _board_with_zone(tmp_path)
        # Neither IPC nor pcbnew can fill.
        monkeypatch.setattr(ipc_fill, "fill_zones", lambda _p: None)
        monkeypatch.setattr(pcbnew_fill, "is_available", lambda: False)
        monkeypatch.setattr(pcbnew_fill, "_python_with_pcbnew", lambda: None)
        result = TOOL_REGISTRY["fill_zones"].handler(session_id=None)
        assert "error" in result
        # Message names both engines and the pcbnew escape hatch.
        assert "pcbnew" in result["error"] and "KICAD_PYTHON" in result["error"]
        assert "IPC" in result["error"]
        # The board must be left untouched when fill can't run.
        assert "filled_polygon" not in board.read_text()


# ── IPC transport selection (hermetic, no real KiCad) ───────────────────────


class _FakeBoard:
    def __init__(self) -> None:
        self.refilled = False
        self.saved = False

    def get_zones(self):
        return [object(), object()]

    def refill_zones(self, block: bool = True) -> None:
        self.refilled = True

    def save(self) -> None:
        self.saved = True


class _FakeKiCadHeadless:
    """A kipy-like class whose ctor accepts headless/file_path."""

    last: _FakeKiCadHeadless | None = None

    def __init__(self, socket_path=None, *, headless=False, file_path=None, **kw) -> None:
        self.headless = headless
        self.file_path = file_path
        self._board = _FakeBoard()
        type(self).last = self

    def get_board(self):
        return self._board

    def close(self) -> None:
        pass


class _FakeKiCadNoHeadless:
    """A kipy-like class whose ctor lacks a headless parameter."""

    def __init__(self, socket_path=None, **kw) -> None:
        self._board = _FakeBoard()

    def get_board(self):
        return self._board


class TestIpcFillTransport:
    def test_ctor_headless_detection(self):
        assert ipc_fill._ctor_supports_headless(_FakeKiCadHeadless) is True
        assert ipc_fill._ctor_supports_headless(_FakeKiCadNoHeadless) is False

    def test_returns_none_when_kipy_absent(self, monkeypatch):
        monkeypatch.setattr(ipc_fill, "_kipy_kicad", lambda: None)
        assert ipc_fill.fill_zones("/x.kicad_pcb") is None

    def test_returns_none_when_no_transport(self, monkeypatch):
        monkeypatch.setattr(ipc_fill, "_kipy_kicad", lambda: _FakeKiCadNoHeadless)
        monkeypatch.setattr(ipc_fill, "_kicad_cli_has_api_server", lambda: False)
        assert ipc_fill.fill_zones("/x.kicad_pcb") is None

    def test_headless_ctor_path(self, monkeypatch):
        monkeypatch.setattr(ipc_fill, "_kipy_kicad", lambda: _FakeKiCadHeadless)
        result = ipc_fill.fill_zones("/board.kicad_pcb")
        assert result == {"filled": 2, "backend": "ipc"}
        kc = _FakeKiCadHeadless.last
        assert kc is not None and kc.headless is True
        assert kc.file_path == "/board.kicad_pcb"
        assert kc._board.refilled and kc._board.saved

    def test_spawned_server_path(self, monkeypatch):
        monkeypatch.setattr(ipc_fill, "_kipy_kicad", lambda: _FakeKiCadNoHeadless)
        monkeypatch.setattr(ipc_fill, "_kicad_cli_has_api_server", lambda: True)
        sentinel = {"filled": 5, "backend": "ipc"}
        called: dict[str, str] = {}

        def fake_spawn(path: str, cls) -> dict:
            called["path"] = path
            return sentinel

        monkeypatch.setattr(ipc_fill, "_fill_via_spawned_server", fake_spawn)
        assert ipc_fill.fill_zones("/b.kicad_pcb") is sentinel
        assert called["path"] == "/b.kicad_pcb"


class TestZoneFillOrchestration:
    def test_ipc_success_short_circuits_pcbnew(self, monkeypatch):
        monkeypatch.setattr(ipc_fill, "fill_zones", lambda _p: {"filled": 3, "backend": "ipc"})

        def boom(_p):
            raise AssertionError("pcbnew must not be called when IPC succeeds")

        monkeypatch.setattr(pcbnew_fill, "fill_zones", boom)
        assert zone_fill.fill_zones("/b.kicad_pcb") == {"filled": 3, "backend": "ipc"}

    def test_ipc_none_falls_back_to_pcbnew(self, monkeypatch):
        monkeypatch.setattr(ipc_fill, "fill_zones", lambda _p: None)
        monkeypatch.setattr(
            pcbnew_fill, "fill_zones", lambda _p: {"filled": 2, "backend": "pcbnew"}
        )
        assert zone_fill.fill_zones("/b.kicad_pcb") == {"filled": 2, "backend": "pcbnew"}


# ── Real fill (pcbnew engine) — needs pcbnew somewhere ──────────────────────

_HAS_PCBNEW = pcbnew_fill.is_available() or pcbnew_fill._python_with_pcbnew() is not None


@pytest.mark.skipif(not _HAS_PCBNEW, reason="pcbnew not available in any interpreter")
class TestFillZonesReal:
    def test_fill_adds_filled_polygon(self, tmp_path, monkeypatch):
        # Force the pcbnew engine so this is deterministic regardless of IPC.
        monkeypatch.setattr(ipc_fill, "fill_zones", lambda _p: None)
        board = _board_with_zone(tmp_path)
        assert "filled_polygon" not in board.read_text()
        result = TOOL_REGISTRY["fill_zones"].handler()
        assert result["status"] == "filled"
        assert result["filled"] == 1
        assert result["backend"] == "pcbnew"
        assert "filled_polygon" in board.read_text()

    def test_state_refreshed_and_nets_readable(self, tmp_path, monkeypatch):
        """pcbnew rewrites in canonical form; reader must still see the net."""
        from kicad_mcp.schema.extract import extract_nets

        monkeypatch.setattr(ipc_fill, "fill_zones", lambda _p: None)
        _board_with_zone(tmp_path)
        TOOL_REGISTRY["fill_zones"].handler()
        nets = extract_nets(state.get_document())
        assert any(n.name == "GND" for n in nets)
