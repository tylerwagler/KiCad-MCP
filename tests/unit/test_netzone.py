"""Tests for net and zone creation tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.session.manager import SessionManager
from kicad_mcp.sexp import Document

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")

skip_no_board = pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")


@skip_no_board
class TestCreateNet:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_create_net_adds_net(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("net"))

        record = mgr.apply_create_net(session, "VCC_3V3")
        assert record.applied
        assert record.operation == "create_net"

        after_count = len(session._working_doc.root.find_all("net"))
        assert after_count == before_count + 1

    def test_create_net_assigns_next_number(self) -> None:
        mgr, session = self._make_session()
        # Blinky has nets 0-8, so next should be 9
        mgr.apply_create_net(session, "MY_NET")

        found = False
        for net_node in session._working_doc.root.find_all("net"):
            vals = net_node.atom_values
            if len(vals) >= 2 and vals[1] == "MY_NET":
                assert int(vals[0]) == 9
                found = True
                break
        assert found

    def test_create_duplicate_net_fails(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="already exists"):
            mgr.apply_create_net(session, "VBUS")

    def test_create_net_undo(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("net"))

        mgr.apply_create_net(session, "VCC_3V3")
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("net"))
        assert after_count == before_count


@skip_no_board
class TestDeleteNet:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_delete_net_removes_it(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("net"))

        record = mgr.apply_delete_net(session, "VBUS")
        assert record.applied

        after_count = len(session._working_doc.root.find_all("net"))
        assert after_count == before_count - 1

    def test_delete_nonexistent_net_fails(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="not found"):
            mgr.apply_delete_net(session, "NONEXISTENT_NET")

    def test_delete_net_undo(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("net"))

        mgr.apply_delete_net(session, "VBUS")
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("net"))
        assert after_count == before_count


@skip_no_board
class TestAssignNet:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_assign_net_to_pad(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_assign_net(session, "C7", "1", "VBUS")
        assert record.applied
        assert record.operation == "assign_net"

        # Verify the pad now has the net
        fp = mgr._find_footprint(session._working_doc, "C7")
        for pad_node in fp.find_all("pad"):
            vals = pad_node.atom_values
            if vals and vals[0] == "1":
                net_node = pad_node.get("net")
                assert net_node is not None
                net_vals = net_node.atom_values
                assert int(net_vals[0]) == 1  # VBUS is net 1
                assert net_vals[1] == "VBUS"
                break

    def test_assign_net_nonexistent_component_fails(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="not found"):
            mgr.apply_assign_net(session, "NONEXISTENT", "1", "VBUS")

    def test_assign_net_nonexistent_pad_fails(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="Pad.*not found"):
            mgr.apply_assign_net(session, "C7", "99", "VBUS")

    def test_assign_nonexistent_net_fails(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="not found"):
            mgr.apply_assign_net(session, "C7", "1", "FAKE_NET")

    def test_assign_net_undo(self) -> None:
        mgr, session = self._make_session()
        # Get pad before
        fp = mgr._find_footprint(session._working_doc, "C7")
        pad_before = None
        for pad_node in fp.find_all("pad"):
            vals = pad_node.atom_values
            if vals and vals[0] == "1":
                pad_before = pad_node.to_string()
                break

        mgr.apply_assign_net(session, "C7", "1", "VBUS")
        mgr.undo(session)

        fp = mgr._find_footprint(session._working_doc, "C7")
        for pad_node in fp.find_all("pad"):
            vals = pad_node.atom_values
            if vals and vals[0] == "1":
                assert pad_node.to_string() == pad_before
                break


@skip_no_board
class TestCreateZone:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_create_zone(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("zone"))

        points = [(0, 0), (40, 0), (40, 30), (0, 30)]
        record = mgr.apply_create_zone(session, "VBUS", "F.Cu", points)
        assert record.applied
        assert record.operation == "create_zone"

        after_count = len(session._working_doc.root.find_all("zone"))
        assert after_count == before_count + 1

    def test_zone_has_correct_net(self) -> None:
        mgr, session = self._make_session()
        points = [(0, 0), (40, 0), (40, 30), (0, 30)]
        mgr.apply_create_zone(session, "VBUS", "F.Cu", points)

        zone = session._working_doc.root.find_all("zone")[0]
        net_name_node = zone.get("net_name")
        assert net_name_node is not None
        assert net_name_node.first_value == "VBUS"

    def test_zone_has_polygon(self) -> None:
        mgr, session = self._make_session()
        points = [(0, 0), (40, 0), (40, 30), (0, 30)]
        mgr.apply_create_zone(session, "VBUS", "F.Cu", points)

        zone = session._working_doc.root.find_all("zone")[0]
        polygon = zone.get("polygon")
        assert polygon is not None
        pts = polygon.get("pts")
        assert pts is not None
        xy_nodes = pts.find_all("xy")
        assert len(xy_nodes) == 4

    def test_zone_too_few_points_fails(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="at least 3"):
            mgr.apply_create_zone(session, "VBUS", "F.Cu", [(0, 0), (10, 0)])

    def test_zone_nonexistent_net_fails(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="not found"):
            mgr.apply_create_zone(session, "FAKE_NET", "F.Cu", [(0, 0), (10, 0), (10, 10)])

    def test_zone_undo(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("zone"))

        points = [(0, 0), (40, 0), (40, 30), (0, 30)]
        mgr.apply_create_zone(session, "VBUS", "F.Cu", points)
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("zone"))
        assert after_count == before_count


@skip_no_board
class TestNetZoneToolHandlers:
    """Test the registered tool handlers."""

    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_create_net_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["create_net"].handler(session_id=sid, net_name="VCC_3V3")
        assert result["status"] == "created"

    def test_assign_net_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["assign_net_to_pad"].handler(
            session_id=sid, reference="C7", pad_number="1", net_name="VBUS"
        )
        assert result["status"] == "assigned"

    def test_create_zone_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["create_zone"].handler(
            session_id=sid,
            net_name="VBUS",
            layer="F.Cu",
            points=[[0, 0], [40, 0], [40, 30], [0, 30]],
        )
        assert result["status"] == "created"

    def test_delete_net_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["delete_net"].handler(session_id=sid, net_name="VBUS")
        assert result["status"] == "deleted"
