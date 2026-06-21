"""Tests for headless zone fill (fill_zones / pcbnew_fill)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp import state
from kicad_mcp.backends import pcbnew_fill
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

    def test_pcbnew_unavailable_reports_clearly(self, tmp_path, monkeypatch):
        board = _board_with_zone(tmp_path)
        monkeypatch.setattr(pcbnew_fill, "is_available", lambda: False)
        monkeypatch.setattr(pcbnew_fill, "_python_with_pcbnew", lambda: None)
        result = TOOL_REGISTRY["fill_zones"].handler(session_id=None)
        assert "error" in result
        assert "pcbnew" in result["error"] and "KICAD_PYTHON" in result["error"]
        # The board must be left untouched when fill can't run.
        assert "filled_polygon" not in board.read_text()


# Real fill needs pcbnew somewhere; skip if no interpreter has it.
_HAS_PCBNEW = pcbnew_fill.is_available() or pcbnew_fill._python_with_pcbnew() is not None


@pytest.mark.skipif(not _HAS_PCBNEW, reason="pcbnew not available in any interpreter")
class TestFillZonesReal:
    def test_fill_adds_filled_polygon(self, tmp_path):
        board = _board_with_zone(tmp_path)
        assert "filled_polygon" not in board.read_text()
        result = TOOL_REGISTRY["fill_zones"].handler()
        assert result["status"] == "filled"
        assert result["filled"] == 1
        assert "filled_polygon" in board.read_text()

    def test_state_refreshed_and_nets_readable(self, tmp_path):
        """pcbnew rewrites in canonical form; reader must still see the net."""
        from kicad_mcp.schema.extract import extract_nets

        _board_with_zone(tmp_path)
        TOOL_REGISTRY["fill_zones"].handler()
        nets = extract_nets(state.get_document())
        assert any(n.name == "GND" for n in nets)
