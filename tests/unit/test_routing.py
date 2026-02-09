"""Tests for trace routing tools (route_trace, add_via, delete_trace, ratsnest)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.session.manager import SessionManager
from kicad_mcp.sexp import Document

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")

skip_no_board = pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")


@skip_no_board
class TestRouteTrace:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_route_trace_adds_segment(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("segment"))

        record = mgr.apply_route_trace(session, 10, 5, 20, 5, 0.25, "F.Cu", 1)
        assert record.applied
        assert record.operation == "route_trace"

        after_count = len(session._working_doc.root.find_all("segment"))
        assert after_count == before_count + 1

    def test_route_trace_correct_properties(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_route_trace(session, 10, 5, 20, 15, 0.4, "B.Cu", 3)

        # Find the last segment (the one we added)
        segments = session._working_doc.root.find_all("segment")
        seg = segments[-1]

        start = seg.get("start")
        assert float(start.atom_values[0]) == 10.0
        assert float(start.atom_values[1]) == 5.0

        end = seg.get("end")
        assert float(end.atom_values[0]) == 20.0
        assert float(end.atom_values[1]) == 15.0

        assert float(seg.get("width").first_value) == 0.4
        assert seg.get("layer").first_value == "B.Cu"
        assert int(seg.get("net").first_value) == 3

    def test_route_trace_undo(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("segment"))

        mgr.apply_route_trace(session, 10, 5, 20, 5, 0.25, "F.Cu", 1)
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("segment"))
        assert after_count == before_count


@skip_no_board
class TestAddVia:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_add_via(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("via"))

        record = mgr.apply_add_via(session, 15, 10, 1, size=0.8, drill=0.4)
        assert record.applied
        assert record.operation == "add_via"

        after_count = len(session._working_doc.root.find_all("via"))
        assert after_count == before_count + 1

    def test_via_correct_properties(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_add_via(session, 25, 12, 2, size=0.9, drill=0.5, layers=("F.Cu", "B.Cu"))

        vias = session._working_doc.root.find_all("via")
        via = vias[-1]

        at = via.get("at")
        assert float(at.atom_values[0]) == 25.0
        assert float(at.atom_values[1]) == 12.0

        assert float(via.get("size").first_value) == 0.9
        assert float(via.get("drill").first_value) == 0.5
        assert int(via.get("net").first_value) == 2

        layers = via.get("layers")
        assert "F.Cu" in layers.atom_values
        assert "B.Cu" in layers.atom_values

    def test_via_undo(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("via"))

        mgr.apply_add_via(session, 15, 10, 1)
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("via"))
        assert after_count == before_count


@skip_no_board
class TestDeleteTrace:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_delete_trace(self) -> None:
        mgr, session = self._make_session()
        # Get the UUID of the first segment
        segments = session._working_doc.root.find_all("segment")
        assert len(segments) > 0
        first_uuid = segments[0].get("uuid").first_value

        before_count = len(segments)
        record = mgr.apply_delete_trace(session, first_uuid)
        assert record.applied
        assert record.operation == "delete_trace"

        after_count = len(session._working_doc.root.find_all("segment"))
        assert after_count == before_count - 1

    def test_delete_trace_not_found(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="not found"):
            mgr.apply_delete_trace(session, "nonexistent-uuid")

    def test_delete_trace_undo(self) -> None:
        mgr, session = self._make_session()
        segments = session._working_doc.root.find_all("segment")
        first_uuid = segments[0].get("uuid").first_value
        before_count = len(segments)

        mgr.apply_delete_trace(session, first_uuid)
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("segment"))
        assert after_count == before_count


@skip_no_board
class TestDeleteVia:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_delete_via_after_add(self) -> None:
        mgr, session = self._make_session()
        # Add a via first, then delete it
        mgr.apply_add_via(session, 15, 10, 1)
        vias = session._working_doc.root.find_all("via")
        via_uuid = vias[-1].get("uuid").first_value

        record = mgr.apply_delete_via(session, via_uuid)
        assert record.applied

        after_count = len(session._working_doc.root.find_all("via"))
        assert after_count == 0  # blinky has no vias originally

    def test_delete_via_not_found(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="not found"):
            mgr.apply_delete_via(session, "nonexistent-uuid")

    def test_delete_via_undo(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_add_via(session, 15, 10, 1)
        vias = session._working_doc.root.find_all("via")
        via_uuid = vias[-1].get("uuid").first_value

        mgr.apply_delete_via(session, via_uuid)
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("via"))
        assert after_count == 1


@skip_no_board
class TestGetRatsnest:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_ratsnest_returns_list(self) -> None:
        mgr, session = self._make_session()
        result = mgr.get_ratsnest(session)
        assert isinstance(result, list)

    def test_ratsnest_structure(self) -> None:
        mgr, session = self._make_session()
        result = mgr.get_ratsnest(session)
        # Blinky has some nets with pads but may or may not have full routing
        for entry in result:
            assert "net_number" in entry
            assert "net_name" in entry
            assert "pad_count" in entry
            assert "pads" in entry
            assert entry["pad_count"] >= 2


@skip_no_board
class TestRoutingToolHandlers:
    """Test the registered tool handlers."""

    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_route_trace_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["route_trace"].handler(
            session_id=sid,
            start_x=10,
            start_y=5,
            end_x=20,
            end_y=5,
            width=0.25,
            layer="F.Cu",
            net_number=1,
        )
        assert result["status"] == "routed"

    def test_add_via_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["add_via"].handler(session_id=sid, x=15, y=10, net_number=1)
        assert result["status"] == "added"

    def test_delete_trace_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        # Route then delete
        TOOL_REGISTRY["route_trace"].handler(
            session_id=sid,
            start_x=10,
            start_y=5,
            end_x=20,
            end_y=5,
            width=0.25,
            layer="F.Cu",
            net_number=1,
        )
        # Get the UUID from the after_snapshot — use execute_tool to get session status
        # Instead, just try deleting a known segment from blinky
        # Blinky's first segment UUID
        from kicad_mcp import state

        doc = state.get_document()
        segs = doc.root.find_all("segment")
        if segs:
            seg_uuid = segs[0].get("uuid").first_value
            # Need a fresh session since the one above already has the doc
            start2 = TOOL_REGISTRY["start_session"].handler()
            sid2 = start2["session_id"]
            result = TOOL_REGISTRY["delete_trace"].handler(session_id=sid2, segment_uuid=seg_uuid)
            assert result["status"] == "deleted"

    def test_get_ratsnest_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["get_ratsnest"].handler(session_id=sid)
        assert "unrouted_net_count" in result
        assert "unrouted" in result
