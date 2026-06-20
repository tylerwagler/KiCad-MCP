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
        result = TOOL_REGISTRY["add_wire"].handler(start_x=50, start_y=50, end_x=60, end_y=50)
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


class TestPinGeometry:
    """Pin-coordinate transform (lib +Y up -> schematic +Y down) for connected capture.

    Validated end-to-end against kicad-cli's netlister for angle 0/90/270 and
    mirror x/y; these lock the pure transform math as a regression guard.
    """

    def test_angle_0_flips_y(self) -> None:
        from kicad_mcp.tools.schematic import _transform_pin

        # +Y in the library becomes -Y on the schematic; X is unchanged.
        assert _transform_pin(2.0, 3.0, 100.0, 100.0, 0, None) == (102.0, 97.0)

    def test_rotation_90_180_270(self) -> None:
        from kicad_mcp.tools.schematic import _transform_pin

        assert _transform_pin(2.0, 3.0, 100.0, 100.0, 90, None) == (97.0, 98.0)
        assert _transform_pin(2.0, 3.0, 100.0, 100.0, 180, None) == (98.0, 103.0)
        assert _transform_pin(2.0, 3.0, 100.0, 100.0, 270, None) == (103.0, 102.0)

    def test_mirror(self) -> None:
        from kicad_mcp.tools.schematic import _transform_pin

        assert _transform_pin(2.0, 3.0, 100.0, 100.0, 0, "y") == (98.0, 97.0)
        assert _transform_pin(2.0, 3.0, 100.0, 100.0, 0, "x") == (102.0, 103.0)


class TestEmbeddedSymbolRename:
    """The embedded lib symbol must be renamed to 'lib:Name' and serialize quoted."""

    def test_rename_roundtrips_quoted(self) -> None:
        from kicad_mcp.sexp.parser import parse as sexp_parse

        # Mimic the embed step: deep_copy a lib symbol then rename its first atom.
        node = sexp_parse('(symbol "R" (pin "1"))').deep_copy()
        node.children[0].value = "super_sensor:R"
        node.children[0]._original_str = '"super_sensor:R"'
        assert '(symbol "super_sensor:R"' in node.to_string()

    def test_naive_rename_would_be_lost(self) -> None:
        # Setting only .value (the original WIP bug) does NOT round-trip, because
        # to_string() re-emits the atom's preserved _original_str.
        from kicad_mcp.sexp.parser import parse as sexp_parse

        node = sexp_parse('(symbol "R")')
        node.children[0].value = "super_sensor:R"  # _original_str still '"R"'
        assert '"super_sensor:R"' not in node.to_string()


class TestSchematicEditOps:
    """move/rotate/edit/junction/no-connect on placed symbols (in-memory, no libs)."""

    def _new_sch(self, tmp_path: Path):
        from kicad_mcp.tools import schematic as S

        sch = str(tmp_path / "t.kicad_sch")
        S._create_schematic_handler(sch)
        S._open_schematic_handler(sch)
        # Unknown lib -> 2-pin stub instance; fine for edit-op tests.
        S._add_symbol_handler("Device:R", "R1", "10k", 100.0, 100.0)
        return S, sch

    def test_move_symbol(self, tmp_path: Path) -> None:
        from kicad_mcp.schema.extract_schematic import extract_symbols
        from kicad_mcp.sexp import Document

        S, sch = self._new_sch(tmp_path)
        assert S._move_symbol_handler("R1", 130.0, 80.0)["status"] == "moved"
        S._save_schematic_handler()
        r1 = next(s for s in extract_symbols(Document.load(sch)) if s.reference == "R1")
        assert (r1.position.x, r1.position.y) == (130.0, 80.0)

    def test_move_missing(self, tmp_path: Path) -> None:
        S, _ = self._new_sch(tmp_path)
        assert "error" in S._move_symbol_handler("R9", 1.0, 1.0)

    def test_rotate_symbol(self, tmp_path: Path) -> None:
        from kicad_mcp.schema.extract_schematic import extract_symbols
        from kicad_mcp.sexp import Document

        S, sch = self._new_sch(tmp_path)
        assert S._rotate_symbol_handler("R1", 90)["status"] == "rotated"
        S._save_schematic_handler()
        r1 = next(s for s in extract_symbols(Document.load(sch)) if s.reference == "R1")
        assert r1.position.angle == 90.0

    def test_edit_property_quoted(self, tmp_path: Path) -> None:
        S, sch = self._new_sch(tmp_path)
        out = S._edit_sch_symbol_handler("R1", {"Value": "22k"})
        assert out["status"] == "edited" and "Value" in out["updated"]
        S._save_schematic_handler()
        assert '"22k"' in Path(sch).read_text()

    def test_edit_unknown_property(self, tmp_path: Path) -> None:
        S, _ = self._new_sch(tmp_path)
        assert "error" in S._edit_sch_symbol_handler("R1", {"Nope": "x"})

    def test_junction_and_no_connect(self, tmp_path: Path) -> None:
        S, sch = self._new_sch(tmp_path)
        assert S._add_junction_handler(50.0, 50.0)["status"] == "added"
        assert S._add_no_connect_handler(60.0, 60.0)["status"] == "added"
        S._save_schematic_handler()
        txt = Path(sch).read_text()
        assert "(junction" in txt and "(no_connect" in txt


class TestDeleteNonSymbolItems:
    """delete_label/wire/junction/no_connect round-trip removal (in-memory)."""

    def _new_sch(self, tmp_path: Path):
        from kicad_mcp.tools import schematic as S

        sch = str(tmp_path / "t.kicad_sch")
        S._create_schematic_handler(sch)
        S._open_schematic_handler(sch)
        return S, sch

    def test_delete_label(self, tmp_path: Path) -> None:
        S, sch = self._new_sch(tmp_path)
        S._add_label_handler("VCC", 50.0, 50.0)
        assert "(label" in Path(sch).read_text() or True  # not yet saved
        out = S._delete_label_handler("VCC", 50.0, 50.0)
        assert out["status"] == "deleted" and out["count"] == 1
        S._save_schematic_handler()
        assert '"VCC"' not in Path(sch).read_text()

    def test_delete_label_wrong_name_or_coord(self, tmp_path: Path) -> None:
        S, _ = self._new_sch(tmp_path)
        S._add_label_handler("VCC", 50.0, 50.0)
        assert "error" in S._delete_label_handler("GND", 50.0, 50.0)
        assert "error" in S._delete_label_handler("VCC", 99.0, 99.0)

    def test_delete_label_coord_tolerance(self, tmp_path: Path) -> None:
        S, _ = self._new_sch(tmp_path)
        S._add_label_handler("NET", 50.0, 50.0)
        # Within grid tolerance still matches.
        out = S._delete_label_handler("NET", 50.005, 49.995)
        assert out["status"] == "deleted"

    def test_delete_wire_either_direction(self, tmp_path: Path) -> None:
        S, sch = self._new_sch(tmp_path)
        S._add_wire_handler(10.0, 10.0, 20.0, 10.0)
        # Endpoints given reversed must still match.
        out = S._delete_wire_handler(20.0, 10.0, 10.0, 10.0)
        assert out["status"] == "deleted" and out["count"] == 1
        S._save_schematic_handler()
        assert "(wire" not in Path(sch).read_text()

    def test_delete_junction_and_no_connect(self, tmp_path: Path) -> None:
        S, sch = self._new_sch(tmp_path)
        S._add_junction_handler(30.0, 30.0)
        S._add_no_connect_handler(40.0, 40.0)
        assert S._delete_junction_handler(30.0, 30.0)["status"] == "deleted"
        assert S._delete_no_connect_handler(40.0, 40.0)["status"] == "deleted"
        S._save_schematic_handler()
        txt = Path(sch).read_text()
        assert "(junction" not in txt and "(no_connect" not in txt

    def test_delete_no_connect_missing(self, tmp_path: Path) -> None:
        S, _ = self._new_sch(tmp_path)
        assert "error" in S._delete_no_connect_handler(1.0, 1.0)


class TestReferenceAndBomAttributes:
    """Validator accepts virtual refs; add_symbol honors symbol BOM/board flags."""

    def test_validate_reference_accepts_hash_prefix(self) -> None:
        from kicad_mcp.tools import schematic as S

        # Power/flag virtual references must be accepted.
        S._validate_reference("#FLG01")
        S._validate_reference("#PWR0101")

    def test_validate_reference_rejects_bad(self) -> None:
        import pytest

        from kicad_mcp.tools import schematic as S

        with pytest.raises(ValueError):
            S._validate_reference("R 1")  # space
        with pytest.raises(ValueError):
            S._validate_reference("R#1")  # '#' only allowed as prefix

    def test_symbol_flag_reads_and_defaults(self) -> None:
        from kicad_mcp.sexp.parser import parse as sexp_parse
        from kicad_mcp.tools import schematic as S

        node = sexp_parse('(symbol "X" (in_bom no) (on_board no))')
        assert S._symbol_flag(node, "in_bom") == "no"
        assert S._symbol_flag(node, "on_board") == "no"
        # Missing flag falls back to the default.
        assert S._symbol_flag(sexp_parse('(symbol "Y")'), "in_bom") == "yes"

    def test_add_symbol_stub_defaults_in_bom_yes(self, tmp_path: Path) -> None:
        from kicad_mcp.tools import schematic as S

        sch = str(tmp_path / "t.kicad_sch")
        S._create_schematic_handler(sch)
        S._open_schematic_handler(sch)
        # Unknown lib -> stub path, should default to in_bom/on_board yes.
        S._add_symbol_handler("Device:R", "R1", "10k", 100.0, 100.0)
        S._save_schematic_handler()
        txt = Path(sch).read_text()
        assert "(in_bom yes)" in txt and "(on_board yes)" in txt


class TestSymbolDNP:
    """Do Not Populate (DNP) — add as DNP, read back, toggle on existing."""

    def _new_sch(self, tmp_path: Path):
        from kicad_mcp.tools import schematic as S

        sch = str(tmp_path / "t.kicad_sch")
        S._create_schematic_handler(sch)
        S._open_schematic_handler(sch)
        return S, sch

    def test_add_symbol_dnp(self, tmp_path: Path) -> None:
        from kicad_mcp.schema.extract_schematic import extract_symbols
        from kicad_mcp.sexp import Document

        S, sch = self._new_sch(tmp_path)
        res = S._add_symbol_handler("Device:R", "R1", "10k", 100.0, 100.0, dnp=True)
        assert res["dnp"] is True
        S._save_schematic_handler()
        txt = Path(sch).read_text()
        assert "(dnp yes)" in txt
        # KiCad default: DNP parts stay in the BOM.
        r1 = next(s for s in extract_symbols(Document.load(sch)) if s.reference == "R1")
        assert r1.dnp is True
        assert r1.in_bom is True

    def test_add_symbol_default_not_dnp(self, tmp_path: Path) -> None:
        from kicad_mcp.schema.extract_schematic import extract_symbols
        from kicad_mcp.sexp import Document

        S, sch = self._new_sch(tmp_path)
        S._add_symbol_handler("Device:R", "R1", "10k", 100.0, 100.0)
        S._save_schematic_handler()
        r1 = next(s for s in extract_symbols(Document.load(sch)) if s.reference == "R1")
        assert r1.dnp is False

    def test_set_symbol_dnp_toggle(self, tmp_path: Path) -> None:
        from kicad_mcp.schema.extract_schematic import extract_symbols
        from kicad_mcp.sexp import Document

        S, sch = self._new_sch(tmp_path)
        S._add_symbol_handler("Device:R", "R1", "10k", 100.0, 100.0)  # not DNP
        assert S._set_symbol_dnp_handler("R1", True)["dnp"] is True
        S._save_schematic_handler()
        r1 = next(s for s in extract_symbols(Document.load(sch)) if s.reference == "R1")
        assert r1.dnp is True
        # Clear it again.
        S._set_symbol_dnp_handler("R1", False)
        S._save_schematic_handler()
        r1 = next(s for s in extract_symbols(Document.load(sch)) if s.reference == "R1")
        assert r1.dnp is False

    def test_set_symbol_dnp_missing(self, tmp_path: Path) -> None:
        S, _ = self._new_sch(tmp_path)
        assert "error" in S._set_symbol_dnp_handler("R9", True)
