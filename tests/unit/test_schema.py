"""Tests for typed schema models and extraction from S-expression trees."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.schema import (
    BoundingBox,
    Position,
    Size,
    extract_board_outline,
    extract_board_summary,
    extract_footprints,
    extract_layers,
    extract_nets,
    extract_segments,
)
from kicad_mcp.sexp import Document

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")


class TestCommonModels:
    def test_position_to_dict(self) -> None:
        pos = Position(1.5, 2.5)
        d = pos.to_dict()
        assert d == {"x": 1.5, "y": 2.5}

    def test_position_with_angle_to_dict(self) -> None:
        pos = Position(1.0, 2.0, 90.0)
        d = pos.to_dict()
        assert d == {"x": 1.0, "y": 2.0, "angle": 90.0}

    def test_size_to_dict(self) -> None:
        s = Size(3.0, 4.0)
        assert s.to_dict() == {"width": 3.0, "height": 4.0}

    def test_bounding_box_properties(self) -> None:
        bb = BoundingBox(0.0, 0.0, 10.0, 20.0)
        assert bb.width == 10.0
        assert bb.height == 20.0
        assert bb.center == Position(5.0, 10.0)

    def test_bounding_box_to_dict(self) -> None:
        bb = BoundingBox(1.0, 2.0, 11.0, 22.0)
        d = bb.to_dict()
        assert d["min_x"] == 1.0
        assert d["width"] == 10.0
        assert d["height"] == 20.0


@pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
class TestExtractFromBlinky:
    """Integration tests extracting schema models from the real blinky board."""

    @pytest.fixture()
    def doc(self) -> Document:
        return Document.load(BLINKY_PATH)

    def test_extract_nets(self, doc: Document) -> None:
        nets = extract_nets(doc)
        assert len(nets) == 9
        net_names = {n.name for n in nets}
        assert "VBUS" in net_names
        assert "LED1" in net_names
        assert "LED4" in net_names

    def test_extract_layers(self, doc: Document) -> None:
        layers = extract_layers(doc)
        assert len(layers) >= 20
        layer_names = {lyr.name for lyr in layers}
        assert "F.Cu" in layer_names
        assert "B.Cu" in layer_names
        assert "Edge.Cuts" in layer_names
        # Check copper layers
        copper = [lyr for lyr in layers if lyr.layer_type == "signal"]
        assert len(copper) == 2

    def test_extract_footprints_count(self, doc: Document) -> None:
        fps = extract_footprints(doc)
        assert len(fps) == 29

    def test_extract_footprint_properties(self, doc: Document) -> None:
        fps = extract_footprints(doc)
        # Find C7 (the first capacitor)
        c7 = next((f for f in fps if f.reference == "C7"), None)
        assert c7 is not None
        assert c7.library == "Capacitor_SMD:C_0805_2012Metric"
        assert c7.value == "10uF"
        assert c7.layer == "F.Cu"
        assert c7.position.x == 14.0
        assert c7.position.y == 5.5

    def test_extract_footprint_pads(self, doc: Document) -> None:
        fps = extract_footprints(doc)
        c7 = next((f for f in fps if f.reference == "C7"), None)
        assert c7 is not None
        assert len(c7.pads) == 2
        pad1 = c7.pads[0]
        assert pad1.number == "1"
        assert pad1.pad_type == "smd"
        assert pad1.shape == "roundrect"

    def test_extract_segments(self, doc: Document) -> None:
        segs = extract_segments(doc)
        assert len(segs) == 12
        # All segments should have valid layers and net numbers
        for seg in segs:
            assert seg.layer in ("F.Cu", "B.Cu")
            assert seg.width > 0

    def test_extract_board_outline(self, doc: Document) -> None:
        bb = extract_board_outline(doc)
        assert bb is not None
        assert bb.width > 0
        assert bb.height > 0

    def test_extract_board_summary(self, doc: Document) -> None:
        summary = extract_board_summary(doc)
        assert summary.title == "blinky"
        assert summary.version == "20241229"
        assert summary.generator == "pcbnew"
        assert summary.thickness == 1.6
        assert summary.net_count == 9
        assert summary.footprint_count == 29
        assert summary.segment_count == 12
        assert len(summary.copper_layers) == 2
        assert "F.Cu" in summary.copper_layers
        assert "B.Cu" in summary.copper_layers

    def test_board_summary_json_serializable(self, doc: Document) -> None:
        summary = extract_board_summary(doc)
        d = summary.to_dict()
        # Must not raise
        json_str = json.dumps(d)
        assert len(json_str) > 100

    def test_footprint_to_dict_json_serializable(self, doc: Document) -> None:
        fps = extract_footprints(doc)
        for fp in fps:
            d = fp.to_dict()
            json.dumps(d)  # must not raise

    def test_references_extracted(self, doc: Document) -> None:
        fps = extract_footprints(doc)
        refs = [f.reference for f in fps if f.reference]
        # All 29 footprints should have references
        assert len(refs) == 29
        # Some references may repeat (e.g. virtual/test footprints share refs)
        unique = set(refs)
        assert len(unique) >= 20
