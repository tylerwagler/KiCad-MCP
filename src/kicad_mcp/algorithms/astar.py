"""A* pathfinding engine for PCB auto-routing.

Supports multi-layer routing with via cost, 45-degree and Manhattan modes,
and path post-processing (co-linear collapse, via detection).
"""

from __future__ import annotations

import heapq
import math
from typing import Any

from .grid import ObstacleMap
from .types import BatchRouteResult, RouteResult, Waypoint

# Type alias for 3D grid node
Node = tuple[int, int, int]  # (col, row, layer_idx)

SQRT2 = math.sqrt(2)

# 8 planar directions: (dcol, drow, cost)
_DIAG_MOVES: list[tuple[int, int, float]] = [
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, SQRT2),
    (1, -1, SQRT2),
    (-1, 1, SQRT2),
    (-1, -1, SQRT2),
]

# 4 cardinal directions only
_CARDINAL_MOVES: list[tuple[int, int, float]] = [
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
]


def _heuristic(node: Node, goal: Node, diagonal: bool, via_cost: float) -> float:
    """Admissible heuristic for A*.

    - 45-degree: Chebyshev distance with diagonal cost
    - Manhattan: L1 distance
    - Adds via_cost if layers differ
    """
    dx = abs(node[0] - goal[0])
    dy = abs(node[1] - goal[1])

    h = max(dx, dy) + (SQRT2 - 1) * min(dx, dy) if diagonal else float(dx + dy)

    # Penalize layer mismatch
    if node[2] != goal[2]:
        h += via_cost

    return h


def astar_search(
    grid: ObstacleMap,
    start: Node,
    goal: Node,
    via_cost: float = 5.0,
    diagonal: bool = True,
    max_iterations: int = 500_000,
) -> list[Node] | None:
    """Run A* on the obstacle grid, returning the path or None.

    Args:
        grid: The obstacle map.
        start: Start node (col, row, layer_idx).
        goal: Goal node (col, row, layer_idx).
        via_cost: Cost for changing layers (via insertion).
        diagonal: Allow 45-degree moves.
        max_iterations: Safety limit to prevent infinite loops.

    Returns:
        List of nodes from start to goal, or None if no path found.
    """
    if start == goal:
        return [start]

    if grid.is_blocked(*start) or grid.is_blocked(*goal):
        return None

    moves = _DIAG_MOVES if diagonal else _CARDINAL_MOVES
    num_layers = len(grid.layers)

    # Priority queue: (f_score, tie_breaker, node)
    open_set: list[tuple[float, int, Node]] = []
    counter = 0
    h0 = _heuristic(start, goal, diagonal, via_cost)
    heapq.heappush(open_set, (h0, counter, start))
    counter += 1

    came_from: dict[Node, Node] = {}
    g_score: dict[Node, float] = {start: 0.0}
    closed_set: set[Node] = set()

    iterations = 0

    while open_set:
        iterations += 1
        if iterations > max_iterations:
            return None  # safety limit

        _, _, current = heapq.heappop(open_set)

        # Skip if already processed (found a better path)
        if current in closed_set:
            continue
        closed_set.add(current)

        if current == goal:
            # Reconstruct path
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        c, r, li = current
        current_g = g_score.get(current, float("inf"))

        # Planar moves on same layer
        for dc, dr, move_cost in moves:
            nc, nr = c + dc, r + dr
            if not grid.in_bounds(nc, nr):
                continue
            neighbor: Node = (nc, nr, li)
            if grid.is_blocked(nc, nr, li):
                continue

            tentative_g = current_g + move_cost
            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f = tentative_g + _heuristic(neighbor, goal, diagonal, via_cost)
                heapq.heappush(open_set, (f, counter, neighbor))
                counter += 1

        # Layer changes (via insertion) at same position
        for nli in range(num_layers):
            if nli == li:
                continue
            neighbor = (c, r, nli)
            if grid.is_blocked(c, r, nli):
                continue

            tentative_g = current_g + via_cost
            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f = tentative_g + _heuristic(neighbor, goal, diagonal, via_cost)
                heapq.heappush(open_set, (f, counter, neighbor))
                counter += 1

    return None  # no path found


def _collapse_collinear(waypoints: list[Waypoint]) -> list[Waypoint]:
    """Remove intermediate waypoints that are co-linear and on the same layer."""
    if len(waypoints) <= 2:
        return list(waypoints)

    result = [waypoints[0]]
    for i in range(1, len(waypoints) - 1):
        prev = result[-1]
        curr = waypoints[i]
        nxt = waypoints[i + 1]

        # Different layer means keep the point
        if curr.layer != prev.layer or curr.layer != nxt.layer:
            result.append(curr)
            continue

        # Check co-linearity: direction from prev→curr == curr→next
        dx1 = curr.x - prev.x
        dy1 = curr.y - prev.y
        dx2 = nxt.x - curr.x
        dy2 = nxt.y - curr.y

        # Cross product ≈ 0 means co-linear
        cross = dx1 * dy2 - dy1 * dx2
        if abs(cross) > 1e-9:
            result.append(curr)

    result.append(waypoints[-1])
    return result


def _detect_vias(waypoints: list[Waypoint]) -> list[Waypoint]:
    """Find waypoints where a layer transition occurs."""
    vias = []
    for i in range(1, len(waypoints)):
        if waypoints[i].layer != waypoints[i - 1].layer:
            vias.append(waypoints[i - 1])
    return vias


def astar_route(
    grid: ObstacleMap,
    start_x: float,
    start_y: float,
    start_layer: str,
    end_x: float,
    end_y: float,
    end_layer: str,
    net_name: str = "",
    net_number: int = 0,
    via_cost: float = 5.0,
    diagonal: bool = True,
    max_iterations: int = 500_000,
) -> RouteResult:
    """Route between two points using A* pathfinding.

    Args:
        grid: Obstacle map.
        start_x, start_y: Start coordinates (mm).
        start_layer: Start copper layer name.
        end_x, end_y: End coordinates (mm).
        end_layer: End copper layer name.
        net_name: Net name for labeling.
        net_number: Net number.
        via_cost: Cost penalty for vias.
        diagonal: Allow 45-degree routing.
        max_iterations: Safety limit.

    Returns:
        RouteResult with waypoints, via locations, and cost.
    """
    try:
        start_li = grid.layer_index(start_layer)
        end_li = grid.layer_index(end_layer)
    except ValueError as e:
        return RouteResult(success=False, net_name=net_name, net_number=net_number, error=str(e))

    start_node: Node = (
        grid.mm_to_col(start_x),
        grid.mm_to_row(start_y),
        start_li,
    )
    goal_node: Node = (grid.mm_to_col(end_x), grid.mm_to_row(end_y), end_li)

    path = astar_search(
        grid,
        start_node,
        goal_node,
        via_cost=via_cost,
        diagonal=diagonal,
        max_iterations=max_iterations,
    )

    if path is None:
        return RouteResult(
            success=False,
            net_name=net_name,
            net_number=net_number,
            error="No path found",
        )

    # Convert grid path to waypoints
    raw_waypoints = [
        Waypoint(
            x=grid.col_to_mm(c),
            y=grid.row_to_mm(r),
            layer=grid.layers[li],
        )
        for c, r, li in path
    ]

    # Post-process: collapse co-linear, detect vias
    waypoints = _collapse_collinear(raw_waypoints)
    via_locations = _detect_vias(waypoints)

    # Count segments (transitions between consecutive waypoints on same layer)
    seg_count = 0
    for i in range(1, len(waypoints)):
        if waypoints[i].layer == waypoints[i - 1].layer:
            seg_count += 1

    # Compute cost from g_score (approximate from path length)
    total_cost = 0.0
    for i in range(1, len(raw_waypoints)):
        p, q = raw_waypoints[i - 1], raw_waypoints[i]
        if p.layer != q.layer:
            total_cost += via_cost
        else:
            total_cost += math.hypot(q.x - p.x, q.y - p.y) / grid.resolution

    return RouteResult(
        success=True,
        net_name=net_name,
        net_number=net_number,
        waypoints=waypoints,
        via_locations=via_locations,
        segment_count=seg_count,
        via_count=len(via_locations),
        total_cost=total_cost,
    )


def _minimum_spanning_tree(
    pads: list[dict[str, Any]],
) -> list[tuple[int, int]]:
    """Compute MST edges over pad positions using Prim's algorithm.

    Args:
        pads: List of pad dicts with "x" and "y" keys.

    Returns:
        List of (i, j) index pairs forming the MST.
    """
    n = len(pads)
    if n <= 1:
        return []

    in_tree = [False] * n
    min_cost = [float("inf")] * n
    min_edge: list[int] = [-1] * n  # edge partner for each node
    edges: list[tuple[int, int]] = []

    min_cost[0] = 0.0
    in_tree[0] = True

    # Initialize costs from node 0
    for j in range(1, n):
        dx = pads[j]["x"] - pads[0]["x"]
        dy = pads[j]["y"] - pads[0]["y"]
        min_cost[j] = math.hypot(dx, dy)
        min_edge[j] = 0

    for _ in range(n - 1):
        # Find cheapest node not in tree
        best = -1
        best_cost = float("inf")
        for j in range(n):
            if not in_tree[j] and min_cost[j] < best_cost:
                best = j
                best_cost = min_cost[j]

        if best == -1:
            break

        in_tree[best] = True
        edges.append((min_edge[best], best))

        # Update costs
        for j in range(n):
            if not in_tree[j]:
                dx = pads[j]["x"] - pads[best]["x"]
                dy = pads[j]["y"] - pads[best]["y"]
                dist = math.hypot(dx, dy)
                if dist < min_cost[j]:
                    min_cost[j] = dist
                    min_edge[j] = best

    return edges


def route_all_nets(
    grid: ObstacleMap,
    unrouted_nets: list[dict[str, Any]],
    via_cost: float = 5.0,
    diagonal: bool = True,
    max_nets: int | None = None,
    preferred_layer: str | None = None,
) -> BatchRouteResult:
    """Route all unrouted nets, shortest-first.

    Sorts nets by shortest pad-pair distance, routes each sequentially,
    and updates the obstacle map after each success.

    Args:
        grid: Obstacle map (will be mutated as nets are routed).
        unrouted_nets: From SessionManager.get_ratsnest().
        via_cost: Cost for layer changes.
        diagonal: Allow 45-degree routing.
        max_nets: Optional limit on number of nets to route.
        preferred_layer: Layer to prefer for routing start/end.
    """
    result = BatchRouteResult()

    # Sort nets by shortest pad-pair distance (easier nets first)
    def _net_min_distance(net: dict[str, Any]) -> float:
        pads = net["pads"]
        if len(pads) < 2:
            return float("inf")
        min_d = float("inf")
        for i in range(len(pads)):
            for j in range(i + 1, len(pads)):
                dx = pads[i]["x"] - pads[j]["x"]
                dy = pads[i]["y"] - pads[j]["y"]
                min_d = min(min_d, math.hypot(dx, dy))
        return min_d

    sorted_nets = sorted(unrouted_nets, key=_net_min_distance)

    if max_nets is not None:
        sorted_nets = sorted_nets[:max_nets]

    default_layer = preferred_layer or grid.layers[0]

    for net_info in sorted_nets:
        net_name = net_info["net_name"]
        net_number = net_info["net_number"]
        pads = net_info["pads"]

        if len(pads) < 2:
            continue

        # Clear this net's obstacles so it can route through own copper
        grid.clear_net(net_number)

        # Compute MST for multi-pin nets
        mst_edges = _minimum_spanning_tree(pads)

        net_success = True
        net_segments = 0
        net_vias = 0

        for i, j in mst_edges:
            pad_a = pads[i]
            pad_b = pads[j]

            route = astar_route(
                grid,
                pad_a["x"],
                pad_a["y"],
                default_layer,
                pad_b["x"],
                pad_b["y"],
                default_layer,
                net_name=net_name,
                net_number=net_number,
                via_cost=via_cost,
                diagonal=diagonal,
            )

            if route.success:
                net_segments += route.segment_count
                net_vias += route.via_count
                result.results.append(route)

                # Mark routed path as obstacles for subsequent nets
                for wp_idx in range(1, len(route.waypoints)):
                    prev_wp = route.waypoints[wp_idx - 1]
                    curr_wp = route.waypoints[wp_idx]
                    if prev_wp.layer == curr_wp.layer:
                        try:
                            li = grid.layer_index(curr_wp.layer)
                        except ValueError:
                            continue
                        grid.mark_segment_line(
                            prev_wp.x,
                            prev_wp.y,
                            curr_wp.x,
                            curr_wp.y,
                            grid.resolution,  # minimal width for grid
                            li,
                            net_number,
                        )
            else:
                net_success = False
                result.results.append(route)

        if net_success:
            result.routed_count += 1
            result.routed_nets.append(net_name)
            result.total_segments += net_segments
            result.total_vias += net_vias
        else:
            result.failed_count += 1
            result.failed_nets.append(net_name)

    return result
