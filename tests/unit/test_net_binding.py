"""assign_net / create_zone must bind nets by name on KiCad 10 boards.

KiCad 10 dropped the top-level (net N "name") table and references nets purely
by name — (net "GND") on both pads and zones. Boards with the legacy numbered
table keep the numbered form.
"""

from __future__ import annotations

import pytest

from kicad_mcp.session.manager import SessionManager
from kicad_mcp.session.net_zone_ops import _lookup_net
from kicad_mcp.sexp import Document
from kicad_mcp.sexp.parser import parse as sexp_parse

# Legacy board: explicit numbered net table.
_LEGACY = """\
(kicad_pcb (version 20240108) (generator "pcbnew")
  (net 0 "") (net 1 "GND")
  (footprint "R" (layer "F.Cu") (at 20 20)
    (property "Reference" "R1" (at 0 0))
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu"))))
"""

# KiCad 10 board: no net table at all.
_KI10 = """\
(kicad_pcb (version 20241229) (generator "pcbnew")
  (footprint "R" (layer "F.Cu") (at 20 20)
    (property "Reference" "R1" (at 0 0))
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu"))))
"""


def _session(text: str):
    doc = Document(path=None, root=sexp_parse(text), raw_text=text)
    mgr = SessionManager()
    return mgr, mgr.start_session(doc)


def _pad_net(doc, ref="R1", pad="1"):
    for fp in doc.root.find_all("footprint"):
        for p in fp.find_all("pad"):
            if p.atom_values and p.atom_values[0] == pad:
                return p.get("net")
    return None


class TestLookupNet:
    def test_legacy_found(self):
        doc = Document(path=None, root=sexp_parse(_LEGACY), raw_text="")
        assert _lookup_net(doc, "GND") == (1, True)

    def test_legacy_absent(self):
        doc = Document(path=None, root=sexp_parse(_LEGACY), raw_text="")
        assert _lookup_net(doc, "NOPE") == (None, True)

    def test_kicad10_no_table(self):
        doc = Document(path=None, root=sexp_parse(_KI10), raw_text="")
        assert _lookup_net(doc, "GND") == (None, False)


class TestAssignNet:
    def test_legacy_numbered_form(self):
        mgr, s = _session(_LEGACY)
        mgr.apply_assign_net(s, "R1", "1", "GND")
        assert _pad_net(s._working_doc).atom_values == ["1", "GND"]

    def test_legacy_unknown_net_raises(self):
        mgr, s = _session(_LEGACY)
        with pytest.raises(ValueError, match="not found on the board"):
            mgr.apply_assign_net(s, "R1", "1", "MISSING")

    def test_kicad10_named_form(self):
        mgr, s = _session(_KI10)
        mgr.apply_assign_net(s, "R1", "1", "GND")
        # By-name, no number.
        assert _pad_net(s._working_doc).atom_values == ["GND"]

    def test_kicad10_replaces_existing_net(self):
        mgr, s = _session(_KI10)
        mgr.apply_assign_net(s, "R1", "1", "GND")
        mgr.apply_assign_net(s, "R1", "1", "VCC")
        net = _pad_net(s._working_doc)
        assert net.atom_values == ["VCC"]
        # Exactly one net node on the pad.
        pad = next(
            p
            for fp in s._working_doc.root.find_all("footprint")
            for p in fp.find_all("pad")
            if p.atom_values[0] == "1"
        )
        assert len(pad.find_all("net")) == 1


class TestCreateZone:
    _PTS = [[1, 1], [39, 1], [39, 39], [1, 39]]

    def test_legacy_numbered_with_net_name(self):
        mgr, s = _session(_LEGACY)
        mgr.apply_create_zone(s, "GND", "F.Cu", self._PTS)
        zone = s._working_doc.root.find_all("zone")[0]
        assert zone.get("net").atom_values == ["1"]
        assert zone.get("net_name") is not None

    def test_kicad10_named_no_net_name(self):
        mgr, s = _session(_KI10)
        mgr.apply_create_zone(s, "GND", "F.Cu", self._PTS)
        zone = s._working_doc.root.find_all("zone")[0]
        assert zone.get("net").atom_values == ["GND"]
        assert zone.get("net_name") is None

    def test_legacy_unknown_net_raises(self):
        mgr, s = _session(_LEGACY)
        with pytest.raises(ValueError, match="not found on the board"):
            mgr.apply_create_zone(s, "MISSING", "F.Cu", self._PTS)

    def test_kicad10_zone_for_fresh_net(self):
        # On a table-less board any name is bindable, even if unused elsewhere.
        mgr, s = _session(_KI10)
        mgr.apply_create_zone(s, "BRAND_NEW", "F.Cu", self._PTS)
        zone = s._working_doc.root.find_all("zone")[0]
        assert zone.get("net").atom_values == ["BRAND_NEW"]


class TestRoundTrip:
    def test_kicad10_output_reparses(self):
        mgr, s = _session(_KI10)
        mgr.apply_assign_net(s, "R1", "1", "GND")
        mgr.apply_create_zone(s, "GND", "F.Cu", [[1, 1], [39, 1], [39, 39], [1, 39]])
        text = s._working_doc.root.to_string()
        reparsed = sexp_parse(text)
        assert reparsed.find_all("zone")[0].get("net").atom_values == ["GND"]
