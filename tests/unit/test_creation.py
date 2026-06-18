"""Tests for footprint/symbol creation (pure-Python S-expr generation)."""

from __future__ import annotations

from pathlib import Path

from kicad_mcp.sexp import Document
from kicad_mcp.tools.creation import _create_footprint_handler, _create_symbol_handler


class TestCreateFootprint:
    def test_smd_footprint(self, tmp_path: Path) -> None:
        out = tmp_path / "fp.kicad_mod"
        r = _create_footprint_handler(
            str(out),
            "R_0402",
            [
                {
                    "number": "1",
                    "x": -0.5,
                    "y": 0,
                    "width": 0.6,
                    "height": 0.5,
                    "shape": "roundrect",
                },
                {
                    "number": "2",
                    "x": 0.5,
                    "y": 0,
                    "width": 0.6,
                    "height": 0.5,
                    "shape": "roundrect",
                },
            ],
        )
        assert r["status"] == "created"
        assert r["pad_count"] == 2
        doc = Document.load(str(out))
        assert doc.root.name == "footprint"
        assert len(doc.root.find_all("pad")) == 2
        assert doc.root.get("attr").first_value == "smd"

    def test_through_hole_has_drill_and_attr(self, tmp_path: Path) -> None:
        out = tmp_path / "fp.kicad_mod"
        r = _create_footprint_handler(
            str(out),
            "TH",
            [
                {
                    "number": "1",
                    "x": 0,
                    "y": 0,
                    "width": 1.6,
                    "height": 1.6,
                    "shape": "circle",
                    "type": "thru_hole",
                    "drill": 0.8,
                }
            ],
        )
        assert r["status"] == "created"
        doc = Document.load(str(out))
        assert doc.root.get("attr").first_value == "through_hole"
        pad = doc.root.find_all("pad")[0]
        assert pad.get("drill") is not None

    def test_invalid_shape(self, tmp_path: Path) -> None:
        r = _create_footprint_handler(
            str(tmp_path / "f.kicad_mod"), "X", [{"number": "1", "x": 0, "y": 0, "shape": "blob"}]
        )
        assert "error" in r

    def test_no_pads(self, tmp_path: Path) -> None:
        assert "error" in _create_footprint_handler(str(tmp_path / "f.kicad_mod"), "X", [])


class TestCreateSymbol:
    def _pins(self) -> list[dict[str, str]]:
        return [
            {"number": "1", "name": "A", "type": "input", "side": "left"},
            {"number": "2", "name": "B", "type": "output", "side": "right"},
            {"number": "3", "name": "VCC", "type": "power_in", "side": "top"},
        ]

    def test_new_library(self, tmp_path: Path) -> None:
        out = tmp_path / "lib.kicad_sym"
        r = _create_symbol_handler(str(out), "CHIP", self._pins(), footprint="lib:FP")
        assert r["status"] == "created"
        assert r["pin_count"] == 3
        doc = Document.load(str(out))
        assert doc.root.name == "kicad_symbol_lib"
        syms = [s for s in doc.root.find_all("symbol") if s.first_value == "CHIP"]
        assert len(syms) == 1
        # 3 pins live in the unit sub-symbol.
        pins = list(syms[0].find_recursive("pin"))
        assert len(pins) == 3

    def test_append_to_existing(self, tmp_path: Path) -> None:
        out = tmp_path / "lib.kicad_sym"
        _create_symbol_handler(str(out), "CHIP1", self._pins())
        r = _create_symbol_handler(str(out), "CHIP2", self._pins())
        assert r["status"] == "created"
        doc = Document.load(str(out))
        names = {s.first_value for s in doc.root.find_all("symbol")}
        assert {"CHIP1", "CHIP2"} <= names

    def test_duplicate_rejected(self, tmp_path: Path) -> None:
        out = tmp_path / "lib.kicad_sym"
        _create_symbol_handler(str(out), "CHIP", self._pins())
        r = _create_symbol_handler(str(out), "CHIP", self._pins())
        assert "error" in r and "exists" in r["error"]

    def test_invalid_pin_type(self, tmp_path: Path) -> None:
        r = _create_symbol_handler(
            str(tmp_path / "l.kicad_sym"),
            "X",
            [{"number": "1", "name": "A", "type": "wat", "side": "left"}],
        )
        assert "error" in r

    def test_footprint_property_carried(self, tmp_path: Path) -> None:
        out = tmp_path / "lib.kicad_sym"
        _create_symbol_handler(str(out), "CHIP", self._pins(), footprint="mylib:SOT-23")
        doc = Document.load(str(out))
        sym = next(s for s in doc.root.find_all("symbol") if s.first_value == "CHIP")
        fp = next(p for p in sym.find_all("property") if p.first_value == "Footprint")
        assert fp.atom_values[1] == "mylib:SOT-23"
