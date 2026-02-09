"""Tests for component placement tools (place, rotate, flip, delete)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.session.manager import SessionManager
from kicad_mcp.sexp import Document

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")

skip_no_board = pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")

# Check if KiCad libraries are available for footprint resolution tests
_RESISTOR_MOD = Path(
    r"C:\Program Files\KiCad\9.0\share\kicad\footprints"
    r"\Resistor_SMD.pretty\R_0402_1005Metric.kicad_mod"
)
skip_no_libs = pytest.mark.skipif(
    not _RESISTOR_MOD.exists(), reason="KiCad footprint libraries not installed"
)


@skip_no_board
class TestRotateComponent:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_rotate_sets_angle(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_rotate(session, "C7", 90)
        assert record.applied
        assert record.operation == "rotate_component"
        # Verify the angle was set
        fp = mgr._find_footprint(session._working_doc, "C7")
        at_node = fp.get("at")
        vals = at_node.atom_values
        assert len(vals) >= 3
        assert float(vals[2]) == 90.0

    def test_rotate_overwrites_existing_angle(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_rotate(session, "C7", 45)
        mgr.apply_rotate(session, "C7", 180)
        fp = mgr._find_footprint(session._working_doc, "C7")
        at_node = fp.get("at")
        assert float(at_node.atom_values[2]) == 180.0

    def test_rotate_not_found(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="not found"):
            mgr.apply_rotate(session, "NONEXISTENT", 90)

    def test_rotate_undo(self) -> None:
        mgr, session = self._make_session()
        # Get original at node
        fp_before = mgr._find_footprint(session._working_doc, "C7")
        at_before = fp_before.get("at").to_string()

        mgr.apply_rotate(session, "C7", 90)
        mgr.undo(session)

        fp_after = mgr._find_footprint(session._working_doc, "C7")
        at_after = fp_after.get("at").to_string()
        assert at_before == at_after


@skip_no_board
class TestFlipComponent:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_flip_changes_layer(self) -> None:
        mgr, session = self._make_session()
        # C7 is on F.Cu
        fp = mgr._find_footprint(session._working_doc, "C7")
        layer_node = fp.get("layer")
        assert layer_node.first_value == "F.Cu"

        record = mgr.apply_flip(session, "C7")
        assert record.applied
        assert record.operation == "flip_component"

        fp = mgr._find_footprint(session._working_doc, "C7")
        layer_node = fp.get("layer")
        assert layer_node.first_value == "B.Cu"

    def test_flip_changes_pad_layers(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_flip(session, "C7")
        fp = mgr._find_footprint(session._working_doc, "C7")
        for pad in fp.find_all("pad"):
            layers_node = pad.get("layers")
            if layers_node:
                layer_vals = layers_node.atom_values
                # F.Cu should now be B.Cu, F.Mask -> B.Mask, F.Paste -> B.Paste
                assert "F.Cu" not in layer_vals
                assert "B.Cu" in layer_vals

    def test_flip_twice_restores(self) -> None:
        mgr, session = self._make_session()
        fp_before = mgr._find_footprint(session._working_doc, "C7")
        layer_before = fp_before.get("layer").first_value

        mgr.apply_flip(session, "C7")
        mgr.apply_flip(session, "C7")

        fp_after = mgr._find_footprint(session._working_doc, "C7")
        assert fp_after.get("layer").first_value == layer_before

    def test_flip_undo(self) -> None:
        mgr, session = self._make_session()
        fp_before = mgr._find_footprint(session._working_doc, "C7")
        before_str = fp_before.to_string()

        mgr.apply_flip(session, "C7")
        mgr.undo(session)

        fp_after = mgr._find_footprint(session._working_doc, "C7")
        assert fp_after.to_string() == before_str


@skip_no_board
class TestDeleteComponent:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_delete_removes_component(self) -> None:
        mgr, session = self._make_session()
        # Count footprints before
        before_count = len(session._working_doc.root.find_all("footprint"))

        record = mgr.apply_delete(session, "C7")
        assert record.applied
        assert record.operation == "delete_component"

        after_count = len(session._working_doc.root.find_all("footprint"))
        assert after_count == before_count - 1

        # Component should not be findable
        assert mgr._find_footprint(session._working_doc, "C7") is None

    def test_delete_not_found(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="not found"):
            mgr.apply_delete(session, "NONEXISTENT")

    def test_delete_undo_restores(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("footprint"))

        mgr.apply_delete(session, "C7")
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("footprint"))
        assert after_count == before_count
        assert mgr._find_footprint(session._working_doc, "C7") is not None


@skip_no_board
class TestPlaceComponent:
    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_place_adds_component(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("footprint"))

        record = mgr.apply_place(
            session,
            footprint_library="Resistor_SMD:R_0402_1005Metric",
            reference="R99",
            value="10k",
            x=50,
            y=25,
            layer="F.Cu",
        )
        assert record.applied
        assert record.operation == "place_component"

        after_count = len(session._working_doc.root.find_all("footprint"))
        assert after_count == before_count + 1

        # Verify the new component is findable
        fp = mgr._find_footprint(session._working_doc, "R99")
        assert fp is not None

    def test_place_correct_position(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_place(session, "Resistor_SMD:R_0402", "R99", "4.7k", 30, 15)

        fp = mgr._find_footprint(session._working_doc, "R99")
        at_node = fp.get("at")
        vals = at_node.atom_values
        assert float(vals[0]) == 30.0
        assert float(vals[1]) == 15.0

    def test_place_correct_layer(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_place(session, "Cap_SMD:C_0805", "C99", "100nF", 10, 10, "B.Cu")

        fp = mgr._find_footprint(session._working_doc, "C99")
        assert fp.get("layer").first_value == "B.Cu"

    def test_place_duplicate_reference_fails(self) -> None:
        mgr, session = self._make_session()
        with pytest.raises(ValueError, match="already exists"):
            mgr.apply_place(session, "Resistor_SMD:R_0402", "C7", "10k", 50, 25)

    def test_place_undo_removes(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("footprint"))

        mgr.apply_place(session, "Resistor_SMD:R_0402", "R99", "10k", 50, 25)
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("footprint"))
        assert after_count == before_count
        assert mgr._find_footprint(session._working_doc, "R99") is None

    def test_place_has_properties(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_place(session, "Resistor_SMD:R_0402", "R99", "10k", 50, 25)

        fp = mgr._find_footprint(session._working_doc, "R99")
        # Check Reference property
        ref_found = False
        val_found = False
        for prop in fp.find_all("property"):
            if prop.first_value == "Reference":
                assert prop.atom_values[1] == "R99"
                ref_found = True
            elif prop.first_value == "Value":
                assert prop.atom_values[1] == "10k"
                val_found = True
        assert ref_found
        assert val_found


@skip_no_board
class TestPlacementToolHandlers:
    """Test the registered tool handlers."""

    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_place_component_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        # Start session first
        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["place_component"].handler(
            session_id=sid,
            footprint_library="Resistor_SMD:R_0402",
            reference="R99",
            value="10k",
            x=50,
            y=25,
        )
        assert result["status"] == "placed"

    def test_rotate_component_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["rotate_component"].handler(session_id=sid, reference="C7", angle=90)
        assert result["status"] == "rotated"

    def test_flip_component_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["flip_component"].handler(session_id=sid, reference="C7")
        assert result["status"] == "flipped"

    def test_delete_component_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        start = TOOL_REGISTRY["start_session"].handler()
        sid = start["session_id"]

        result = TOOL_REGISTRY["delete_component"].handler(session_id=sid, reference="C7")
        assert result["status"] == "deleted"


# ── Library-resolved footprint placement tests ─────────────────────


@skip_no_board
@skip_no_libs
class TestPlaceWithLibraryResolution:
    """Verify place_component creates footprints with pads from KiCad libs."""

    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_place_resolves_pads(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_place(
            session,
            footprint_library="Resistor_SMD:R_0402_1005Metric",
            reference="R99",
            value="10k",
            x=50,
            y=25,
        )
        fp = mgr._find_footprint(session._working_doc, "R99")
        pads = fp.find_all("pad")
        assert len(pads) >= 2, f"Expected pads, got {len(pads)}"

    def test_place_preserves_position_with_library(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_place(
            session,
            footprint_library="Resistor_SMD:R_0402_1005Metric",
            reference="R99",
            value="10k",
            x=42.5,
            y=17.3,
        )
        fp = mgr._find_footprint(session._working_doc, "R99")
        at_node = fp.get("at")
        assert float(at_node.atom_values[0]) == 42.5
        assert float(at_node.atom_values[1]) == 17.3

    def test_place_preserves_reference_with_library(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_place(
            session,
            footprint_library="Resistor_SMD:R_0402_1005Metric",
            reference="R99",
            value="4.7k",
            x=50,
            y=25,
        )
        fp = mgr._find_footprint(session._working_doc, "R99")
        for prop in fp.find_all("property"):
            if prop.first_value == "Reference":
                assert prop.atom_values[1] == "R99"
                break
        else:
            pytest.fail("Reference property not found")

    def test_place_preserves_value_with_library(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_place(
            session,
            footprint_library="Resistor_SMD:R_0402_1005Metric",
            reference="R99",
            value="4.7k",
            x=50,
            y=25,
        )
        fp = mgr._find_footprint(session._working_doc, "R99")
        for prop in fp.find_all("property"):
            if prop.first_value == "Value":
                assert prop.atom_values[1] == "4.7k"
                break
        else:
            pytest.fail("Value property not found")

    def test_place_undo_with_library(self) -> None:
        mgr, session = self._make_session()
        before_count = len(session._working_doc.root.find_all("footprint"))

        mgr.apply_place(
            session,
            footprint_library="Resistor_SMD:R_0402_1005Metric",
            reference="R99",
            value="10k",
            x=50,
            y=25,
        )
        mgr.undo(session)

        after_count = len(session._working_doc.root.find_all("footprint"))
        assert after_count == before_count
        assert mgr._find_footprint(session._working_doc, "R99") is None

    def test_place_library_name_before_at(self) -> None:
        """KiCad requires (footprint "name" ... (at X Y)) — name before at."""
        mgr, session = self._make_session()
        mgr.apply_place(
            session,
            footprint_library="Resistor_SMD:R_0402_1005Metric",
            reference="R99",
            value="10k",
            x=50,
            y=25,
        )
        fp = mgr._find_footprint(session._working_doc, "R99")
        sexp_str = fp.to_string()
        # The library name must appear before (at ...)
        name_pos = sexp_str.find("R_0402_1005Metric")
        at_pos = sexp_str.find("(at ")
        assert name_pos < at_pos, (
            f"Library name at {name_pos} must come before (at ...) at {at_pos}. "
            f"Got: {sexp_str[:100]}..."
        )

    def test_place_pad_has_type_and_shape(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_place(
            session,
            footprint_library="Resistor_SMD:R_0402_1005Metric",
            reference="R99",
            value="10k",
            x=50,
            y=25,
        )
        fp = mgr._find_footprint(session._working_doc, "R99")
        pads = fp.find_all("pad")
        for pad in pads:
            vals = pad.atom_values
            assert len(vals) >= 3, f"Pad missing type/shape: {vals}"


@skip_no_board
class TestPlaceFallbackSkeleton:
    """Verify fallback to skeleton when library is not available."""

    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_place_nonexistent_library_still_places(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_place(
            session,
            footprint_library="NonExistent_Lib:FakeFootprint",
            reference="X99",
            value="test",
            x=10,
            y=10,
        )
        assert record.applied
        fp = mgr._find_footprint(session._working_doc, "X99")
        assert fp is not None

    def test_skeleton_library_name_before_at(self) -> None:
        """Even skeleton footprints must have name before (at ...)."""
        mgr, session = self._make_session()
        mgr.apply_place(
            session,
            footprint_library="NonExistent_Lib:FakeFootprint",
            reference="X99",
            value="test",
            x=10,
            y=10,
        )
        fp = mgr._find_footprint(session._working_doc, "X99")
        sexp_str = fp.to_string()
        name_pos = sexp_str.find("FakeFootprint")
        at_pos = sexp_str.find("(at ")
        assert name_pos < at_pos, f"Name must precede (at ...) in: {sexp_str[:100]}"


@skip_no_board
@skip_no_libs
class TestReplaceWithLibraryResolution:
    """Verify replace_component creates footprints with pads from KiCad libs."""

    def _make_session(self):
        doc = Document.load(str(BLINKY_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_replace_resolves_pads(self) -> None:
        mgr, session = self._make_session()
        mgr.apply_replace_component(session, "C7", "Resistor_SMD:R_0402_1005Metric", "10k")
        fp = mgr._find_footprint(session._working_doc, "C7")
        pads = fp.find_all("pad")
        assert len(pads) >= 2, f"Expected pads, got {len(pads)}"

    def test_replace_preserves_position_with_library(self) -> None:
        mgr, session = self._make_session()
        fp_before = mgr._find_footprint(session._working_doc, "C7")
        at_before = fp_before.get("at")
        x_before = float(at_before.atom_values[0])
        y_before = float(at_before.atom_values[1])

        mgr.apply_replace_component(session, "C7", "Resistor_SMD:R_0402_1005Metric", "10k")

        fp_after = mgr._find_footprint(session._working_doc, "C7")
        at_after = fp_after.get("at")
        assert float(at_after.atom_values[0]) == x_before
        assert float(at_after.atom_values[1]) == y_before
