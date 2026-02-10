"""Tests for force-directed placement solver (algorithms/placement.py)."""

from __future__ import annotations

from kicad_mcp.algorithms.placement import (
    _build_connection_weights,
    _build_net_map,
    _count_overlaps,
    _estimate_bbox,
    compute_hpwl,
    evaluate_placement,
    force_directed_placement,
    spread_components,
)
from kicad_mcp.algorithms.types import ComponentPlacement
from kicad_mcp.schema.board import Footprint, Pad
from kicad_mcp.schema.common import BoundingBox, Position


def _make_footprint(
    ref: str,
    x: float,
    y: float,
    pads: list[Pad] | None = None,
) -> Footprint:
    """Helper to create a test footprint."""
    if pads is None:
        pads = [
            Pad(
                number="1",
                pad_type="smd",
                shape="rect",
                position=Position(0, 0),
                size=(1.0, 0.5),
                layers=["F.Cu"],
                net_number=1,
            ),
            Pad(
                number="2",
                pad_type="smd",
                shape="rect",
                position=Position(2.0, 0),
                size=(1.0, 0.5),
                layers=["F.Cu"],
                net_number=2,
            ),
        ]
    return Footprint(
        library="R_0402",
        reference=ref,
        value="10k",
        position=Position(x, y),
        layer="F.Cu",
        pads=pads,
    )


class TestEstimateBbox:
    def test_with_pads(self) -> None:
        fp = _make_footprint("R1", 10, 10)
        w, h = _estimate_bbox(fp)
        assert w > 0
        assert h > 0
        # Two pads: one at (0,0) size 1x0.5, one at (2,0) size 1x0.5
        # Extent: -0.5 to 2.5 x, -0.25 to 0.25 y
        assert abs(w - 3.0) < 0.1
        assert abs(h - 0.5) < 0.1

    def test_no_pads(self) -> None:
        fp = Footprint(
            library="Test",
            reference="T1",
            value="",
            position=Position(0, 0),
            layer="F.Cu",
        )
        w, h = _estimate_bbox(fp)
        assert w == 1.0  # default
        assert h == 1.0


class TestBuildNetMap:
    def test_basic(self) -> None:
        fps = [
            _make_footprint("R1", 10, 10),
            _make_footprint("R2", 20, 10),
        ]
        net_map = _build_net_map(fps)
        assert 1 in net_map
        assert "R1" in net_map[1]
        assert "R2" in net_map[1]


class TestBuildConnectionWeights:
    def test_shared_nets(self) -> None:
        net_map = {1: ["R1", "R2"], 2: ["R1", "R2"]}
        weights = _build_connection_weights(net_map)
        # R1-R2 share 2 nets
        key = ("R1", "R2")
        assert weights[key] == 2

    def test_no_shared_nets(self) -> None:
        net_map = {1: ["R1"], 2: ["R2"]}
        weights = _build_connection_weights(net_map)
        assert len(weights) == 0


class TestComputeHpwl:
    def test_simple(self) -> None:
        placements = {
            "R1": ComponentPlacement("R1", 0, 0, 2, 1),
            "R2": ComponentPlacement("R2", 10, 0, 2, 1),
            "R3": ComponentPlacement("R3", 0, 10, 2, 1),
        }
        net_map = {1: ["R1", "R2"], 2: ["R1", "R3"]}
        hpwl = compute_hpwl(placements, net_map)
        # Net 1: dx=10, dy=0 → 10
        # Net 2: dx=0, dy=10 → 10
        assert abs(hpwl - 20.0) < 0.001

    def test_single_pad_net(self) -> None:
        placements = {"R1": ComponentPlacement("R1", 0, 0, 2, 1)}
        net_map = {1: ["R1"]}  # single pad
        hpwl = compute_hpwl(placements, net_map)
        assert hpwl == 0.0


class TestCountOverlaps:
    def test_overlapping(self) -> None:
        placements = {
            "R1": ComponentPlacement("R1", 5, 5, 4, 4),
            "R2": ComponentPlacement("R2", 6, 6, 4, 4),  # overlapping
        }
        count = _count_overlaps(placements, 0.0)
        assert count == 1

    def test_no_overlap(self) -> None:
        placements = {
            "R1": ComponentPlacement("R1", 0, 0, 2, 2),
            "R2": ComponentPlacement("R2", 20, 20, 2, 2),
        }
        count = _count_overlaps(placements, 0.0)
        assert count == 0

    def test_clearance_matters(self) -> None:
        placements = {
            "R1": ComponentPlacement("R1", 0, 0, 2, 2),
            "R2": ComponentPlacement("R2", 3, 0, 2, 2),  # just touching
        }
        # Without clearance, no overlap (edges touch at x=1 and x=2)
        # half widths: 1+1 = 2, distance = 3 → 3 < 2? No.
        assert _count_overlaps(placements, 0.0) == 0
        # With clearance=2, they overlap (half_w: 1+1=2 each, dist: 3 < 2+2=4)
        assert _count_overlaps(placements, 2.0) == 1


class TestForceDirectedPlacement:
    def test_convergence(self) -> None:
        bbox = BoundingBox(0, 0, 100, 100)
        fps = [
            _make_footprint("R1", 50, 50),
            _make_footprint("R2", 51, 51),
        ]
        result = force_directed_placement(fps, bbox, max_iterations=100)
        assert result.iterations_used > 0

    def test_locked_components_stay(self) -> None:
        bbox = BoundingBox(0, 0, 100, 100)
        fps = [
            _make_footprint("J1", 10, 10),
            _make_footprint("R1", 50, 50),
        ]
        result = force_directed_placement(fps, bbox, locked_references=["J1"], max_iterations=100)
        # J1 should not move
        for m in result.movements:
            assert m["reference"] != "J1"

    def test_hpwl_reduction(self) -> None:
        bbox = BoundingBox(0, 0, 100, 100)
        # Place connected components far apart
        pad1 = Pad("1", "smd", "rect", Position(0, 0), (1, 1), ["F.Cu"], 1)
        pad2 = Pad("2", "smd", "rect", Position(0, 0), (1, 1), ["F.Cu"], 1)
        fps = [
            Footprint("R", "R1", "10k", Position(10, 10), "F.Cu", [pad1]),
            Footprint("R", "R2", "10k", Position(90, 90), "F.Cu", [pad2]),
        ]
        result = force_directed_placement(fps, bbox, max_iterations=500)
        # Attractive force should pull them closer → HPWL should decrease
        assert result.hpwl_after <= result.hpwl_before

    def test_boundary_clamping(self) -> None:
        bbox = BoundingBox(0, 0, 20, 20)
        fps = [
            _make_footprint("R1", 1, 1),
            _make_footprint("R2", 19, 19),
        ]
        result = force_directed_placement(fps, bbox, max_iterations=100)
        # All movements should be within bounds
        for m in result.movements:
            assert m["to_x"] >= 0
            assert m["to_y"] >= 0
            assert m["to_x"] <= 20
            assert m["to_y"] <= 20

    def test_result_to_dict(self) -> None:
        bbox = BoundingBox(0, 0, 100, 100)
        fps = [_make_footprint("R1", 50, 50)]
        result = force_directed_placement(fps, bbox, max_iterations=10)
        d = result.to_dict()
        assert "movement_count" in d
        assert "hpwl_before" in d
        assert "hpwl_after" in d
        assert "converged" in d

    def test_empty_board(self) -> None:
        bbox = BoundingBox(0, 0, 100, 100)
        result = force_directed_placement([], bbox, max_iterations=10)
        assert result.movements == []
        assert result.converged is True


class TestEvaluatePlacement:
    def test_basic_evaluation(self) -> None:
        bbox = BoundingBox(0, 0, 100, 100)
        fps = [
            _make_footprint("R1", 10, 10),
            _make_footprint("R2", 20, 20),
        ]
        ev = evaluate_placement(fps, bbox)
        assert ev.component_count == 2
        assert ev.hpwl_total >= 0
        assert ev.density > 0

    def test_per_net_wirelength(self) -> None:
        bbox = BoundingBox(0, 0, 100, 100)
        fps = [
            _make_footprint("R1", 10, 10),
            _make_footprint("R2", 50, 50),
        ]
        ev = evaluate_placement(fps, bbox)
        assert len(ev.per_net_wirelength) > 0
        for entry in ev.per_net_wirelength:
            assert "net_number" in entry
            assert "hpwl" in entry

    def test_evaluation_to_dict(self) -> None:
        bbox = BoundingBox(0, 0, 100, 100)
        fps = [_make_footprint("R1", 10, 10)]
        ev = evaluate_placement(fps, bbox)
        d = ev.to_dict()
        assert "hpwl_total" in d
        assert "overlap_count" in d
        assert "density" in d


class TestSpreadComponents:
    def test_overlapping_spread(self) -> None:
        bbox = BoundingBox(0, 0, 100, 100)
        # Place components on top of each other
        fps = [
            _make_footprint("R1", 50, 50),
            _make_footprint("R2", 50, 50),
        ]
        result = spread_components(fps, bbox, min_clearance=1.0)
        # Should have movements to separate them
        assert len(result.movements) > 0

    def test_already_spread(self) -> None:
        bbox = BoundingBox(0, 0, 100, 100)
        # Place components far apart
        fps = [
            _make_footprint("R1", 20, 20),
            _make_footprint("R2", 80, 80),
        ]
        result = spread_components(fps, bbox, min_clearance=0.5)
        # Minimal movement expected (repulsive forces only, far apart)
        total_displacement = sum(abs(m["dx"]) + abs(m["dy"]) for m in result.movements)
        assert total_displacement < 5.0  # very little movement

    def test_spread_within_bounds(self) -> None:
        bbox = BoundingBox(0, 0, 30, 30)
        fps = [
            _make_footprint("R1", 15, 15),
            _make_footprint("R2", 15.1, 15.1),
            _make_footprint("R3", 15.2, 15.2),
        ]
        result = spread_components(fps, bbox, min_clearance=1.0)
        for m in result.movements:
            assert m["to_x"] >= 0
            assert m["to_y"] >= 0
            assert m["to_x"] <= 30
            assert m["to_y"] <= 30
