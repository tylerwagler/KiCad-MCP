"""Tests for schematic support (schema, extraction, tools)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.schema.extract_schematic import (
    extract_labels,
    extract_schematic_summary,
    extract_symbols,
    extract_wires,
)
from kicad_mcp.sexp import Document

# Use the diagnostic_v3 schematic as test fixture
SCH_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\diagnostic_test_v3\diagnostic_v3.kicad_sch")
SCH_V3 = Path(r"C:\Users\tyler\Dev\repos\test_PCB\diag_v3_sch.kicad_sch")

skip_no_sch = pytest.mark.skipif(not SCH_PATH.exists(), reason="Schematic fixture not available")
skip_no_v3 = pytest.mark.skipif(not SCH_V3.exists(), reason="v3 schematic not available")


@skip_no_sch
class TestExtractSymbols:
    def test_extract_symbols_count(self) -> None:
        doc = Document.load(str(SCH_PATH))
        symbols = extract_symbols(doc)
        # diagnostic_v3 has template symbols
        assert len(symbols) > 0

    def test_symbol_has_lib_id(self) -> None:
        doc = Document.load(str(SCH_PATH))
        symbols = extract_symbols(doc)
        for sym in symbols:
            assert sym.lib_id != ""

    def test_symbol_has_reference(self) -> None:
        doc = Document.load(str(SCH_PATH))
        symbols = extract_symbols(doc)
        for sym in symbols:
            assert sym.reference != ""

    def test_symbol_has_uuid(self) -> None:
        doc = Document.load(str(SCH_PATH))
        symbols = extract_symbols(doc)
        for sym in symbols:
            assert sym.uuid != ""

    def test_symbol_has_pins(self) -> None:
        doc = Document.load(str(SCH_PATH))
        symbols = extract_symbols(doc)
        # At least some symbols should have pins
        has_pins = any(len(s.pins) > 0 for s in symbols)
        assert has_pins

    def test_symbol_to_dict(self) -> None:
        doc = Document.load(str(SCH_PATH))
        symbols = extract_symbols(doc)
        d = symbols[0].to_dict()
        assert "lib_id" in d
        assert "reference" in d
        assert "value" in d
        assert "position" in d
        assert "uuid" in d


@skip_no_sch
class TestExtractSchematicSummary:
    def test_summary_fields(self) -> None:
        doc = Document.load(str(SCH_PATH))
        summary = extract_schematic_summary(doc)
        assert summary.version != ""
        assert summary.symbol_count > 0
        assert summary.lib_symbol_count > 0

    def test_summary_to_dict(self) -> None:
        doc = Document.load(str(SCH_PATH))
        summary = extract_schematic_summary(doc)
        d = summary.to_dict()
        assert "version" in d
        assert "symbol_count" in d
        assert "symbols" in d
        assert "wires" in d
        assert "labels" in d

    def test_wires_list(self) -> None:
        doc = Document.load(str(SCH_PATH))
        wires = extract_wires(doc)
        # May or may not have wires depending on schematic
        assert isinstance(wires, list)

    def test_labels_list(self) -> None:
        doc = Document.load(str(SCH_PATH))
        labels = extract_labels(doc)
        assert isinstance(labels, list)


@skip_no_sch
class TestSchematicState:
    def test_load_schematic(self) -> None:
        from kicad_mcp import schematic_state

        summary = schematic_state.load_schematic(str(SCH_PATH))
        assert summary.symbol_count > 0
        assert schematic_state.is_loaded()

    def test_get_symbols(self) -> None:
        from kicad_mcp import schematic_state

        schematic_state.load_schematic(str(SCH_PATH))
        symbols = schematic_state.get_symbols()
        assert len(symbols) > 0


@skip_no_sch
class TestSchematicToolHandlers:
    def test_open_schematic_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["open_schematic"].handler(schematic_path=str(SCH_PATH))
        assert result["status"] == "ok"
        assert "summary" in result

    def test_get_schematic_info_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        TOOL_REGISTRY["open_schematic"].handler(schematic_path=str(SCH_PATH))
        result = TOOL_REGISTRY["get_schematic_info"].handler()
        assert "symbol_count" in result

    def test_list_symbols_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        TOOL_REGISTRY["open_schematic"].handler(schematic_path=str(SCH_PATH))
        result = TOOL_REGISTRY["list_sch_symbols"].handler()
        assert result["count"] > 0
        assert len(result["symbols"]) > 0

    def test_find_symbol_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        TOOL_REGISTRY["open_schematic"].handler(schematic_path=str(SCH_PATH))
        # Get first reference
        syms = TOOL_REGISTRY["list_sch_symbols"].handler()
        ref = syms["symbols"][0]["reference"]

        result = TOOL_REGISTRY["find_sch_symbol"].handler(reference=ref)
        assert result["found"]

    def test_find_symbol_not_found(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        TOOL_REGISTRY["open_schematic"].handler(schematic_path=str(SCH_PATH))
        result = TOOL_REGISTRY["find_sch_symbol"].handler(reference="NONEXISTENT")
        assert not result["found"]


@skip_no_v3
class TestSchematicMutation:
    def test_add_and_delete_symbol(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        TOOL_REGISTRY["open_schematic"].handler(schematic_path=str(SCH_V3))
        before = TOOL_REGISTRY["list_sch_symbols"].handler()
        before_count = before["count"]

        # Add a symbol
        result = TOOL_REGISTRY["add_symbol"].handler(
            lib_id="Device:R", reference="R99", value="10k", x=50, y=50
        )
        assert result["status"] == "added"

        after = TOOL_REGISTRY["list_sch_symbols"].handler()
        assert after["count"] == before_count + 1

        # Delete it
        result = TOOL_REGISTRY["delete_symbol"].handler(reference="R99")
        assert result["status"] == "deleted"

        final = TOOL_REGISTRY["list_sch_symbols"].handler()
        assert final["count"] == before_count

    def test_add_wire(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        TOOL_REGISTRY["open_schematic"].handler(schematic_path=str(SCH_V3))
        result = TOOL_REGISTRY["add_wire"].handler(
            start_x=50, start_y=50, end_x=60, end_y=50
        )
        assert result["status"] == "added"
        assert "uuid" in result

    def test_add_label(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        TOOL_REGISTRY["open_schematic"].handler(schematic_path=str(SCH_V3))
        result = TOOL_REGISTRY["add_label"].handler(name="VCC", x=50, y=50)
        assert result["status"] == "added"
        assert result["name"] == "VCC"

    def test_add_duplicate_symbol_fails(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        TOOL_REGISTRY["open_schematic"].handler(schematic_path=str(SCH_V3))
        # Get first existing reference
        syms = TOOL_REGISTRY["list_sch_symbols"].handler()
        ref = syms["symbols"][0]["reference"]

        result = TOOL_REGISTRY["add_symbol"].handler(
            lib_id="Device:R", reference=ref, value="10k", x=50, y=50
        )
        assert "error" in result
