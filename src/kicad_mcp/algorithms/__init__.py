"""Auto-routing and placement algorithms — pure Python, zero dependencies."""

from .astar import astar_route, route_all_nets
from .grid import ObstacleMap, build_obstacle_map
from .placement import (
    compute_hpwl,
    evaluate_placement,
    force_directed_placement,
    spread_components,
)
from .types import (
    ComponentPlacement,
    GridConfig,
    PlacementResult,
    RouteResult,
    Waypoint,
)

__all__ = [
    "ComponentPlacement",
    "GridConfig",
    "ObstacleMap",
    "PlacementResult",
    "RouteResult",
    "Waypoint",
    "astar_route",
    "build_obstacle_map",
    "compute_hpwl",
    "evaluate_placement",
    "force_directed_placement",
    "route_all_nets",
    "spread_components",
]
