"""Tests for hierarchical (multi-sheet) schematic parsing and resolution."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import kicad_mcp.tools  # noqa: F401  (registers tools)
from kicad_mcp.schema.extract_schematic import (
    extract_hierarchical_labels,
    extract_schematic_summary,
    extract_sheets,
    extract_symbols,
)
from kicad_mcp.schema.hierarchy import build_hierarchy
from kicad_mcp.sexp import Document
from kicad_mcp.tools import hierarchy as H
from kicad_mcp.tools import schematic as S

FIXTURES = Path(__file__).parent.parent / "fixtures" / "hierarchy"
ROOT = str(FIXTURES / "root.kicad_sch")
CHILD = str(FIXTURES / "child.kicad_sch")

ROOT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
S1 = "11111111-1111-1111-1111-111111111111"
S2 = "22222222-2222-2222-2222-222222222222"


# ── Phase 1: extraction ─────────────────────────────────────────────


class TestSheetExtraction:
    def test_root_sheets(self):
        sheets = extract_sheets(Document.load(ROOT))
        assert len(sheets) == 2
        by_name = {s.name: s for s in sheets}
        assert by_name["amp_left"].file == "child.kicad_sch"
        assert by_name["amp_left"].uuid == S1
        assert by_name["amp_left"].page == "2"
        assert by_name["amp_right"].uuid == S2
        assert by_name["amp_right"].page == "3"

    def test_sheet_pins(self):
        sheets = extract_sheets(Document.load(ROOT))
        pins = sheets[0].pins
        assert len(pins) == 1
        assert pins[0].name == "IN"
        assert pins[0].shape == "input"

    def test_reused_file(self):
        # Both sheets point at the same child file.
        files = {s.file for s in extract_sheets(Document.load(ROOT))}
        assert files == {"child.kicad_sch"}

    def test_hierarchical_labels(self):
        hl = extract_hierarchical_labels(Document.load(CHILD))
        assert len(hl) == 1
        assert hl[0].name == "IN"
        assert hl[0].shape == "input"

    def test_symbol_instances_multi(self):
        syms = extract_symbols(Document.load(CHILD))
        assert len(syms) == 1
        sym = syms[0]
        assert len(sym.instances) == 2
        refs = {i.path: i.reference for i in sym.instances}
        assert refs[f"/{ROOT_UUID}/{S1}"] == "R1"
        assert refs[f"/{ROOT_UUID}/{S2}"] == "R2"

    def test_summary_includes_hierarchy(self):
        d = extract_schematic_summary(Document.load(ROOT)).to_dict()
        assert d["sheet_count"] == 2
        assert len(d["sheets"]) == 2
        c = extract_schematic_summary(Document.load(CHILD)).to_dict()
        assert c["hierarchical_label_count"] == 1


# ── Phase 2: tree resolution ────────────────────────────────────────


class TestBuildHierarchy:
    def test_tree_shape(self):
        h = build_hierarchy(ROOT)
        assert h.root.instance_path == f"/{ROOT_UUID}"
        assert len(h.root.children) == 2
        paths = {c.instance_path for c in h.root.children}
        assert paths == {f"/{ROOT_UUID}/{S1}", f"/{ROOT_UUID}/{S2}"}

    def test_reused_file_loaded_once(self):
        h = build_hierarchy(ROOT)
        # root + child = 2 unique files even though child is placed twice.
        assert len(h.docs) == 2

    def test_enumerate_components_distinct_refs(self):
        comps = build_hierarchy(ROOT).enumerate_components()
        refs = sorted(c.reference for c in comps)
        assert refs == ["R1", "R2"]
        # Each instance reports the sheet it belongs to.
        by_ref = {c.reference: c for c in comps}
        assert by_ref["R1"].sheet_name == "amp_left"
        assert by_ref["R2"].sheet_name == "amp_right"
        assert by_ref["R1"].value == "10k"

    def test_find_node(self):
        h = build_hierarchy(ROOT)
        node = h.find_node(f"/{ROOT_UUID}/{S2}")
        assert node is not None
        assert node.name == "amp_right"
        assert h.find_node("/nonexistent") is None

    def test_iter_nodes_count(self):
        assert len(list(build_hierarchy(ROOT).iter_nodes())) == 3  # root + 2

    def test_missing_sheetfile_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.kicad_sch")
            Path(p).write_text(
                '(kicad_sch (version 20260306) (generator "x")'
                ' (uuid "10000000-0000-0000-0000-000000000000") (paper "A4") (lib_symbols)\n'
                '  (sheet (at 1 1) (size 2 2) (uuid "20000000-0000-0000-0000-000000000000")\n'
                '    (property "Sheetname" "gone") (property "Sheetfile" "nope.kicad_sch")\n'
                '    (instances (project "x" (path "/10000000-0000-0000-0000-000000000000"'
                ' (page "2")))))\n'
                '  (sheet_instances (path "/" (page "1"))))'
            )
            h = build_hierarchy(p)
            child = h.root.children[0]
            assert child.missing is True
            assert child.is_cycle is False

    def test_cycle_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "loop.kicad_sch")
            Path(p).write_text(
                '(kicad_sch (version 20260306) (generator "x")'
                ' (uuid "30000000-0000-0000-0000-000000000000") (paper "A4") (lib_symbols)\n'
                '  (sheet (at 1 1) (size 2 2) (uuid "40000000-0000-0000-0000-000000000000")\n'
                '    (property "Sheetname" "self") (property "Sheetfile" "loop.kicad_sch")\n'
                '    (instances (project "x" (path "/30000000-0000-0000-0000-000000000000"'
                ' (page "2")))))\n'
                '  (sheet_instances (path "/" (page "1"))))'
            )
            h = build_hierarchy(p)
            assert any(n.is_cycle for n in h.iter_nodes())
            # cycle node has no further children (recursion stopped)
            cyc = next(n for n in h.iter_nodes() if n.is_cycle)
            assert cyc.children == []


# ── Phase 3: tools (read + edit) ─────────────────────────────────────


@pytest.fixture
def loaded(tmp_path):
    """Copy the fixture to a temp dir and open it as a hierarchy."""
    import shutil

    for f in ("root.kicad_sch", "child.kicad_sch"):
        shutil.copy(FIXTURES / f, tmp_path / f)
    root = str(tmp_path / "root.kicad_sch")
    H._open_hierarchy_handler(root)
    return tmp_path, root


class TestHierarchyReadTools:
    def test_open_hierarchy(self, loaded):
        _, root = loaded
        r = H._open_hierarchy_handler(root)
        assert r["status"] == "ok"
        assert r["sheet_count"] == 3
        assert r["component_count"] == 2
        assert r["missing_sheets"] == []

    def test_list_hierarchical_symbols(self, loaded):
        comps = H._list_hierarchical_symbols_handler()["components"]
        assert sorted(c["reference"] for c in comps) == ["R1", "R2"]

    def test_list_sheets(self, loaded):
        sheets = H._list_sheets_handler()
        assert sheets["count"] == 2
        assert {s["name"] for s in sheets["sheets"]} == {"amp_left", "amp_right"}

    def test_select_sheet(self, loaded):
        tree = H._get_sheet_hierarchy_handler()
        left = tree["children"][0]["instance_path"]
        r = H._select_sheet_handler(left)
        assert r["status"] == "ok"
        assert r["sheet"] in ("amp_left", "amp_right")

    def test_select_bad_path(self, loaded):
        with pytest.raises(RuntimeError):
            H._select_sheet_handler("/nope")


class TestHierarchyEditTools:
    def test_add_symbol_to_reused_sheet_gets_all_paths(self, loaded):
        tree = H._get_sheet_hierarchy_handler()
        H._select_sheet_handler(tree["children"][0]["instance_path"])
        res = S._add_symbol_handler("Device:C", "C1", "100nF", 60, 40)
        assert res["status"] == "added"
        # The added symbol must carry one instance path per placement (2).
        comps = H._list_hierarchical_symbols_handler()["components"]
        c1 = [c for c in comps if c["reference"] == "C1"]
        assert len(c1) == 2  # appears in both reused placements

    def test_add_hierarchical_label(self, loaded):
        tree = H._get_sheet_hierarchy_handler()
        H._select_sheet_handler(tree["children"][0]["instance_path"])
        r = H._add_hierarchical_label_handler("OUT", "output", 30, 50)
        assert r["status"] == "added"
        hl = H._list_sheets_handler  # noqa: F841
        from kicad_mcp import schematic_state as st

        labels = extract_hierarchical_labels(st.get_document())
        assert any(lbl.name == "OUT" and lbl.shape == "output" for lbl in labels)

    def test_add_hierarchical_label_bad_shape(self, loaded):
        assert "error" in H._add_hierarchical_label_handler("X", "bogus", 0, 0)

    def test_add_sheet_creates_child(self, loaded):
        tmp, root = loaded
        r = H._add_sheet_handler(
            "power",
            "power.kicad_sch",
            140,
            50,
            30,
            20,
            pins=[{"name": "VCC", "shape": "input"}, {"name": "GND", "shape": "input"}],
        )
        assert r["status"] == "added"
        assert (tmp / "power.kicad_sch").exists()
        # child carries matching hierarchical labels
        pw = (tmp / "power.kicad_sch").read_text()
        assert "VCC" in pw and "GND" in pw and "hierarchical_label" in pw
        # parent now lists 3 sheets
        assert H._list_sheets_handler()["count"] == 3

    def test_add_sheet_pin(self, loaded):
        tree = H._get_sheet_hierarchy_handler()
        sheet_uuid = tree["children"][0]["sheet_uuid"]
        r = H._add_sheet_pin_handler(sheet_uuid, "EN", "input", 50, 60)
        assert r["status"] == "added"
        from kicad_mcp import schematic_state as st

        sheets = extract_sheets(st.get_document())
        target = next(s for s in sheets if s.uuid == sheet_uuid)
        assert any(p.name == "EN" for p in target.pins)

    def test_remove_sheet(self, loaded):
        tree = H._get_sheet_hierarchy_handler()
        sheet_uuid = tree["children"][1]["sheet_uuid"]
        r = H._remove_sheet_handler(sheet_uuid)
        assert r["status"] == "removed"
        assert H._list_sheets_handler()["count"] == 1

    def test_save_and_reopen_roundtrip(self, loaded):
        tmp, root = loaded
        tree = H._get_sheet_hierarchy_handler()
        H._select_sheet_handler(tree["children"][0]["instance_path"])
        S._add_symbol_handler("Device:C", "C9", "1uF", 60, 40)
        H._select_sheet_handler(tree["instance_path"])  # back to root
        H._add_sheet_handler("io", "io.kicad_sch", 140, 50)
        H._save_hierarchy_handler()
        # Reopen from disk and confirm persistence.
        r = H._open_hierarchy_handler(root)
        assert r["sheet_count"] == 4  # root + 2 + io
        refs = sorted(c["reference"] for c in H._list_hierarchical_symbols_handler()["components"])
        assert "C9" in refs
