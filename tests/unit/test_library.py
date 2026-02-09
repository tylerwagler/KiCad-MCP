"""Tests for library search and browsing tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.library import (
    discover_lib_tables,
    get_footprint_details,
    list_footprints_in_library,
    list_symbols_in_library,
    search_footprints,
    search_symbols,
)

# Paths for KiCad 9 installed libraries
SYM_DIR = Path(r"C:\Program Files\KiCad\9.0\share\kicad\symbols")
FP_DIR = Path(r"C:\Program Files\KiCad\9.0\share\kicad\footprints")
DEVICE_LIB = SYM_DIR / "Device.kicad_sym"
RESISTOR_SMD_DIR = FP_DIR / "Resistor_SMD.pretty"

skip_no_kicad = pytest.mark.skipif(
    not SYM_DIR.exists(), reason="KiCad libraries not installed"
)


@skip_no_kicad
class TestDiscoverLibTables:
    def test_discover_returns_both_types(self) -> None:
        tables = discover_lib_tables()
        assert "symbol_libraries" in tables
        assert "footprint_libraries" in tables

    def test_has_symbol_libraries(self) -> None:
        tables = discover_lib_tables()
        assert len(tables["symbol_libraries"]) > 0

    def test_has_footprint_libraries(self) -> None:
        tables = discover_lib_tables()
        assert len(tables["footprint_libraries"]) > 0

    def test_library_entry_has_name(self) -> None:
        tables = discover_lib_tables()
        for entry in tables["symbol_libraries"][:5]:
            assert entry.name != ""

    def test_library_entry_to_dict(self) -> None:
        tables = discover_lib_tables()
        d = tables["symbol_libraries"][0].to_dict()
        assert "name" in d
        assert "type" in d
        assert "uri" in d


@skip_no_kicad
class TestListSymbols:
    def test_list_device_symbols(self) -> None:
        symbols = list_symbols_in_library(DEVICE_LIB)
        assert len(symbols) > 0

    def test_symbol_has_name(self) -> None:
        symbols = list_symbols_in_library(DEVICE_LIB)
        for sym in symbols[:10]:
            assert sym.name != ""

    def test_symbol_has_library(self) -> None:
        symbols = list_symbols_in_library(DEVICE_LIB)
        for sym in symbols[:10]:
            assert sym.library == "Device"

    def test_symbol_full_id(self) -> None:
        symbols = list_symbols_in_library(DEVICE_LIB)
        for sym in symbols[:10]:
            assert sym.full_id.startswith("Device:")

    def test_symbol_has_reference(self) -> None:
        symbols = list_symbols_in_library(DEVICE_LIB)
        # At least some should have a reference prefix
        has_ref = any(s.reference != "" for s in symbols)
        assert has_ref

    def test_symbol_to_dict(self) -> None:
        symbols = list_symbols_in_library(DEVICE_LIB)
        d = symbols[0].to_dict()
        assert "name" in d
        assert "library" in d
        assert "full_id" in d
        assert "reference" in d

    def test_nonexistent_library_returns_empty(self) -> None:
        symbols = list_symbols_in_library(Path("nonexistent.kicad_sym"))
        assert symbols == []


@skip_no_kicad
class TestListFootprints:
    def test_list_resistor_smd(self) -> None:
        footprints = list_footprints_in_library(RESISTOR_SMD_DIR)
        assert len(footprints) > 0

    def test_footprint_has_name(self) -> None:
        footprints = list_footprints_in_library(RESISTOR_SMD_DIR)
        for fp in footprints[:10]:
            assert fp.name != ""

    def test_footprint_has_library(self) -> None:
        footprints = list_footprints_in_library(RESISTOR_SMD_DIR)
        for fp in footprints[:10]:
            assert fp.library == "Resistor_SMD"

    def test_footprint_full_id(self) -> None:
        footprints = list_footprints_in_library(RESISTOR_SMD_DIR)
        for fp in footprints[:10]:
            assert fp.full_id.startswith("Resistor_SMD:")

    def test_footprint_has_pads(self) -> None:
        footprints = list_footprints_in_library(RESISTOR_SMD_DIR)
        has_pads = any(fp.pad_count > 0 for fp in footprints)
        assert has_pads

    def test_footprint_to_dict(self) -> None:
        footprints = list_footprints_in_library(RESISTOR_SMD_DIR)
        d = footprints[0].to_dict()
        assert "name" in d
        assert "library" in d
        assert "pad_count" in d

    def test_nonexistent_library_returns_empty(self) -> None:
        footprints = list_footprints_in_library(Path("nonexistent.pretty"))
        assert footprints == []


@skip_no_kicad
class TestGetFootprintDetails:
    def test_get_details(self) -> None:
        mod_path = RESISTOR_SMD_DIR / "R_0402_1005Metric.kicad_mod"
        if not mod_path.exists():
            pytest.skip("R_0402 footprint not found")
        info = get_footprint_details(mod_path)
        assert info is not None
        assert info.pad_count == 2
        assert info.name == "R_0402_1005Metric"

    def test_nonexistent_returns_none(self) -> None:
        info = get_footprint_details(Path("nonexistent.kicad_mod"))
        assert info is None


@skip_no_kicad
class TestSearchSymbols:
    def test_search_resistor(self) -> None:
        # Restrict to Device library for speed
        from kicad_mcp.schema.library import LibraryEntry
        libs = [LibraryEntry("Device", "KiCad", str(DEVICE_LIB), "")]
        results = search_symbols("Resistor", libraries=libs, max_results=10)
        assert len(results) > 0

    def test_search_respects_max(self) -> None:
        from kicad_mcp.schema.library import LibraryEntry
        libs = [LibraryEntry("Device", "KiCad", str(DEVICE_LIB), "")]
        results = search_symbols("R", libraries=libs, max_results=5)
        assert len(results) <= 5

    def test_search_no_results(self) -> None:
        from kicad_mcp.schema.library import LibraryEntry
        libs = [LibraryEntry("Device", "KiCad", str(DEVICE_LIB), "")]
        results = search_symbols("xyznonexistent99999", libraries=libs)
        assert len(results) == 0


@skip_no_kicad
class TestSearchFootprints:
    def test_search_0402(self) -> None:
        from kicad_mcp.schema.library import LibraryEntry
        libs = [LibraryEntry("Resistor_SMD", "KiCad", str(RESISTOR_SMD_DIR), "")]
        results = search_footprints("0402", libraries=libs, max_results=10)
        assert len(results) > 0

    def test_search_respects_max(self) -> None:
        from kicad_mcp.schema.library import LibraryEntry
        libs = [LibraryEntry("Resistor_SMD", "KiCad", str(RESISTOR_SMD_DIR), "")]
        results = search_footprints("0402", libraries=libs, max_results=5)
        assert len(results) <= 5

    def test_search_no_results(self) -> None:
        from kicad_mcp.schema.library import LibraryEntry
        libs = [LibraryEntry("Resistor_SMD", "KiCad", str(RESISTOR_SMD_DIR), "")]
        results = search_footprints("xyznonexistent99999", libraries=libs)
        assert len(results) == 0


@skip_no_kicad
class TestLibraryToolHandlers:
    def test_list_libraries_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["list_libraries"].handler()
        assert "symbol_libraries" in result
        assert "footprint_libraries" in result
        assert result["symbol_libraries"]["count"] > 0

    def test_search_symbols_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["search_symbols"].handler(
            query="capacitor", library="Device", max_results=10
        )
        assert "count" in result
        assert "symbols" in result

    def test_search_footprints_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["search_footprints"].handler(
            query="0805", library="Resistor_SMD", max_results=10
        )
        assert "count" in result
        assert "footprints" in result

    def test_list_symbols_in_library_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["list_symbols_in_library"].handler(library="Device")
        assert result["library"] == "Device"
        assert result["count"] > 0

    def test_list_symbols_unknown_library(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["list_symbols_in_library"].handler(library="Nonexistent")
        assert "error" in result

    def test_list_footprints_in_library_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["list_footprints_in_library"].handler(library="Resistor_SMD")
        assert result["library"] == "Resistor_SMD"
        assert result["count"] > 0

    def test_get_footprint_details_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["get_footprint_details"].handler(
            library="Resistor_SMD", footprint="R_0402_1005Metric"
        )
        assert result.get("found") is True
        assert result["pad_count"] == 2
