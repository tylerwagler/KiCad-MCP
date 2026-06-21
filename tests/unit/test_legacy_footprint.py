"""Tests for legacy (fp_text reference|value …) footprint handling.

KiCad 6-and-older .kicad_mod files declare the reference/value with fp_text
instead of modern properties. These must still place, be findable, and accept
net assignment — otherwise net assignment silently skips every pad.
"""

from __future__ import annotations

from pathlib import Path

from kicad_mcp.session.helpers import find_footprint, footprint_field
from kicad_mcp.session.manager import SessionManager
from kicad_mcp.sexp import Document
from kicad_mcp.sexp.parser import parse as sexp_parse
from kicad_mcp.tools.project import _minimal_kicad_pcb

# A footprint that declares ref/value the old way and carries no fp_text uuids.
_LEGACY_MOD = """\
(footprint "Legacy_R" (version 20221018) (generator pcbnew) (layer "F.Cu")
  (at 0 0)
  (fp_text reference "REF**" (at 0 -2 0) (layer "F.SilkS")
    (effects (font (size 1 1) (thickness 0.15))))
  (fp_text value "Legacy_R" (at 0 2 0) (layer "F.Fab")
    (effects (font (size 1 1) (thickness 0.15))))
  (fp_text user "${REFERENCE}" (at 0 0 0) (layer "F.Fab")
    (effects (font (size 1 1) (thickness 0.15))))
  (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
)
"""


def _board_session(tmp_path: Path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text(_minimal_kicad_pcb(100, 80))
    mgr = SessionManager()
    session = mgr.start_session(Document.load(str(board)))
    return mgr, session


def _place_legacy(tmp_path: Path):
    mod = tmp_path / "Legacy_R.kicad_mod"
    mod.write_text(_LEGACY_MOD)
    mgr, session = _board_session(tmp_path)
    mgr.place_from_kicad_mod(session, str(mod), "R5", "10k", 10, 10)
    return mgr, session


class TestPlaceLegacyFootprint:
    def test_normalizes_fp_text_to_property(self, tmp_path):
        _, session = _place_legacy(tmp_path)
        fp = find_footprint(session._working_doc, "R5")
        assert fp is not None
        # Ref/value now live in modern property nodes…
        assert footprint_field(fp, "Reference") == "R5"
        assert footprint_field(fp, "Value") == "10k"
        # …and the legacy reference/value fp_text nodes are gone.
        legacy_kinds = {ft.atom_values[0] for ft in fp.find_all("fp_text") if ft.atom_values}
        assert "reference" not in legacy_kinds
        assert "value" not in legacy_kinds

    def test_user_fp_text_is_preserved(self, tmp_path):
        _, session = _place_legacy(tmp_path)
        fp = find_footprint(session._working_doc, "R5")
        user_texts = [ft for ft in fp.find_all("fp_text") if ft.atom_values[0] == "user"]
        assert len(user_texts) == 1

    def test_converted_properties_get_uuid(self, tmp_path):
        _, session = _place_legacy(tmp_path)
        fp = find_footprint(session._working_doc, "R5")
        for prop in fp.find_all("property"):
            if prop.first_value in ("Reference", "Value"):
                assert prop.get("uuid") is not None

    def test_assign_net_to_legacy_placed_pad(self, tmp_path):
        """The core regression: legacy footprints must accept net assignment."""
        mgr, session = _place_legacy(tmp_path)
        mgr.apply_create_net(session, "VCC")
        record = mgr.apply_assign_net(session, "R5", "1", "VCC")
        assert record.applied
        assert "net" in record.after_snapshot and "VCC" in record.after_snapshot


class TestFindFootprintBothForms:
    def test_find_footprint_matches_unconverted_legacy(self, tmp_path):
        """find_footprint locates a legacy footprint already on the board."""
        board = tmp_path / "b.kicad_pcb"
        text = _minimal_kicad_pcb(50, 50)
        # Splice a raw legacy footprint (untouched fp_text) into the board.
        text = text.rstrip().rstrip(")") + "\n" + _LEGACY_MOD + "\n)"
        board.write_text(text)
        doc = Document.load(str(board))
        # The board carries the literal "REF**" reference.
        fp = find_footprint(doc, "REF**")
        assert fp is not None
        assert footprint_field(fp, "Value") == "Legacy_R"

    def test_footprint_field_modern_form(self):
        fp = sexp_parse(
            '(footprint "X" (property "Reference" "U7" (at 0 0)) (property "Value" "MCU" (at 0 1)))'
        )
        assert footprint_field(fp, "Reference") == "U7"
        assert footprint_field(fp, "Value") == "MCU"

    def test_footprint_field_absent_returns_none(self):
        fp = sexp_parse('(footprint "X" (at 0 0))')
        assert footprint_field(fp, "Reference") is None
