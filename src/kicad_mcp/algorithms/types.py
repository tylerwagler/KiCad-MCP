"""Shared dataclasses for auto-routing and placement algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GridConfig:
    """Configuration for the routing grid."""

    resolution: float = 0.25  # mm per cell
    clearance: float = 0.2  # mm clearance around obstacles
    via_cost: float = 5.0  # cost penalty for layer change
    diagonal: bool = True  # allow 45-degree routing


@dataclass(frozen=True)
class Waypoint:
    """A point along a routed path."""

    x: float  # board mm
    y: float  # board mm
    layer: str  # e.g. "F.Cu"

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "layer": self.layer}


@dataclass
class RouteResult:
    """Result of routing a single net or pad pair."""

    success: bool
    net_name: str = ""
    net_number: int = 0
    waypoints: list[Waypoint] = field(default_factory=list)
    via_locations: list[Waypoint] = field(default_factory=list)
    segment_count: int = 0
    via_count: int = 0
    total_cost: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "success": self.success,
            "net_name": self.net_name,
            "net_number": self.net_number,
            "segment_count": self.segment_count,
            "via_count": self.via_count,
            "total_cost": round(self.total_cost, 3),
        }
        if self.waypoints:
            d["waypoints"] = [w.to_dict() for w in self.waypoints]
        if self.via_locations:
            d["via_locations"] = [v.to_dict() for v in self.via_locations]
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class BatchRouteResult:
    """Result of batch-routing multiple nets."""

    routed_count: int = 0
    failed_count: int = 0
    total_segments: int = 0
    total_vias: int = 0
    routed_nets: list[str] = field(default_factory=list)
    failed_nets: list[str] = field(default_factory=list)
    results: list[RouteResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "routed_count": self.routed_count,
            "failed_count": self.failed_count,
            "total_segments": self.total_segments,
            "total_vias": self.total_vias,
            "routed_nets": self.routed_nets,
            "failed_nets": self.failed_nets,
        }


@dataclass
class ComponentPlacement:
    """A component's placement state."""

    reference: str
    x: float
    y: float
    width: float  # estimated bbox width from pad extents
    height: float  # estimated bbox height from pad extents
    locked: bool = False
    net_connections: list[int] = field(default_factory=list)  # net numbers

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
            "locked": self.locked,
        }


@dataclass
class PlacementResult:
    """Result of placement optimization."""

    movements: list[dict[str, Any]] = field(default_factory=list)
    hpwl_before: float = 0.0
    hpwl_after: float = 0.0
    hpwl_reduction_pct: float = 0.0
    overlap_count: int = 0
    iterations_used: int = 0
    converged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "movement_count": len(self.movements),
            "movements": self.movements,
            "hpwl_before": round(self.hpwl_before, 3),
            "hpwl_after": round(self.hpwl_after, 3),
            "hpwl_reduction_pct": round(self.hpwl_reduction_pct, 2),
            "overlap_count": self.overlap_count,
            "iterations_used": self.iterations_used,
            "converged": self.converged,
        }


@dataclass
class PlacementEvaluation:
    """Read-only evaluation of current placement quality."""

    hpwl_total: float = 0.0
    overlap_count: int = 0
    component_count: int = 0
    density: float = 0.0  # component area / board area
    per_net_wirelength: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hpwl_total": round(self.hpwl_total, 3),
            "overlap_count": self.overlap_count,
            "component_count": self.component_count,
            "density": round(self.density, 4),
            "per_net_wirelength": self.per_net_wirelength,
        }


@dataclass
class RoutePreview:
    """Quick feasibility estimate for a route."""

    manhattan_distance: float = 0.0
    straight_line_distance: float = 0.0
    obstacle_density: float = 0.0  # fraction of cells blocked in corridor
    estimated_feasible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "manhattan_distance": round(self.manhattan_distance, 3),
            "straight_line_distance": round(self.straight_line_distance, 3),
            "obstacle_density": round(self.obstacle_density, 4),
            "estimated_feasible": self.estimated_feasible,
        }
