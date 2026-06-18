"""Tests for convenience placement (duplicate/array/align) and the 2D view tool."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import kicad_mcp.tools  # noqa: F401  — triggers tool registration
from kicad_mcp.session import SessionManager
from kicad_mcp.session.helpers import find_footprint
from kicad_mcp.sexp import Document

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "minimal_board.kicad_pcb"
BOARD_PATH = Path(os.environ.get("KICAD_TEST_BOARD", str(FIXTURE_PATH)))

pytestmark = pytest.mark.skipif(not BOARD_PATH.exists(), reason="Test fixture not available")


@pytest.fixture()
def mgr_session() -> tuple[SessionManager, object]:
    doc = Document.load(BOARD_PATH)
    mgr = SessionManager()
    return mgr, mgr.start_session(doc)


# ── read_position / apply_duplicate (session layer) ────────────────


class TestReadPosition:
    def test_reads_known_position(self, mgr_session) -> None:
        mgr, session = mgr_session
        pos = mgr.read_position(session, "R1")
        assert pos == {"x": 10.0, "y": 10.0, "angle": 0.0}

    def test_missing_raises(self, mgr_session) -> None:
        mgr, session = mgr_session
        with pytest.raises(ValueError, match="not found"):
            mgr.read_position(session, "NOPE")


class TestApplyDuplicate:
    def test_duplicate_creates_new_footprint(self, mgr_session) -> None:
        mgr, session = mgr_session
        record = mgr.apply_duplicate(session, "R1", "R99", 40.0, 25.0)
        assert record.applied
        assert record.operation == "place_component"  # so undo removes it
        assert record.target == "R99"

        dup = find_footprint(session._working_doc, "R99")
        assert dup is not None
        at = dup.get("at")
        assert float(at.atom_values[0]) == 40.0
        assert float(at.atom_values[1]) == 25.0

    def test_duplicate_preserves_pads(self, mgr_session) -> None:
        mgr, session = mgr_session
        mgr.apply_duplicate(session, "R1", "R99", 40.0, 25.0)
        dup = find_footprint(session._working_doc, "R99")
        assert len(dup.find_all("pad")) == 2  # same as R1

    def test_duplicate_regenerates_uuid(self, mgr_session) -> None:
        mgr, session = mgr_session
        original = find_footprint(session._working_doc, "R1")
        orig_uuid = original.get("uuid").first_value
        mgr.apply_duplicate(session, "R1", "R99", 40.0, 25.0)
        dup = find_footprint(session._working_doc, "R99")
        assert dup.get("uuid").first_value != orig_uuid

    def test_duplicate_to_existing_ref_raises(self, mgr_session) -> None:
        mgr, session = mgr_session
        with pytest.raises(ValueError, match="already exists"):
            mgr.apply_duplicate(session, "R1", "C1", 40.0, 25.0)

    def test_duplicate_is_undoable(self, mgr_session) -> None:
        mgr, session = mgr_session
        mgr.apply_duplicate(session, "R1", "R99", 40.0, 25.0)
        mgr.undo(session)
        assert find_footprint(session._working_doc, "R99") is None


# ── handler-level: array / align ───────────────────────────────────


def _start_session_via_handler() -> tuple[str, object]:
    """Start a session through the shared singleton manager the handlers use."""
    from kicad_mcp.tools.mutation import _get_manager

    mgr = _get_manager()
    doc = Document.load(BOARD_PATH)
    session = mgr.start_session(doc)
    return session.session_id, mgr


class TestAlignComponents:
    def test_align_left(self) -> None:
        from kicad_mcp.tools.placement import _align_components_handler

        sid, mgr = _start_session_via_handler()
        # R1 x=10, C1 x=20, U1 x=30 → left aligns all to x=10
        out = _align_components_handler(sid, ["R1", "C1", "U1"], "left")
        assert out["status"] == "aligned"
        session = mgr.get_session(sid)
        assert mgr.read_position(session, "C1")["x"] == 10.0
        assert mgr.read_position(session, "U1")["x"] == 10.0
        # y unchanged
        assert mgr.read_position(session, "U1")["y"] == 10.0

    def test_align_skips_already_aligned(self) -> None:
        from kicad_mcp.tools.placement import _align_components_handler

        sid, _ = _start_session_via_handler()
        # All three share y=10 already → top alignment moves nothing
        out = _align_components_handler(sid, ["R1", "C1", "U1"], "top")
        assert out["moved_count"] == 0

    def test_align_distribute_x(self) -> None:
        from kicad_mcp.tools.placement import _align_components_handler

        sid, mgr = _start_session_via_handler()
        out = _align_components_handler(sid, ["R1", "C1", "U1"], "distribute_x")
        assert out["status"] == "aligned"
        session = mgr.get_session(sid)
        # Extremes (10 and 30) fixed, middle evenly spaced at 20
        assert mgr.read_position(session, "C1")["x"] == 20.0

    def test_align_invalid_mode(self) -> None:
        from kicad_mcp.tools.placement import _align_components_handler

        sid, _ = _start_session_via_handler()
        out = _align_components_handler(sid, ["R1", "C1"], "diagonal")
        assert "error" in out

    def test_align_needs_two(self) -> None:
        from kicad_mcp.tools.placement import _align_components_handler

        sid, _ = _start_session_via_handler()
        out = _align_components_handler(sid, ["R1"], "left")
        assert "error" in out


class TestDuplicateHandler:
    def test_invalid_reference(self) -> None:
        from kicad_mcp.tools.placement import _duplicate_component_handler

        sid, _ = _start_session_via_handler()
        out = _duplicate_component_handler(sid, "bad ref!", "R2", 5, 5)
        assert "error" in out

    def test_duplicate_ok(self) -> None:
        from kicad_mcp.tools.placement import _duplicate_component_handler

        sid, _ = _start_session_via_handler()
        out = _duplicate_component_handler(sid, "R1", "R2", 5, 5)
        assert out["status"] == "duplicated"


class TestPlaceComponentArray:
    def test_array_counts(self) -> None:
        from kicad_mcp.tools.placement import _place_component_array_handler

        sid, mgr = _start_session_via_handler()
        out = _place_component_array_handler(
            sid,
            footprint_library="Resistor_SMD:R_0402_1005Metric",
            value="1k",
            reference_prefix="RA",
            start_number=1,
            columns=3,
            rows=2,
            start_x=0,
            start_y=0,
            spacing_x=5,
            spacing_y=5,
        )
        assert out["status"] == "array_placed"
        assert out["placed_count"] == 6
        session = mgr.get_session(sid)
        # Last in grid: RA6 at col=2,row=1 → (10, 5)
        pos = mgr.read_position(session, "RA6")
        assert pos == {"x": 10.0, "y": 5.0, "angle": 0.0}

    def test_array_rejects_bad_dims(self) -> None:
        from kicad_mcp.tools.placement import _place_component_array_handler

        sid, _ = _start_session_via_handler()
        out = _place_component_array_handler(sid, "Resistor_SMD:R", "1k", "RB", 1, 0, 2, 0, 0, 5, 5)
        assert "error" in out


class TestGetBoard2DView:
    def test_no_board_loaded(self) -> None:
        # Fresh state with nothing opened → graceful error.
        from kicad_mcp import state
        from kicad_mcp.tools.visual import _get_board_2d_view_handler

        if state.is_loaded():
            pytest.skip("A board is already loaded in shared state")
        out = _get_board_2d_view_handler()
        assert "error" in out
        assert "No board loaded" in out["error"]
