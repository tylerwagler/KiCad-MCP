"""Tests for update_pcb_from_schematic (netlist import / "Update PCB")."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.backends.kicad_cli import KiCadCli
from kicad_mcp.session import SessionManager
from kicad_mcp.sexp import Document
from kicad_mcp.sync import parse_netlist_doc
from kicad_mcp.tools.project import _minimal_kicad_pcb

_MOD = """\
(footprint "R_test" (version 20240108) (generator "test") (layer "F.Cu")
  (at 0 0)
  (property "Reference" "REF**" (at 0 -2 0) (layer "F.SilkS")
    (uuid "11111111-1111-1111-1111-111111111111") (effects (font (size 1 1))))
  (property "Value" "Val" (at 0 2 0) (layer "F.Fab")
    (uuid "22222222-2222-2222-2222-222222222222") (effects (font (size 1 1))))
  (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")
    (uuid "33333333-3333-3333-3333-333333333333"))
  (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")
    (uuid "44444444-4444-4444-4444-444444444444"))
)
"""

_NETLIST = """\
(export (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Lib:R_test"))
    (comp (ref "R2") (value "1k") (footprint "Lib:Missing")))
  (nets
    (net (code "1") (name "VCC") (node (ref "R1") (pin "1")))
    (net (code "2") (name "GND") (node (ref "R1") (pin "2")) (node (ref "R2") (pin "1")))))
"""


def _board_session(tmp_path: Path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text(_minimal_kicad_pcb(100, 80))
    mgr = SessionManager()
    session = mgr.start_session(Document.load(str(board)))
    return mgr, session, board


class TestParseNetlist:
    def test_parses_components_and_nets(self, tmp_path):
        nl = tmp_path / "n.net"
        nl.write_text(_NETLIST)
        comps, nets = parse_netlist_doc(Document.load(str(nl)))
        assert {c["ref"] for c in comps} == {"R1", "R2"}
        r1 = next(c for c in comps if c["ref"] == "R1")
        assert r1["value"] == "10k" and r1["footprint"] == "Lib:R_test"
        gnd = next(n for n in nets if n["name"] == "GND")
        assert ("R1", "2") in gnd["nodes"] and ("R2", "1") in gnd["nodes"]


class TestApplyUpdate:
    @pytest.fixture
    def patched_resolver(self, tmp_path, monkeypatch):
        """Resolve only Lib:R_test to a real .kicad_mod; everything else missing."""
        mod = tmp_path / "R_test.kicad_mod"
        mod.write_text(_MOD)
        from kicad_mcp.session import placement_ops

        def fake(fp_lib: str, project_dir=None):
            return str(mod) if fp_lib == "Lib:R_test" else None

        monkeypatch.setattr(placement_ops, "_resolve_kicad_mod_path", fake)
        return mod

    def test_blank_board_population(self, tmp_path, patched_resolver):
        mgr, session, _ = _board_session(tmp_path)
        comps, nets = parse_netlist_doc(Document.load(str(_write(tmp_path, _NETLIST))))
        out = mgr.apply_update_from_schematic(session, comps, nets)
        assert out["added"] == ["R1"]
        assert [u["ref"] for u in out["unresolved"]] == ["R2"]
        assert out["nets_created"] == 2
        # R1.1 -> VCC, R1.2 -> GND (R2 not placed, its GND node skipped silently)
        assert out["pads_assigned"] == 2
        # The placed footprint and its netted pads are on the working doc.
        doc = session._working_doc
        assert doc.root.to_string().count("(footprint ") == 1
        assert '(net 1 "VCC")' in doc.root.to_string()
        assert '(net 2 "GND")' in doc.root.to_string()

    def test_value_reconcile_on_existing(self, tmp_path, patched_resolver):
        mgr, session, _ = _board_session(tmp_path)
        # First import places R1.
        comps, nets = parse_netlist_doc(Document.load(str(_write(tmp_path, _NETLIST))))
        mgr.apply_update_from_schematic(session, comps, nets)
        # Re-run with a changed value → reconciled, not re-added.
        comps2 = [{"ref": "R1", "value": "22k", "footprint": "Lib:R_test"}]
        out = mgr.apply_update_from_schematic(session, comps2, [])
        assert out["added"] == []
        assert "R1" in out["updated"]
        assert '"22k"' in session._working_doc.root.to_string()

    def test_place_new_false_skips_placement(self, tmp_path, patched_resolver):
        mgr, session, _ = _board_session(tmp_path)
        comps, nets = parse_netlist_doc(Document.load(str(_write(tmp_path, _NETLIST))))
        out = mgr.apply_update_from_schematic(session, comps, nets, place_new=False)
        assert out["added"] == []

    def test_remove_extra(self, tmp_path, patched_resolver):
        mgr, session, _ = _board_session(tmp_path)
        comps, nets = parse_netlist_doc(Document.load(str(_write(tmp_path, _NETLIST))))
        mgr.apply_update_from_schematic(session, comps, nets)  # places R1
        # Now a netlist without R1 → remove_extra deletes it.
        out = mgr.apply_update_from_schematic(session, [], [], remove_extra=True)
        assert "R1" in out["removed"]
        assert session._working_doc.root.to_string().count("(footprint ") == 0


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "n.net"
    p.write_text(text)
    return p


@pytest.mark.skipif(not KiCadCli.is_available(), reason="kicad-cli not installed")
class TestEndToEnd:
    def test_populates_blank_board_from_demo(self, tmp_path):
        import kicad_mcp.tools  # noqa: F401  (register tools)
        from kicad_mcp.tools import sync as SY
        from kicad_mcp.tools.registry import TOOL_REGISTRY as R

        board = tmp_path / "b.kicad_pcb"
        board.write_text(_minimal_kicad_pcb(120, 80))
        R["open_project"].handler(str(board))
        sid = R["start_session"].handler()["session_id"]
        sch = "/usr/share/kicad/demos/complex_hierarchy/complex_hierarchy.kicad_sch"
        if not Path(sch).exists():
            pytest.skip("KiCad demo not installed")
        out = SY._update_pcb_from_schematic_handler(sid, schematic_path=sch)
        assert out["status"] == "ok"
        assert len(out["added"]) > 0
        assert out["nets_created"] > 0
        assert out["pads_assigned"] > 0
        assert out["unresolved"] == []


class TestKiprjmodFootprintResolution:
    """Project-local footprints (${KIPRJMOD}) must resolve on the PCB side."""

    def test_resolves_project_footprint(self, tmp_path):
        from kicad_mcp.session.placement_ops import _resolve_kicad_mod_path

        # A project library registered with ${KIPRJMOD}, KiCad's convention.
        pretty = tmp_path / "myproj.pretty"
        pretty.mkdir()
        (pretty / "MyFP.kicad_mod").write_text(_MOD)
        (tmp_path / "fp-lib-table").write_text(
            "(fp_lib_table\n"
            '  (lib (name "myproj") (type "KiCad")'
            ' (uri "${KIPRJMOD}/myproj.pretty") (descr "project"))\n'
            ")",
            encoding="utf-8",
        )

        # Without project_dir it can't resolve the ${KIPRJMOD} lib...
        assert _resolve_kicad_mod_path("myproj:MyFP") is None
        # ...with it, the project table is read and ${KIPRJMOD} expands.
        hit = _resolve_kicad_mod_path("myproj:MyFP", tmp_path)
        assert hit is not None
        assert hit == str(pretty / "MyFP.kicad_mod")

    def test_update_places_project_footprint(self, tmp_path):
        # End-to-end through the session: a board in the project dir + a netlist
        # referencing the project lib → the footprint is instantiated.
        pretty = tmp_path / "myproj.pretty"
        pretty.mkdir()
        (pretty / "MyFP.kicad_mod").write_text(_MOD)
        (tmp_path / "fp-lib-table").write_text(
            '(fp_lib_table (lib (name "myproj") (type "KiCad") (uri "${KIPRJMOD}/myproj.pretty")))',
            encoding="utf-8",
        )
        mgr, session, _ = _board_session(tmp_path)
        comps = [{"ref": "U1", "value": "X", "footprint": "myproj:MyFP"}]
        nets = [{"name": "N1", "nodes": [("U1", "1")]}]
        out = mgr.apply_update_from_schematic(session, comps, nets)
        assert out["added"] == ["U1"]
        assert out["unresolved"] == []
        assert out["pads_assigned"] == 1
