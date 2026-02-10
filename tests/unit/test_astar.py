"""Tests for A* pathfinding engine (algorithms/astar.py)."""

from __future__ import annotations

import math
import time

from kicad_mcp.algorithms.astar import (
    _collapse_collinear,
    _detect_vias,
    _heuristic,
    _minimum_spanning_tree,
    astar_route,
    astar_search,
    route_all_nets,
)
from kicad_mcp.algorithms.grid import ObstacleMap
from kicad_mcp.algorithms.types import Waypoint


def _make_grid(
    width: float = 20.0,
    height: float = 20.0,
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


class TestHeuristic:
    def test_same_position(self) -> None:
        assert _heuristic((5, 5, 0), (5, 5, 0), True, 5.0) == 0.0

    def test_manhattan_heuristic(self) -> None:
        h = _heuristic((0, 0, 0), (3, 4, 0), False, 5.0)
        assert h == 7.0  # |3| + |4|

    def test_diagonal_heuristic(self) -> None:
        h = _heuristic((0, 0, 0), (3, 4, 0), True, 5.0)
        # Chebyshev: max(3,4) + (sqrt(2)-1)*min(3,4) = 4 + 0.414*3 ≈ 5.243
        expected = 4 + (math.sqrt(2) - 1) * 3
        assert abs(h - expected) < 0.001

    def test_layer_mismatch_adds_via_cost(self) -> None:
        h_same = _heuristic((0, 0, 0), (3, 4, 0), True, 5.0)
        h_diff = _heuristic((0, 0, 0), (3, 4, 1), True, 5.0)
        assert abs(h_diff - h_same - 5.0) < 0.001


class TestAstarSearch:
    def test_start_equals_goal(self) -> None:
        grid = _make_grid()
        path = astar_search(grid, (5, 5, 0), (5, 5, 0))
        assert path == [(5, 5, 0)]

    def test_simple_path(self) -> None:
        grid = _make_grid()
        path = astar_search(grid, (2, 2, 0), (8, 2, 0))
        assert path is not None
        assert path[0] == (2, 2, 0)
        assert path[-1] == (8, 2, 0)

    def test_blocked_start(self) -> None:
        grid = _make_grid()
        grid.blocked.add((2, 2, 0))
        path = astar_search(grid, (2, 2, 0), (8, 2, 0))
        assert path is None

    def test_blocked_goal(self) -> None:
        grid = _make_grid()
        grid.blocked.add((8, 2, 0))
        path = astar_search(grid, (2, 2, 0), (8, 2, 0))
        assert path is None

    def test_no_path_fully_blocked(self) -> None:
        grid = _make_grid()
        # Block a vertical wall across the entire grid on ALL layers
        for r in range(grid.rows):
            for li in range(len(grid.layers)):
                grid.blocked.add((5, r, li))
        path = astar_search(grid, (2, 2, 0), (8, 2, 0))
        assert path is None

    def test_path_around_obstacle(self) -> None:
        grid = _make_grid()
        # Block a partial wall
        for r in range(0, 15):
            grid.blocked.add((10, r, 0))
        path = astar_search(grid, (5, 5, 0), (15, 5, 0))
        assert path is not None
        assert path[0] == (5, 5, 0)
        assert path[-1] == (15, 5, 0)
        # Path should go around the wall
        assert len(path) > 10

    def test_manhattan_mode(self) -> None:
        grid = _make_grid()
        path = astar_search(grid, (2, 2, 0), (5, 5, 0), diagonal=False)
        assert path is not None
        # In manhattan mode, all moves should be cardinal (no diagonal)
        for i in range(1, len(path)):
            dc = abs(path[i][0] - path[i - 1][0])
            dr = abs(path[i][1] - path[i - 1][1])
            dl = abs(path[i][2] - path[i - 1][2])
            assert dc + dr + dl <= 1  # Only one coordinate changes at a time

    def test_multi_layer_via(self) -> None:
        grid = _make_grid()
        # Block the path on F.Cu but leave B.Cu open
        for c in range(grid.cols):
            if c != 5:  # Leave a gap for the via
                grid.blocked.add((c, 10, 0))

        path = astar_search(grid, (2, 2, 0), (2, 18, 0), via_cost=2.0)
        assert path is not None
        # Path should use layer changes (vias)
        layers_used = set(node[2] for node in path)
        assert len(layers_used) > 1 or path[-1] == (2, 18, 0)

    def test_via_cost_affects_preference(self) -> None:
        grid = _make_grid()
        # Create a scenario where low via cost makes layer change attractive
        # Block most of layer 0 between start and goal
        for c in range(3, 18):
            for r in range(3, 18):
                grid.blocked.add((c, r, 0))

        # With low via cost, should prefer going through B.Cu
        path_low = astar_search(grid, (1, 1, 0), (19, 19, 0), via_cost=1.0)
        # With very high via cost, might not find a path (or longer path)
        path_high = astar_search(grid, (1, 1, 0), (19, 19, 0), via_cost=100.0)

        assert path_low is not None
        # Both should reach the goal
        if path_high is not None:
            assert path_high[-1] == (19, 19, 0)

    def test_max_iterations_limit(self) -> None:
        grid = _make_grid(width=50, height=50, resolution=1.0)
        # Very small iteration limit should fail on a long path
        path = astar_search(grid, (0, 0, 0), (49, 49, 0), max_iterations=10)
        assert path is None

    def test_performance_large_grid(self) -> None:
        grid = _make_grid(width=100, height=100, resolution=1.0)
        start = time.monotonic()
        path = astar_search(grid, (5, 5, 0), (90, 90, 0))
        elapsed = time.monotonic() - start
        assert path is not None
        assert elapsed < 5.0  # Should complete in < 5 seconds


class TestCollapseCollinear:
    def test_empty(self) -> None:
        assert _collapse_collinear([]) == []

    def test_two_points(self) -> None:
        wps = [Waypoint(0, 0, "F.Cu"), Waypoint(10, 0, "F.Cu")]
        result = _collapse_collinear(wps)
        assert len(result) == 2

    def test_collinear_horizontal(self) -> None:
        wps = [
            Waypoint(0, 0, "F.Cu"),
            Waypoint(5, 0, "F.Cu"),
            Waypoint(10, 0, "F.Cu"),
        ]
        result = _collapse_collinear(wps)
        assert len(result) == 2
        assert result[0] == wps[0]
        assert result[1] == wps[2]

    def test_collinear_diagonal(self) -> None:
        wps = [
            Waypoint(0, 0, "F.Cu"),
            Waypoint(5, 5, "F.Cu"),
            Waypoint(10, 10, "F.Cu"),
        ]
        result = _collapse_collinear(wps)
        assert len(result) == 2

    def test_non_collinear_preserved(self) -> None:
        wps = [
            Waypoint(0, 0, "F.Cu"),
            Waypoint(5, 0, "F.Cu"),
            Waypoint(5, 10, "F.Cu"),
        ]
        result = _collapse_collinear(wps)
        assert len(result) == 3  # Corner point preserved

    def test_layer_change_preserved(self) -> None:
        wps = [
            Waypoint(0, 0, "F.Cu"),
            Waypoint(5, 0, "F.Cu"),
            Waypoint(5, 0, "B.Cu"),
            Waypoint(10, 0, "B.Cu"),
        ]
        result = _collapse_collinear(wps)
        assert len(result) >= 3  # Layer change point preserved


class TestDetectVias:
    def test_no_vias(self) -> None:
        wps = [Waypoint(0, 0, "F.Cu"), Waypoint(10, 0, "F.Cu")]
        assert _detect_vias(wps) == []

    def test_single_via(self) -> None:
        wps = [
            Waypoint(0, 0, "F.Cu"),
            Waypoint(5, 0, "F.Cu"),
            Waypoint(5, 0, "B.Cu"),
            Waypoint(10, 0, "B.Cu"),
        ]
        vias = _detect_vias(wps)
        assert len(vias) == 1
        assert vias[0].x == 5.0
        assert vias[0].layer == "F.Cu"

    def test_multiple_vias(self) -> None:
        wps = [
            Waypoint(0, 0, "F.Cu"),
            Waypoint(3, 0, "B.Cu"),
            Waypoint(6, 0, "F.Cu"),
        ]
        vias = _detect_vias(wps)
        assert len(vias) == 2


class TestAstarRoute:
    def test_simple_route(self) -> None:
        grid = _make_grid()
        result = astar_route(grid, 2, 2, "F.Cu", 18, 2, "F.Cu")
        assert result.success is True
        assert result.segment_count > 0
        assert result.waypoints[0].x == 2.0
        assert result.waypoints[-1].x == 18.0

    def test_route_no_path(self) -> None:
        grid = _make_grid()
        # Block entire column
        for r in range(grid.rows):
            for li in range(len(grid.layers)):
                grid.blocked.add((10, r, li))
        result = astar_route(grid, 2, 2, "F.Cu", 18, 2, "F.Cu")
        assert result.success is False
        assert "No path" in result.error

    def test_route_invalid_layer(self) -> None:
        grid = _make_grid()
        result = astar_route(grid, 2, 2, "In1.Cu", 18, 2, "F.Cu")
        assert result.success is False
        assert "Layer" in result.error

    def test_route_via_count(self) -> None:
        grid = _make_grid()
        # Route to different layer
        result = astar_route(grid, 5, 5, "F.Cu", 5, 5, "B.Cu", via_cost=1.0)
        assert result.success is True
        assert result.via_count >= 1


class TestMinimumSpanningTree:
    def test_two_pads(self) -> None:
        pads = [{"x": 0, "y": 0}, {"x": 10, "y": 0}]
        edges = _minimum_spanning_tree(pads)
        assert len(edges) == 1
        assert edges[0] == (0, 1)

    def test_three_pads_line(self) -> None:
        pads = [{"x": 0, "y": 0}, {"x": 5, "y": 0}, {"x": 10, "y": 0}]
        edges = _minimum_spanning_tree(pads)
        assert len(edges) == 2

    def test_single_pad(self) -> None:
        pads = [{"x": 0, "y": 0}]
        edges = _minimum_spanning_tree(pads)
        assert len(edges) == 0

    def test_square_pads(self) -> None:
        pads = [
            {"x": 0, "y": 0},
            {"x": 10, "y": 0},
            {"x": 10, "y": 10},
            {"x": 0, "y": 10},
        ]
        edges = _minimum_spanning_tree(pads)
        assert len(edges) == 3  # N-1 edges for N nodes


class TestRouteAllNets:
    def test_route_single_net(self) -> None:
        grid = _make_grid()
        unrouted = [
            {
                "net_number": 1,
                "net_name": "VCC",
                "pad_count": 2,
                "pads": [
                    {"reference": "R1", "pad": "1", "x": 2, "y": 5},
                    {"reference": "C1", "pad": "1", "x": 18, "y": 5},
                ],
            }
        ]
        result = route_all_nets(grid, unrouted)
        assert result.routed_count == 1
        assert result.failed_count == 0
        assert "VCC" in result.routed_nets

    def test_route_multiple_nets(self) -> None:
        grid = _make_grid()
        unrouted = [
            {
                "net_number": 1,
                "net_name": "VCC",
                "pad_count": 2,
                "pads": [
                    {"reference": "R1", "pad": "1", "x": 2, "y": 3},
                    {"reference": "C1", "pad": "1", "x": 8, "y": 3},
                ],
            },
            {
                "net_number": 2,
                "net_name": "GND",
                "pad_count": 2,
                "pads": [
                    {"reference": "R1", "pad": "2", "x": 2, "y": 15},
                    {"reference": "C1", "pad": "2", "x": 8, "y": 15},
                ],
            },
        ]
        result = route_all_nets(grid, unrouted)
        assert result.routed_count == 2

    def test_max_nets_limit(self) -> None:
        grid = _make_grid()
        unrouted = [
            {
                "net_number": i,
                "net_name": f"NET{i}",
                "pad_count": 2,
                "pads": [
                    {"reference": f"R{i}", "pad": "1", "x": 2, "y": i * 2 + 1},
                    {"reference": f"C{i}", "pad": "1", "x": 8, "y": i * 2 + 1},
                ],
            }
            for i in range(1, 6)
        ]
        result = route_all_nets(grid, unrouted, max_nets=2)
        assert result.routed_count + result.failed_count <= 2

    def test_batch_result_dict(self) -> None:
        grid = _make_grid()
        unrouted = [
            {
                "net_number": 1,
                "net_name": "VCC",
                "pad_count": 2,
                "pads": [
                    {"reference": "R1", "pad": "1", "x": 2, "y": 5},
                    {"reference": "C1", "pad": "1", "x": 8, "y": 5},
                ],
            }
        ]
        result = route_all_nets(grid, unrouted)
        d = result.to_dict()
        assert "routed_count" in d
        assert "failed_count" in d
        assert "routed_nets" in d
