"""Tests for set_layer_stack (copper-layer count + dielectric stackup)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.session.manager import SessionManager
from kicad_mcp.sexp import Document
from kicad_mcp.sexp.parser import parse as sexp_parse
from kicad_mcp.tools.project import _minimal_kicad_pcb


def _board_session(tmp_path: Path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text(_minimal_kicad_pcb(100, 80))
    mgr = SessionManager()
    session = mgr.start_session(Document.load(str(board)))
    return mgr, session


def _copper_rows(doc):
    """Map copper layer name -> layer number (int)."""
    layers = doc.root.get("layers")
    out = {}
    for child in layers.children:
        vals = child.atom_values
        if vals and vals[0].endswith(".Cu"):
            out[vals[0]] = int(child.name)
    return out


def _dielectric_thicknesses(doc):
    stackup = doc.root.get("setup").get("stackup")
    out = []
    for child in stackup.find_all("layer"):
        if child.first_value and child.first_value.startswith("dielectric"):
            out.append(float(child.get("thickness").first_value))
    return out


class TestFourLayer:
    def test_copper_numbering(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        mgr.apply_set_layer_stack(session, copper_layers=4)
        rows = _copper_rows(session._working_doc)
        assert rows == {"F.Cu": 0, "In1.Cu": 1, "In2.Cu": 2, "B.Cu": 31}

    def test_preserves_non_copper_layers(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        layers = session._working_doc.root.get("layers")
        before = {c.atom_values[0] for c in layers.children if not c.atom_values[0].endswith(".Cu")}
        mgr.apply_set_layer_stack(session, copper_layers=4)
        layers = session._working_doc.root.get("layers")
        after = {c.atom_values[0] for c in layers.children if not c.atom_values[0].endswith(".Cu")}
        assert before == after
        assert "Edge.Cuts" in after

    def test_default_dielectric_stack(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        mgr.apply_set_layer_stack(session, copper_layers=4)
        assert _dielectric_thicknesses(session._working_doc) == [0.2, 1.0, 0.2]

    def test_stackup_is_first_setup_child(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        mgr.apply_set_layer_stack(session, copper_layers=4)
        setup = session._working_doc.root.get("setup")
        assert setup.children[0].name == "stackup"

    def test_stackup_copper_layers_present(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        mgr.apply_set_layer_stack(session, copper_layers=4)
        stackup = session._working_doc.root.get("setup").get("stackup")
        copper = [
            c.first_value
            for c in stackup.find_all("layer")
            if c.first_value and c.first_value.endswith(".Cu")
        ]
        assert copper == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]

    def test_general_thickness_updated(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        mgr.apply_set_layer_stack(session, copper_layers=4)
        general = session._working_doc.root.get("general")
        total = float(general.get("thickness").first_value)
        # 4*0.035 copper + (0.2+1.0+0.2) dielectric + 2*0.01 mask
        assert total == pytest.approx(1.56)

    def test_record_metadata(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        record = mgr.apply_set_layer_stack(session, copper_layers=4)
        assert record.applied
        assert record.operation == "set_layer_stack"


class TestSixLayer:
    def test_six_copper_layers(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        mgr.apply_set_layer_stack(session, copper_layers=6)
        rows = _copper_rows(session._working_doc)
        assert rows == {
            "F.Cu": 0,
            "In1.Cu": 1,
            "In2.Cu": 2,
            "In3.Cu": 3,
            "In4.Cu": 4,
            "B.Cu": 31,
        }

    def test_five_dielectric_gaps(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        mgr.apply_set_layer_stack(session, copper_layers=6)
        assert len(_dielectric_thicknesses(session._working_doc)) == 5


class TestExplicitAndValidation:
    def test_explicit_dielectrics(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        diels = [
            {"type": "prepreg", "thickness": 0.1},
            {"type": "core", "thickness": 1.2, "material": "FR408"},
            {"type": "prepreg", "thickness": 0.1},
        ]
        mgr.apply_set_layer_stack(session, copper_layers=4, dielectrics=diels)
        assert _dielectric_thicknesses(session._working_doc) == [0.1, 1.2, 0.1]
        stackup = session._working_doc.root.get("setup").get("stackup")
        assert "FR408" in stackup.to_string()

    def test_wrong_dielectric_count_raises(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        with pytest.raises(ValueError, match="dielectric"):
            mgr.apply_set_layer_stack(session, copper_layers=4, dielectrics=[{"thickness": 1.0}])

    @pytest.mark.parametrize("bad", [0, 1, 3, 5, 33, -2])
    def test_invalid_copper_count_raises(self, tmp_path, bad):
        mgr, session = _board_session(tmp_path)
        with pytest.raises(ValueError, match="copper_layers"):
            mgr.apply_set_layer_stack(session, copper_layers=bad)

    def test_reapply_replaces_stackup_no_duplicate(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        mgr.apply_set_layer_stack(session, copper_layers=4)
        mgr.apply_set_layer_stack(session, copper_layers=2)
        setup = session._working_doc.root.get("setup")
        stackups = [c for c in setup.children if c.name == "stackup"]
        assert len(stackups) == 1
        rows = _copper_rows(session._working_doc)
        assert rows == {"F.Cu": 0, "B.Cu": 31}

    def test_undo_restores_two_layer(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        mgr.apply_set_layer_stack(session, copper_layers=4)
        mgr.undo(session)
        rows = _copper_rows(session._working_doc)
        assert rows == {"F.Cu": 0, "B.Cu": 31}


class TestRoundTrip:
    def test_output_reparses(self, tmp_path):
        mgr, session = _board_session(tmp_path)
        mgr.apply_set_layer_stack(session, copper_layers=4)
        # The whole document must still serialize and parse cleanly.
        text = session._working_doc.root.to_string()
        reparsed = sexp_parse(text)
        assert reparsed.get("layers") is not None
        assert reparsed.get("setup").get("stackup") is not None
