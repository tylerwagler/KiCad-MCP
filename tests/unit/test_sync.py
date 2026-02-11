"""Tests for schematic-PCB sync (cross-reference, forward/back annotation)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from kicad_mcp.schema.board import Footprint
from kicad_mcp.schema.common import Position
from kicad_mcp.schema.schematic import SchSymbol
from kicad_mcp.sexp import Document
from kicad_mcp.sexp.parser import parse as sexp_parse
from kicad_mcp.sync import (
    _update_property,
    back_annotate,
    cross_reference,
    forward_annotate,
)

# ── Helpers ─────────────────────────────────────────────────────────


def _make_symbol(
    reference: str,
    value: str = "10k",
    footprint: str = "",
    on_board: bool = True,
) -> SchSymbol:
    props: dict[str, str] = {"Reference": reference, "Value": value}
    if footprint:
        props["Footprint"] = footprint
    return SchSymbol(
        lib_id="Device:R",
        reference=reference,
        value=value,
        position=Position(0, 0),
        unit=1,
        uuid="fake-uuid",
        on_board=on_board,
        properties=props,
    )


def _make_footprint(
    reference: str,
    value: str = "10k",
    library: str = "Resistor_SMD:R_0805_2012Metric",
) -> Footprint:
    return Footprint(
        library=library,
        reference=reference,
        value=value,
        position=Position(0, 0),
        layer="F.Cu",
    )


_BOARD_TEMPLATE = """\
(kicad_pcb (version 20241229)
  (footprint "Resistor_SMD:R_0805_2012Metric"
    (property "Reference" "R1" (at 0 0 0))
    (property "Value" "10k" (at 0 1 0)))
  (footprint "Capacitor_SMD:C_0805_2012Metric"
    (property "Reference" "C1" (at 0 0 0))
    (property "Value" "100nF" (at 0 1 0))))"""

_SCH_TEMPLATE = """\
(kicad_sch (version 20231120) (generator "kicad_mcp")
  (lib_symbols)
  (symbol (lib_id "Device:R") (at 0 0 0) (unit 1) (in_bom yes) (on_board yes)
    (uuid "aaa")
    (property "Reference" "R1" (at 0 0 0))
    (property "Value" "10k" (at 0 1 0))
    (property "Footprint" "Resistor_SMD:R_0805_2012Metric" (at 0 0 0)))
  (symbol (lib_id "Device:C") (at 10 0 0) (unit 1) (in_bom yes) (on_board yes)
    (uuid "bbb")
    (property "Reference" "C1" (at 10 0 0))
    (property "Value" "100nF" (at 10 1 0))
    (property "Footprint" "Capacitor_SMD:C_0805_2012Metric" (at 10 0 0))))"""


def _make_board_doc(text: str = _BOARD_TEMPLATE) -> Document:
    root = sexp_parse(text)
    return Document(path=Path("test.kicad_pcb"), root=root, raw_text=text)


def _make_sch_doc(text: str = _SCH_TEMPLATE) -> Document:
    root = sexp_parse(text)
    return Document(path=Path("test.kicad_sch"), root=root, raw_text=text)


# ── TestCrossReference ──────────────────────────────────────────────


class TestCrossReference:
    def test_all_matched(self) -> None:
        symbols = [_make_symbol("R1", "10k"), _make_symbol("C1", "100nF")]
        footprints = [_make_footprint("R1", "10k"), _make_footprint("C1", "100nF")]
        result = cross_reference(symbols, footprints)
        assert result["matched"] == 2
        assert result["missing_on_board"] == []
        assert result["missing_in_schematic"] == []
        assert result["value_mismatches"] == []
        assert result["footprint_mismatches"] == []

    def test_missing_on_board(self) -> None:
        symbols = [_make_symbol("R1"), _make_symbol("R2")]
        footprints = [_make_footprint("R1")]
        result = cross_reference(symbols, footprints)
        assert result["missing_on_board"] == ["R2"]
        assert result["matched"] == 1

    def test_missing_in_schematic(self) -> None:
        symbols = [_make_symbol("R1")]
        footprints = [_make_footprint("R1"), _make_footprint("R2")]
        result = cross_reference(symbols, footprints)
        assert result["missing_in_schematic"] == ["R2"]

    def test_value_mismatch(self) -> None:
        symbols = [_make_symbol("R1", "10k")]
        footprints = [_make_footprint("R1", "4.7k")]
        result = cross_reference(symbols, footprints)
        assert len(result["value_mismatches"]) == 1
        mm = result["value_mismatches"][0]
        assert mm["reference"] == "R1"
        assert mm["schematic_value"] == "10k"
        assert mm["board_value"] == "4.7k"
        assert result["matched"] == 0

    def test_footprint_mismatch(self) -> None:
        symbols = [_make_symbol("R1", "10k", footprint="Resistor_SMD:R_0402")]
        footprints = [_make_footprint("R1", "10k", library="Resistor_SMD:R_0805")]
        result = cross_reference(symbols, footprints)
        assert len(result["footprint_mismatches"]) == 1
        mm = result["footprint_mismatches"][0]
        assert mm["schematic_footprint"] == "Resistor_SMD:R_0402"
        assert mm["board_footprint"] == "Resistor_SMD:R_0805"

    def test_on_board_false_skipped(self) -> None:
        symbols = [_make_symbol("R1", on_board=True), _make_symbol("R2", on_board=False)]
        footprints = [_make_footprint("R1")]
        result = cross_reference(symbols, footprints)
        assert result["matched"] == 1
        assert result["missing_on_board"] == []
        assert "R2" not in result["missing_on_board"]

    def test_empty_inputs(self) -> None:
        result = cross_reference([], [])
        assert result["matched"] == 0
        assert result["missing_on_board"] == []
        assert result["missing_in_schematic"] == []

    def test_summary_string(self) -> None:
        symbols = [_make_symbol("R1")]
        footprints = [_make_footprint("R1")]
        result = cross_reference(symbols, footprints)
        assert "1/1 components in sync" in result["summary"]

    def test_footprint_empty_string_no_mismatch(self) -> None:
        """Empty schematic footprint should not trigger a mismatch."""
        symbols = [_make_symbol("R1", "10k", footprint="")]
        footprints = [_make_footprint("R1", "10k")]
        result = cross_reference(symbols, footprints)
        assert result["footprint_mismatches"] == []
        assert result["matched"] == 1


# ── TestForwardAnnotate ─────────────────────────────────────────────


class TestForwardAnnotate:
    def test_value_updated(self) -> None:
        symbols = [_make_symbol("R1", "4.7k")]
        doc = _make_board_doc()
        result = forward_annotate(symbols, doc)
        assert "R1" in result["updated"]
        assert result["errors"] == []
        # Verify the S-expr was actually modified
        for fp_node in doc.root.find_all("footprint"):
            for prop in fp_node.find_all("property"):
                if prop.first_value == "Reference":
                    vals = prop.atom_values
                    if len(vals) > 1 and vals[1] == "R1":
                        for vprop in fp_node.find_all("property"):
                            if vprop.first_value == "Value":
                                assert vprop.atom_values[1] == "4.7k"

    def test_missing_component_flagged(self) -> None:
        symbols = [_make_symbol("R1"), _make_symbol("R99")]
        doc = _make_board_doc()
        result = forward_annotate(symbols, doc)
        assert "R99" in result["not_on_board"]

    def test_no_changes_needed(self) -> None:
        symbols = [_make_symbol("R1", "10k"), _make_symbol("C1", "100nF")]
        doc = _make_board_doc()
        result = forward_annotate(symbols, doc)
        assert result["updated"] == []
        assert result["not_on_board"] == []
        assert result["errors"] == []

    def test_on_board_false_skipped(self) -> None:
        symbols = [_make_symbol("R1", "999", on_board=False)]
        doc = _make_board_doc()
        result = forward_annotate(symbols, doc)
        assert result["updated"] == []
        assert result["not_on_board"] == []

    def test_multiple_updates(self) -> None:
        symbols = [_make_symbol("R1", "4.7k"), _make_symbol("C1", "10uF")]
        doc = _make_board_doc()
        result = forward_annotate(symbols, doc)
        assert sorted(result["updated"]) == ["C1", "R1"]


# ── TestBackAnnotate ────────────────────────────────────────────────


class TestBackAnnotate:
    def test_value_updated(self) -> None:
        footprints = [_make_footprint("R1", "4.7k")]
        doc = _make_sch_doc()
        result = back_annotate(footprints, doc)
        assert "R1" in result["updated"]
        assert result["errors"] == []
        # Verify S-expr was actually modified
        for sym_node in doc.root.find_all("symbol"):
            lib_id = sym_node.get("lib_id")
            if lib_id is None:
                continue
            for prop in sym_node.find_all("property"):
                if prop.first_value == "Reference" and prop.atom_values[1] == "R1":
                    for vprop in sym_node.find_all("property"):
                        if vprop.first_value == "Value":
                            assert vprop.atom_values[1] == "4.7k"

    def test_missing_in_schematic_flagged(self) -> None:
        footprints = [_make_footprint("R1"), _make_footprint("R99")]
        doc = _make_sch_doc()
        result = back_annotate(footprints, doc)
        assert "R99" in result["not_in_schematic"]

    def test_no_changes_needed(self) -> None:
        footprints = [_make_footprint("R1", "10k"), _make_footprint("C1", "100nF")]
        doc = _make_sch_doc()
        result = back_annotate(footprints, doc)
        assert result["updated"] == []
        assert result["not_in_schematic"] == []
        assert result["errors"] == []

    def test_multiple_updates(self) -> None:
        footprints = [_make_footprint("R1", "4.7k"), _make_footprint("C1", "10uF")]
        doc = _make_sch_doc()
        result = back_annotate(footprints, doc)
        assert sorted(result["updated"]) == ["C1", "R1"]


# ── TestUpdateProperty ──────────────────────────────────────────────


class TestUpdateProperty:
    def test_update_existing(self) -> None:
        node = sexp_parse('(footprint (property "Value" "old" (at 0 0 0)))')
        assert _update_property(node, "Value", "new") is True
        prop = node.find_all("property")[0]
        assert prop.atom_values[1] == "new"

    def test_missing_property(self) -> None:
        node = sexp_parse('(footprint (property "Reference" "R1" (at 0 0 0)))')
        assert _update_property(node, "Value", "10k") is False

    def test_preserves_other_properties(self) -> None:
        node = sexp_parse(
            '(footprint (property "Reference" "R1" (at 0 0 0)) (property "Value" "old" (at 0 1 0)))'
        )
        _update_property(node, "Value", "new")
        ref_prop = node.find_all("property")[0]
        assert ref_prop.atom_values[1] == "R1"


# ── TestToolHandlers ────────────────────────────────────────────────


class TestToolHandlers:
    def test_tools_registered(self) -> None:
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        assert "cross_reference_check" in TOOL_REGISTRY
        assert "forward_annotate" in TOOL_REGISTRY
        assert "back_annotate" in TOOL_REGISTRY

    def test_tools_in_sync_category(self) -> None:
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        assert TOOL_REGISTRY["cross_reference_check"].category == "sync"
        assert TOOL_REGISTRY["forward_annotate"].category == "sync"
        assert TOOL_REGISTRY["back_annotate"].category == "sync"

    def test_tools_are_routed(self) -> None:
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        assert TOOL_REGISTRY["cross_reference_check"].direct is False
        assert TOOL_REGISTRY["forward_annotate"].direct is False
        assert TOOL_REGISTRY["back_annotate"].direct is False

    def test_cross_reference_no_board(self) -> None:
        from kicad_mcp.tools.sync import _cross_reference_check_handler

        with patch("kicad_mcp.state.is_loaded", return_value=False):
            result = _cross_reference_check_handler()
        assert "error" in result

    def test_cross_reference_no_schematic(self) -> None:
        from kicad_mcp.tools.sync import _cross_reference_check_handler

        with (
            patch("kicad_mcp.state.is_loaded", return_value=True),
            patch("kicad_mcp.schematic_state.is_loaded", return_value=False),
        ):
            result = _cross_reference_check_handler()
        assert "error" in result

    def test_forward_annotate_no_board(self) -> None:
        from kicad_mcp.tools.sync import _forward_annotate_handler

        with patch("kicad_mcp.state.is_loaded", return_value=False):
            result = _forward_annotate_handler()
        assert "error" in result

    def test_back_annotate_no_schematic(self) -> None:
        from kicad_mcp.tools.sync import _back_annotate_handler

        with (
            patch("kicad_mcp.state.is_loaded", return_value=True),
            patch("kicad_mcp.schematic_state.is_loaded", return_value=False),
        ):
            result = _back_annotate_handler()
        assert "error" in result
