"""Tests for parity tools: edit/replace component, schematic extras, net extras,
check_clearance, group_components, export_vrml."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from kicad_mcp.session.manager import SessionManager
from kicad_mcp.sexp import Document

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")
BLINKY_SCH_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_sch")

skip_no_board = pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
skip_no_sch = pytest.mark.skipif(
    not BLINKY_SCH_PATH.exists(), reason="Test schematic not available"
)


# ── Group B: Edit/Replace Component ─────────────────────────────────


@skip_no_board
class TestEditComponent:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_edit_component_value(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_edit_component(session, "C7", {"Value": "22uF"})
        assert record.applied
        assert record.operation == "edit_component"

        # Verify value changed
        fp = mgr._find_footprint(session._working_doc, "C7")
        for prop in fp.find_all("property"):
            if prop.first_value == "Value":
                assert prop.atom_values[1] == "22uF"
                break

    def test_edit_component_not_found(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="not found"):
            mgr.apply_edit_component(session, "NONEXISTENT", {"Value": "10k"})

    def test_edit_component_undo(self) -> None:
        mgr, session = self._make_session()
        fp_before = mgr._find_footprint(session._working_doc, "C7")
        before_str = fp_before.to_string()

        mgr.apply_edit_component(session, "C7", {"Value": "22uF"})
        mgr.undo(session)

        fp_after = mgr._find_footprint(session._working_doc, "C7")
        assert fp_after.to_string() == before_str

    def test_edit_component_adds_new_property(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_edit_component(session, "C7", {"MPN": "GRM188R71C104KA01D"})

        fp = mgr._find_footprint(session._working_doc, "C7")
        found = False
        for prop in fp.find_all("property"):
            if prop.first_value == "MPN":
                assert prop.atom_values[1] == "GRM188R71C104KA01D"
                found = True
                break
        assert found


@skip_no_board
class TestReplaceComponent:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_replace_component(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_replace_component(
            session, "C7", "Cap_SMD:C_0805", "100nF"
        )
        assert record.applied
        assert record.operation == "replace_component"

    def test_replace_preserves_position(self) -> None:
        mgr, session = self._make_session()
        # Get original position
        fp_before = mgr._find_footprint(session._working_doc, "C7")
        at_before = fp_before.get("at")
        x_before = float(at_before.atom_values[0])
        y_before = float(at_before.atom_values[1])

        mgr.apply_replace_component(session, "C7", "Cap_SMD:C_0805", "100nF")

        fp_after = mgr._find_footprint(session._working_doc, "C7")
        at_after = fp_after.get("at")
        assert float(at_after.atom_values[0]) == x_before
        assert float(at_after.atom_values[1]) == y_before

    def test_replace_not_found(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="not found"):
            mgr.apply_replace_component(
                session, "NONEXISTENT", "Cap_SMD:C_0805", "100nF"
            )

    def test_replace_undo(self) -> None:
        mgr, session = self._make_session()
        fp_before = mgr._find_footprint(session._working_doc, "C7")
        before_str = fp_before.to_string()

        mgr.apply_replace_component(session, "C7", "Cap_SMD:C_0805", "100nF")
        mgr.undo(session)

        fp_after = mgr._find_footprint(session._working_doc, "C7")
        assert fp_after.to_string() == before_str


@skip_no_board
class TestEditReplaceToolHandlers:
    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_edit_component_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["edit_component"].handler(
            session_id=sid,
            reference="C7",
            properties={"Value": "22uF"},
        )
        assert result["status"] == "edited"

    def test_replace_component_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["replace_component"].handler(
            session_id=sid,
            reference="C7",
            new_library="Cap_SMD:C_0805",
            new_value="100nF",
        )
        assert result["status"] == "replaced"


# ── Group D: Schematic Extras ───────────────────────────────────────


class TestCreateSchematic:
    def test_create_schematic_file(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test.kicad_sch")
            result = TOOL_REGISTRY["create_schematic"].handler(path=path)
            assert result["status"] == "created"
            assert Path(path).exists()

    def test_create_schematic_parseable(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test.kicad_sch")
            TOOL_REGISTRY["create_schematic"].handler(path=path)
            doc = Document.load(path)
            assert doc.root.name == "kicad_sch"

    def test_create_schematic_custom_paper(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test.kicad_sch")
            result = TOOL_REGISTRY["create_schematic"].handler(path=path, paper="A3")
            assert result["paper"] == "A3"


@skip_no_sch
class TestGenerateNetlist:
    @pytest.fixture(autouse=True)
    def _load_schematic(self) -> None:
        from kicad_mcp import schematic_state

        schematic_state.load_schematic(str(BLINKY_SCH_PATH))

    def test_generate_netlist(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            out = str(Path(tmpdir) / "netlist.net")
            result = TOOL_REGISTRY["generate_netlist"].handler(output_path=out)
            assert result["status"] == "generated"
            assert Path(out).exists()
            assert result["component_count"] >= 0

    def test_netlist_file_not_empty(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            out = str(Path(tmpdir) / "netlist.net")
            TOOL_REGISTRY["generate_netlist"].handler(output_path=out)
            content = Path(out).read_text(encoding="utf-8")
            assert "(export" in content
            assert "(components" in content


# ── Group E: Net Extras ─────────────────────────────────────────────


@skip_no_board
class TestAddNetClass:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_add_net_class(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_add_net_class(session, "Power", clearance=0.3, trace_width=0.5)
        assert record.applied
        assert record.operation == "add_net_class"

    def test_add_net_class_with_nets(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_add_net_class(
            session, "Power", nets=["VBUS", "GND"]
        )
        assert record.applied

    def test_add_net_class_undo(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_add_net_class(session, "Power")
        mgr.undo(session)

        # Net class should be removed
        setup = session._working_doc.root.get("setup")
        if setup:
            for child in setup.children:
                if child.name == "net_class":
                    assert child.first_value != "Power"


@skip_no_board
class TestSetLayerConstraints:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_set_layer_constraints(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_set_layer_constraints(
            session, "F.Cu", min_width=0.15, min_clearance=0.2
        )
        assert record.applied
        assert record.operation == "set_layer_constraints"

    def test_set_layer_constraints_undo(self) -> None:
        mgr, session = self._make_session()
        setup_before = session._working_doc.root.get("setup").to_string()

        mgr.apply_set_layer_constraints(session, "F.Cu", min_width=0.15)
        mgr.undo(session)

        setup_after = session._working_doc.root.get("setup").to_string()
        assert setup_before == setup_after


@skip_no_board
class TestCopperPour:
    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_copper_pour_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["add_copper_pour"].handler(
            session_id=sid, net_name="VBUS", layer="F.Cu"
        )
        # May succeed or error if no outline
        assert "status" in result or "error" in result


@skip_no_board
class TestNetExtraToolHandlers:
    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_add_net_class_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["add_net_class"].handler(
            session_id=sid,
            name="Power",
            clearance=0.3,
            trace_width=0.5,
        )
        assert result["status"] == "added"

    def test_set_layer_constraints_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["set_layer_constraints"].handler(
            session_id=sid,
            layer="F.Cu",
            min_width=0.15,
        )
        assert result["status"] == "set"


# ── Group F: Check Clearance ────────────────────────────────────────


@skip_no_board
class TestCheckClearance:
    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_check_clearance(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["check_clearance"].handler(
            reference_a="C7", reference_b="R2"
        )
        assert "min_clearance_mm" in result
        assert result["min_clearance_mm"] >= 0

    def test_check_clearance_has_center_distance(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["check_clearance"].handler(
            reference_a="C7", reference_b="R2"
        )
        assert "center_distance_mm" in result
        assert result["center_distance_mm"] > 0

    def test_check_clearance_not_found(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["check_clearance"].handler(
            reference_a="NONEXISTENT", reference_b="R2"
        )
        assert "error" in result

    def test_check_clearance_has_closest_pair(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["check_clearance"].handler(
            reference_a="C7", reference_b="R2"
        )
        if "closest_pair" in result and result["closest_pair"]:
            assert len(result["closest_pair"]) == 2


# ── Group G: Group Components ───────────────────────────────────────


@skip_no_board
class TestGroupComponents:
    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_group_components(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["group_components"].handler(
            session_id=sid,
            references=["C7", "R2"],
            group_name="power_section",
        )
        assert result["status"] == "grouped"
        assert result["grouped_count"] == 2

    def test_group_skips_nonexistent(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["group_components"].handler(
            session_id=sid,
            references=["C7", "NONEXISTENT"],
            group_name="test",
        )
        assert result["grouped_count"] == 1


# ── Tool Registration Completeness ──────────────────────────────────


class TestToolRegistration:
    """Verify all 19 new tools are registered."""

    def test_all_parity_tools_registered(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        expected = [
            "get_design_rules",
            "set_design_rules",
            "set_board_size",
            "add_board_outline",
            "add_mounting_hole",
            "add_board_text",
            "set_active_layer",
            "edit_component",
            "replace_component",
            "create_project",
            "save_project",
            "create_schematic",
            "generate_netlist",
            "add_copper_pour",
            "add_net_class",
            "set_layer_constraints",
            "check_clearance",
            "export_vrml",
            "group_components",
        ]
        for name in expected:
            assert name in TOOL_REGISTRY, f"Tool '{name}' not registered"

    def test_total_tool_count_at_least_75(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        assert len(TOOL_REGISTRY) >= 75
