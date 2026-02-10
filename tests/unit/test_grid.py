"""Tests for the obstacle map grid (algorithms/grid.py)."""

from __future__ import annotations

import pytest

from kicad_mcp.algorithms.grid import ObstacleMap, build_obstacle_map
from kicad_mcp.schema.board import Footprint, Pad, Segment
from kicad_mcp.schema.common import BoundingBox, Position


def _make_grid(
    width: float = 10.0,
    height: float = 10.0,
    resolution: float = 1.0,
    layers: list[str] | None = None,
) -> ObstacleMap:
    """Create a simple obstacle map for testing."""
    layers = layers or ["F.Cu", "B.Cu"]
    cols = int(width / resolution)
    rows = int(height / resolution)
    return ObstacleMap(
        origin_x=0.0,
        origin_y=0.0,
        width_mm=width,
        height_mm=height,
        resolution=resolution,
        cols=cols,
        rows=rows,
        layers=layers,
    )


class TestCoordinateConversion:
    def test_mm_to_col(self) -> None:
        grid = _make_grid(resolution=0.5)
        assert grid.mm_to_col(0.0) == 0
        assert grid.mm_to_col(5.0) == 10
        assert grid.mm_to_col(2.5) == 5

    def test_mm_to_row(self) -> None:
        grid = _make_grid(resolution=0.5)
        assert grid.mm_to_row(0.0) == 0
        assert grid.mm_to_row(5.0) == 10

    def test_col_to_mm(self) -> None:
        grid = _make_grid(resolution=0.25)
        assert grid.col_to_mm(0) == 0.0
        assert grid.col_to_mm(4) == 1.0
        assert grid.col_to_mm(40) == 10.0

    def test_row_to_mm(self) -> None:
        grid = _make_grid(resolution=0.25)
        assert grid.row_to_mm(0) == 0.0
        assert grid.row_to_mm(4) == 1.0

    def test_roundtrip(self) -> None:
        grid = _make_grid(resolution=0.25)
        x = 3.5
        col = grid.mm_to_col(x)
        x_back = grid.col_to_mm(col)
        assert abs(x_back - x) < grid.resolution


class TestBoundsChecking:
    def test_in_bounds(self) -> None:
        grid = _make_grid(width=10, height=10, resolution=1.0)
        assert grid.in_bounds(0, 0) is True
        assert grid.in_bounds(9, 9) is True
        assert grid.in_bounds(10, 0) is False
        assert grid.in_bounds(0, 10) is False
        assert grid.in_bounds(-1, 0) is False

    def test_layer_index(self) -> None:
        grid = _make_grid()
        assert grid.layer_index("F.Cu") == 0
        assert grid.layer_index("B.Cu") == 1

    def test_layer_index_invalid(self) -> None:
        grid = _make_grid()
        with pytest.raises(ValueError, match="Layer"):
            grid.layer_index("In1.Cu")


class TestMarkRect:
    def test_mark_rect_blocks_cells(self) -> None:
        grid = _make_grid(resolution=1.0)
        grid.mark_rect(5.0, 5.0, 1.5, 1.5, 0)
        # Should block cells around (5, 5) with half-extents 1.5
        assert grid.is_blocked(5, 5, 0) is True
        assert grid.is_blocked(4, 4, 0) is True
        assert grid.is_blocked(6, 6, 0) is True
        # Outside extent
        assert grid.is_blocked(2, 2, 0) is False

    def test_mark_rect_with_net(self) -> None:
        grid = _make_grid(resolution=1.0)
        grid.mark_rect(5.0, 5.0, 1.0, 1.0, 0, net_number=42)
        assert (5, 5, 0) in grid.net_ownership
        assert grid.net_ownership[(5, 5, 0)] == 42

    def test_mark_rect_respects_bounds(self) -> None:
        grid = _make_grid(width=5, height=5, resolution=1.0)
        # Mark rect partially outside bounds
        grid.mark_rect(0.0, 0.0, 3.0, 3.0, 0)
        # Should not crash; cells outside bounds are clamped
        assert grid.is_blocked(0, 0, 0) is True


class TestMarkSegmentLine:
    def test_horizontal_line(self) -> None:
        grid = _make_grid(resolution=1.0)
        grid.mark_segment_line(2.0, 5.0, 8.0, 5.0, 0.5, 0)
        # Cells along the line should be blocked
        assert grid.is_blocked(5, 5, 0) is True
        assert grid.is_blocked(3, 5, 0) is True
        # Far away should be clear
        assert grid.is_blocked(5, 0, 0) is False

    def test_vertical_line(self) -> None:
        grid = _make_grid(resolution=1.0)
        grid.mark_segment_line(5.0, 2.0, 5.0, 8.0, 0.5, 0)
        assert grid.is_blocked(5, 5, 0) is True
        assert grid.is_blocked(5, 3, 0) is True

    def test_diagonal_line(self) -> None:
        grid = _make_grid(resolution=1.0)
        grid.mark_segment_line(0.0, 0.0, 9.0, 9.0, 1.0, 0)
        # Points on the diagonal should be blocked
        assert grid.is_blocked(4, 4, 0) is True

    def test_zero_length_segment(self) -> None:
        grid = _make_grid(resolution=1.0)
        # Point segment should still block the cell
        grid.mark_segment_line(5.0, 5.0, 5.0, 5.0, 1.0, 0)
        assert grid.is_blocked(5, 5, 0) is True


class TestClearNet:
    def test_clear_net_removes_owned_cells(self) -> None:
        grid = _make_grid(resolution=1.0)
        grid.mark_rect(5.0, 5.0, 1.0, 1.0, 0, net_number=7)
        grid.mark_rect(2.0, 2.0, 1.0, 1.0, 0, net_number=8)

        assert grid.is_blocked(5, 5, 0) is True
        assert grid.is_blocked(2, 2, 0) is True

        grid.clear_net(7)
        # Net 7 cells should be unblocked
        assert grid.is_blocked(5, 5, 0) is False
        # Net 8 cells should remain blocked
        assert grid.is_blocked(2, 2, 0) is True


class TestGetStats:
    def test_stats(self) -> None:
        grid = _make_grid(width=10, height=10, resolution=1.0, layers=["F.Cu"])
        grid.mark_rect(5.0, 5.0, 1.0, 1.0, 0)
        stats = grid.get_stats()
        assert stats["cols"] == 10
        assert stats["rows"] == 10
        assert stats["layers"] == 1
        assert stats["total_cells"] == 100
        assert stats["blocked_cells"] > 0


class TestBuildObstacleMap:
    def test_empty_board(self) -> None:
        bbox = BoundingBox(0, 0, 50, 50)
        grid = build_obstacle_map([], [], bbox)
        assert grid.cols > 0
        assert grid.rows > 0
        # Boundary cells should be blocked
        stats = grid.get_stats()
        assert stats["blocked_cells"] > 0

    def test_with_footprint(self) -> None:
        bbox = BoundingBox(0, 0, 20, 20)
        pad = Pad(
            number="1",
            pad_type="smd",
            shape="rect",
            position=Position(0, 0),
            size=(1.0, 1.0),
            layers=["F.Cu"],
            net_number=1,
        )
        fp = Footprint(
            library="R_0402",
            reference="R1",
            value="10k",
            position=Position(10, 10),
            layer="F.Cu",
            pads=[pad],
        )
        grid = build_obstacle_map([fp], [], bbox, resolution=0.5)
        # Pad area should be blocked
        col = grid.mm_to_col(10)
        row = grid.mm_to_row(10)
        assert grid.is_blocked(col, row, 0) is True

    def test_with_segment(self) -> None:
        bbox = BoundingBox(0, 0, 20, 20)
        seg = Segment(
            start=Position(5, 10),
            end=Position(15, 10),
            width=0.25,
            layer="F.Cu",
            net_number=1,
        )
        grid = build_obstacle_map([], [seg], bbox, resolution=0.5)
        # Midpoint of segment should be blocked
        col = grid.mm_to_col(10)
        row = grid.mm_to_row(10)
        assert grid.is_blocked(col, row, 0) is True

    def test_target_net_cleared(self) -> None:
        bbox = BoundingBox(0, 0, 20, 20)
        pad = Pad(
            number="1",
            pad_type="smd",
            shape="rect",
            position=Position(0, 0),
            size=(2.0, 2.0),
            layers=["F.Cu"],
            net_number=5,
        )
        fp = Footprint(
            library="R_0402",
            reference="R1",
            value="10k",
            position=Position(10, 10),
            layer="F.Cu",
            pads=[pad],
        )
        grid = build_obstacle_map([fp], [], bbox, resolution=0.5, target_net=5)
        col = grid.mm_to_col(10)
        row = grid.mm_to_row(10)
        # Target net cells should be cleared
        assert grid.is_blocked(col, row, 0) is False

    def test_wildcard_layer_pads(self) -> None:
        bbox = BoundingBox(0, 0, 20, 20)
        pad = Pad(
            number="1",
            pad_type="thru_hole",
            shape="circle",
            position=Position(0, 0),
            size=(1.5, 1.5),
            layers=["*.Cu"],
            net_number=1,
        )
        fp = Footprint(
            library="Conn",
            reference="J1",
            value="Header",
            position=Position(10, 10),
            layer="F.Cu",
            pads=[pad],
        )
        grid = build_obstacle_map([fp], [], bbox, resolution=0.5)
        col = grid.mm_to_col(10)
        row = grid.mm_to_row(10)
        # Should be blocked on both layers
        assert grid.is_blocked(col, row, 0) is True
        assert grid.is_blocked(col, row, 1) is True
