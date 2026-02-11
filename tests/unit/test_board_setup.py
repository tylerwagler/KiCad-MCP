"""Tests for board setup tools (design rules, board size, outline, text, mounting holes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.session.manager import SessionManager
from kicad_mcp.sexp import Document

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")

skip_no_board = pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")


@skip_no_board
class TestSetBoardSize:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_set_board_size_creates_outline(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_set_board_size(session, 50, 30)
        assert record.applied
        assert record.operation == "set_board_size"

        # Count Edge.Cuts gr_lines — should be exactly 4
        edge_cuts = [
            c
            for c in session._working_doc.root.children
            if c.name == "gr_line" and c.get("layer") and c.get("layer").first_value == "Edge.Cuts"
        ]
        assert len(edge_cuts) == 4

    def test_set_board_size_replaces_existing(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_set_board_size(session, 50, 30)
        mgr.apply_set_board_size(session, 100, 80)

        edge_cuts = [
            c
            for c in session._working_doc.root.children
            if c.name == "gr_line" and c.get("layer") and c.get("layer").first_value == "Edge.Cuts"
        ]
        assert len(edge_cuts) == 4

    def test_set_board_size_undo(self) -> None:
        mgr, session = self._make_session()
        before_count = len(
            [
                c
                for c in session._working_doc.root.children
                if c.name == "gr_line"
                and c.get("layer")
                and c.get("layer").first_value == "Edge.Cuts"
            ]
        )

        mgr.apply_set_board_size(session, 50, 30)
        mgr.undo(session)

        after_count = len(
            [
                c
                for c in session._working_doc.root.children
                if c.name == "gr_line"
                and c.get("layer")
                and c.get("layer").first_value == "Edge.Cuts"
            ]
        )
        assert after_count == before_count


@skip_no_board
class TestAddBoardOutline:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_add_outline(self) -> None:
        mgr, session = self._make_session()
        points = [(0, 0), (50, 0), (50, 40), (25, 50), (0, 40)]
        record = mgr.apply_add_board_outline(session, points)
        assert record.applied
        assert record.operation == "add_board_outline"

    def test_outline_creates_correct_segments(self) -> None:
        mgr, session = self._make_session()

        points = [(0, 0), (50, 0), (50, 30)]
        mgr.apply_add_board_outline(session, points)

        edge_cuts = [
            c
            for c in session._working_doc.root.children
            if c.name == "gr_line" and c.get("layer") and c.get("layer").first_value == "Edge.Cuts"
        ]
        # Should have exactly 3 segments (previous edges cleared)
        assert len(edge_cuts) == 3

    def test_outline_clears_existing_edges(self) -> None:
        """add_board_outline replaces existing Edge.Cuts lines."""
        mgr, session = self._make_session()
        # First call set_board_size to create 4 edges
        mgr.apply_set_board_size(session, 50, 30)
        # Then add_board_outline with 4 points — should clear the 4 from set_board_size
        mgr.apply_add_board_outline(session, [(0, 0), (40, 0), (40, 25), (0, 25)])

        edge_cuts = [
            c
            for c in session._working_doc.root.children
            if c.name == "gr_line" and c.get("layer") and c.get("layer").first_value == "Edge.Cuts"
        ]
        # Should have exactly 4 from add_board_outline (not 8 from both)
        assert len(edge_cuts) == 4

    def test_outline_undo_restores_previous_edges(self) -> None:
        """Undoing add_board_outline restores the previous Edge.Cuts lines."""
        mgr, session = self._make_session()
        # Set initial outline via set_board_size
        mgr.apply_set_board_size(session, 50, 30)
        edges_after_size = [
            c
            for c in session._working_doc.root.children
            if c.name == "gr_line" and c.get("layer") and c.get("layer").first_value == "Edge.Cuts"
        ]
        assert len(edges_after_size) == 4

        # Replace with a 3-point outline
        mgr.apply_add_board_outline(session, [(0, 0), (60, 0), (60, 40)])
        edges_after_outline = [
            c
            for c in session._working_doc.root.children
            if c.name == "gr_line" and c.get("layer") and c.get("layer").first_value == "Edge.Cuts"
        ]
        assert len(edges_after_outline) == 3

        # Undo should restore the 4 edges from set_board_size
        mgr.undo(session)
        edges_after_undo = [
            c
            for c in session._working_doc.root.children
            if c.name == "gr_line" and c.get("layer") and c.get("layer").first_value == "Edge.Cuts"
        ]
        assert len(edges_after_undo) == 4

    def test_outline_too_few_points_fails(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="at least 3"):
            mgr.apply_add_board_outline(session, [(0, 0), (10, 0)])

    def test_outline_undo(self) -> None:
        mgr, session = self._make_session()
        before_count = len(
            [
                c
                for c in session._working_doc.root.children
                if c.name == "gr_line"
                and c.get("layer")
                and c.get("layer").first_value == "Edge.Cuts"
            ]
        )

        mgr.apply_add_board_outline(session, [(0, 0), (50, 0), (50, 30)])
        mgr.undo(session)

        after_count = len(
            [
                c
                for c in session._working_doc.root.children
                if c.name == "gr_line"
                and c.get("layer")
                and c.get("layer").first_value == "Edge.Cuts"
            ]
        )
        assert after_count == before_count


@skip_no_board
class TestAddMountingHole:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_add_mounting_hole(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("footprint"))

        record = mgr.apply_add_mounting_hole(session, 5, 5)
        assert record.applied
        assert record.operation == "add_mounting_hole"

        after_count = len(session._working_doc.root.find_all("footprint"))
        assert after_count == before_count + 1

    def test_mounting_hole_has_pad(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_add_mounting_hole(session, 10, 10, drill=3.2, pad_dia=6.0)

        # Find the mounting hole footprint (last added)
        footprints = session._working_doc.root.find_all("footprint")
        mh = footprints[-1]
        pads = mh.find_all("pad")
        assert len(pads) == 1

        # Verify drill
        drill_node = pads[0].get("drill")
        assert drill_node is not None
        assert float(drill_node.first_value) == 3.2

    def test_mounting_hole_custom_drill(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_add_mounting_hole(session, 5, 5, drill=4.0, pad_dia=8.0)

        footprints = session._working_doc.root.find_all("footprint")
        mh = footprints[-1]
        pad = mh.find_all("pad")[0]
        assert float(pad.get("drill").first_value) == 4.0

    def test_mounting_hole_undo(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("footprint"))

        mgr.apply_add_mounting_hole(session, 5, 5)
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("footprint"))
        assert after_count == before_count


@skip_no_board
class TestAddBoardText:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_add_text(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_add_board_text(session, "Hello", 20, 10)
        assert record.applied
        assert record.operation == "add_board_text"

    def test_text_on_correct_layer(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_add_board_text(session, "Test", 10, 10, layer="B.SilkS")

        texts = session._working_doc.root.find_all("gr_text")
        last_text = texts[-1]
        assert last_text.get("layer").first_value == "B.SilkS"

    def test_text_value(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_add_board_text(session, "Rev A", 10, 10)

        texts = session._working_doc.root.find_all("gr_text")
        last_text = texts[-1]
        assert last_text.first_value == "Rev A"

    def test_text_undo(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("gr_text"))

        mgr.apply_add_board_text(session, "Hello", 20, 10)
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("gr_text"))
        assert after_count == before_count


@skip_no_board
class TestDesignRules:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_set_design_rules(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_set_design_rules(session, {"pad_to_mask_clearance": 0.1})
        assert record.applied
        assert record.operation == "set_design_rules"

    def test_set_design_rules_modifies_setup(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_set_design_rules(session, {"pad_to_mask_clearance": 0.15})

        setup = session._working_doc.root.get("setup")
        clearance_node = setup.get("pad_to_mask_clearance")
        assert clearance_node is not None
        assert float(clearance_node.first_value) == 0.15

    def test_set_solder_mask_min_width(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_set_design_rules(session, {"solder_mask_min_width": 0.05})
        assert record.applied

        setup = session._working_doc.root.get("setup")
        node = setup.get("solder_mask_min_width")
        assert node is not None
        assert float(node.first_value) == 0.05

    def test_set_paste_clearance(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_set_design_rules(session, {"pad_to_paste_clearance": 0.02})
        assert record.applied

    def test_alias_min_clearance(self) -> None:
        """Friendly alias 'min_clearance' maps to 'pad_to_mask_clearance'."""
        mgr, session = self._make_session()
        record = mgr.apply_set_design_rules(session, {"min_clearance": 0.12})
        assert record.applied

        setup = session._working_doc.root.get("setup")
        node = setup.get("pad_to_mask_clearance")
        assert node is not None
        assert float(node.first_value) == 0.12

    def test_rejects_min_track_width(self) -> None:
        """min_track_width belongs in .kicad_dru, not setup."""
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="kicad_dru"):
            mgr.apply_set_design_rules(session, {"min_track_width": 0.15})

    def test_rejects_min_via_diameter(self) -> None:
        """min_via_diameter belongs in .kicad_dru, not setup."""
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="kicad_dru"):
            mgr.apply_set_design_rules(session, {"min_via_diameter": 0.6})

    def test_rejects_min_via_drill(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="kicad_dru"):
            mgr.apply_set_design_rules(session, {"min_via_drill": 0.3})

    def test_rejects_unknown_key(self) -> None:
        """Completely unknown keys are rejected."""
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="Unknown design rule"):
            mgr.apply_set_design_rules(session, {"bogus_key": 1.0})

    def test_rejects_dru_rule_without_modifying_setup(self) -> None:
        """Rejected rules must not partially modify the setup section."""
        mgr, session = self._make_session()
        setup_before = session._working_doc.root.get("setup").to_string()

        with pytest.raises(ValueError):
            # First key is valid, second is not — neither should apply.
            mgr.apply_set_design_rules(
                session,
                {"pad_to_mask_clearance": 0.99, "min_track_width": 0.15},
            )

        setup_after = session._working_doc.root.get("setup").to_string()
        assert setup_before == setup_after

    def test_set_design_rules_undo(self) -> None:
        mgr, session = self._make_session()
        setup_before = session._working_doc.root.get("setup").to_string()

        mgr.apply_set_design_rules(session, {"pad_to_mask_clearance": 0.2})
        mgr.undo(session)

        setup_after = session._working_doc.root.get("setup").to_string()
        assert setup_before == setup_after

    def test_get_design_rules_handler(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        state.load_board(str(BLINKY_PATH))
        result = TOOL_REGISTRY["get_design_rules"].handler()
        assert "rules" in result
        assert isinstance(result["rules"], dict)
        # Should only contain valid setup keys, not e.g. pcbplotparams
        for key in result["rules"]:
            assert key in SessionManager._VALID_SETUP_RULES

    def test_set_design_rules_tool_rejects_invalid(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        state.load_board(str(BLINKY_PATH))
        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["set_design_rules"].handler(
            session_id=sid,
            rules={"min_track_width": 0.15},
        )
        assert "error" in result
        assert "kicad_dru" in result["error"]


@skip_no_board
class TestSetActiveLayer:
    def test_set_active_layer(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["set_active_layer"].handler(layer="B.Cu")
        assert result["status"] == "set"
        assert result["active_layer"] == "B.Cu"


@skip_no_board
class TestBoardSetupToolHandlers:
    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_set_board_size_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["set_board_size"].handler(session_id=sid, width=60, height=40)
        assert result["status"] == "updated"

    def test_add_board_outline_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["add_board_outline"].handler(
            session_id=sid,
            points=[[0, 0], [50, 0], [50, 30], [0, 30]],
        )
        assert result["status"] == "added"

    def test_add_mounting_hole_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["add_mounting_hole"].handler(session_id=sid, x=5, y=5)
        assert result["status"] == "added"

    def test_add_board_text_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["add_board_text"].handler(session_id=sid, text="Test", x=10, y=10)
        assert result["status"] == "added"

    def test_set_design_rules_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["set_design_rules"].handler(
            session_id=sid,
            rules={"pad_to_mask_clearance": 0.1},
        )
        assert result["status"] == "updated"
