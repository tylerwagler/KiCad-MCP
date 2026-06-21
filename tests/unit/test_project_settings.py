"""Tests for .kicad_pro net classes and board constraints (gap #3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.session import project_settings
from kicad_mcp.tools.project import _KICAD_PRO_TEMPLATE, _minimal_kicad_pcb


def _project(tmp_path: Path) -> str:
    """Create a board + sibling .kicad_pro, return the board path."""
    board = tmp_path / "demo.kicad_pcb"
    board.write_text(_minimal_kicad_pcb(100, 80))
    pro = tmp_path / "demo.kicad_pro"
    pro.write_text(json.dumps(_KICAD_PRO_TEMPLATE, indent=2))
    return str(board)


def _read_pro(board_path: str) -> dict:
    return json.loads(project_settings.project_path_for(board_path).read_text())


class TestBoardConstraints:
    def test_writes_canonical_rules(self, tmp_path):
        board = _project(tmp_path)
        project_settings.set_board_constraints(
            board, {"min_track_width": 0.127, "min_clearance": 0.127}
        )
        rules = _read_pro(board)["board"]["design_settings"]["rules"]
        assert rules["min_track_width"] == 0.127
        assert rules["min_clearance"] == 0.127

    def test_aliases_resolve(self, tmp_path):
        board = _project(tmp_path)
        project_settings.set_board_constraints(
            board,
            {
                "min_track": 0.13,
                "min_space": 0.13,
                "min_via": 0.4,
                "min_via_drill": 0.2,
                "min_annular_width": 0.1,
            },
        )
        rules = _read_pro(board)["board"]["design_settings"]["rules"]
        assert rules["min_track_width"] == 0.13
        assert rules["min_clearance"] == 0.13
        assert rules["min_via_diameter"] == 0.4
        assert rules["min_through_hole_diameter"] == 0.2
        assert rules["min_via_annular_width"] == 0.1

    def test_unknown_key_raises(self, tmp_path):
        board = _project(tmp_path)
        with pytest.raises(ValueError, match="Unknown constraint"):
            project_settings.set_board_constraints(board, {"bogus": 1.0})

    def test_preserves_other_design_settings(self, tmp_path):
        board = _project(tmp_path)
        project_settings.set_board_constraints(board, {"min_clearance": 0.2})
        ds = _read_pro(board)["board"]["design_settings"]
        # The template's defaults block must survive.
        assert ds["defaults"]["board_outline_line_width"] == 0.05

    def test_missing_project_raises(self, tmp_path):
        board = tmp_path / "noproj.kicad_pcb"
        board.write_text(_minimal_kicad_pcb(10, 10))
        with pytest.raises(FileNotFoundError):
            project_settings.set_board_constraints(str(board), {"min_clearance": 0.2})


class TestNetClass:
    def test_creates_new_class_with_defaults_and_overrides(self, tmp_path):
        board = _project(tmp_path)
        project_settings.set_net_class(board, "Isolation", {"clearance": 4.0, "track_width": 0.3})
        classes = _read_pro(board)["net_settings"]["classes"]
        iso = next(c for c in classes if c["name"] == "Isolation")
        assert iso["clearance"] == 4.0
        assert iso["track_width"] == 0.3
        # Untouched fields come from the KiCad default shape.
        assert iso["via_diameter"] == 0.6
        assert "priority" in iso

    def test_update_existing_class_in_place(self, tmp_path):
        board = _project(tmp_path)
        project_settings.set_net_class(board, "Power", {"clearance": 0.3})
        project_settings.set_net_class(board, "Power", {"track_width": 0.5})
        classes = _read_pro(board)["net_settings"]["classes"]
        power = [c for c in classes if c["name"] == "Power"]
        assert len(power) == 1
        assert power[0]["clearance"] == 0.3
        assert power[0]["track_width"] == 0.5

    def test_assigns_nets_via_patterns(self, tmp_path):
        board = _project(tmp_path)
        project_settings.set_net_class(
            board, "Isolation", {"clearance": 4.0}, nets=["ISO_5V", "SHIELD"]
        )
        pats = _read_pro(board)["net_settings"]["netclass_patterns"]
        mapping = {p["pattern"]: p["netclass"] for p in pats}
        assert mapping == {"ISO_5V": "Isolation", "SHIELD": "Isolation"}

    def test_reassigning_net_moves_it(self, tmp_path):
        board = _project(tmp_path)
        project_settings.set_net_class(board, "A", {"clearance": 1.0}, nets=["N1"])
        project_settings.set_net_class(board, "B", {"clearance": 2.0}, nets=["N1"])
        pats = _read_pro(board)["net_settings"]["netclass_patterns"]
        n1 = [p for p in pats if p["pattern"] == "N1"]
        assert len(n1) == 1 and n1[0]["netclass"] == "B"

    def test_wildcard_patterns(self, tmp_path):
        board = _project(tmp_path)
        project_settings.set_net_class(board, "Iso", {"clearance": 4.0}, patterns=["/ISO_*"])
        pats = _read_pro(board)["net_settings"]["netclass_patterns"]
        assert {"netclass": "Iso", "pattern": "/ISO_*"} in pats

    def test_distinct_ascending_priority(self, tmp_path):
        board = _project(tmp_path)
        project_settings.set_net_class(board, "First", {"clearance": 1.0})
        project_settings.set_net_class(board, "Second", {"clearance": 1.0})
        classes = {c["name"]: c for c in _read_pro(board)["net_settings"]["classes"]}
        assert classes["First"]["priority"] != classes["Second"]["priority"]

    def test_unknown_field_raises(self, tmp_path):
        board = _project(tmp_path)
        with pytest.raises(ValueError, match="Unknown net-class field"):
            project_settings.set_net_class(board, "X", {"bogus": 1.0})


class TestHandlerWiring:
    """Exercise the registered tools through the global manager + state."""

    def _open(self, tmp_path: Path) -> str:
        from kicad_mcp import state

        board = _project(tmp_path)
        state.load_board(board)
        return board

    def test_set_net_class_tool(self, tmp_path):
        from kicad_mcp.tools import TOOL_REGISTRY

        board = self._open(tmp_path)
        sid = TOOL_REGISTRY["start_session"].handler()["session_id"]
        result = TOOL_REGISTRY["set_net_class"].handler(
            session_id=sid,
            name="Isolation",
            clearance=4.0,
            nets=["ISO_5V"],
        )
        assert result["status"] == "updated"
        classes = _read_pro(board)["net_settings"]["classes"]
        assert any(c["name"] == "Isolation" and c["clearance"] == 4.0 for c in classes)

    def test_set_board_constraints_tool(self, tmp_path):
        from kicad_mcp.tools import TOOL_REGISTRY

        board = self._open(tmp_path)
        sid = TOOL_REGISTRY["start_session"].handler()["session_id"]
        result = TOOL_REGISTRY["set_board_constraints"].handler(
            session_id=sid,
            rules={"min_track_width": 0.127, "min_via_annular_width": 0.1},
        )
        assert result["status"] == "updated"
        rules = _read_pro(board)["board"]["design_settings"]["rules"]
        assert rules["min_track_width"] == 0.127
