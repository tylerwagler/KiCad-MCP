"""Force-directed placement solver with simulated annealing.

Pure Python, zero dependencies. Optimizes component placement by:
1. Attractive forces: pull connected components together
2. Repulsive forces: push overlapping components apart
3. Boundary clamping: keep everything inside the board outline
"""

from __future__ import annotations

import math
from typing import Any

from ..schema.board import Footprint
from ..schema.common import BoundingBox
from .types import ComponentPlacement, PlacementEvaluation, PlacementResult


def _estimate_bbox(fp: Footprint) -> tuple[float, float]:
    """Estimate footprint bounding box from pad extents.

    Returns (width, height) in mm.
    """
    if not fp.pads:
        return (1.0, 1.0)  # default 1mm square

    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")

    for pad in fp.pads:
        px = pad.position.x
        py = pad.position.y
        hw = pad.size[0] / 2
        hh = pad.size[1] / 2
        min_x = min(min_x, px - hw)
        max_x = max(max_x, px + hw)
        min_y = min(min_y, py - hh)
        max_y = max(max_y, py + hh)

    w = max_x - min_x
    h = max_y - min_y
    return (max(w, 0.1), max(h, 0.1))


def _build_net_map(
    footprints: list[Footprint],
) -> dict[int, list[str]]:
    """Build net_number → list of component references."""
    net_map: dict[int, list[str]] = {}
    for fp in footprints:
        for pad in fp.pads:
            if pad.net_number is not None and pad.net_number > 0:
                net_map.setdefault(pad.net_number, [])
                if fp.reference not in net_map[pad.net_number]:
                    net_map[pad.net_number].append(fp.reference)
    return net_map


def _build_connection_weights(
    net_map: dict[int, list[str]],
) -> dict[tuple[str, str], int]:
    """Build pairwise connection weights between components.

    Weight = number of shared nets between two components.
    """
    weights: dict[tuple[str, str], int] = {}
    for refs in net_map.values():
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                key = (min(refs[i], refs[j]), max(refs[i], refs[j]))
                weights[key] = weights.get(key, 0) + 1
    return weights


def _build_placements(
    footprints: list[Footprint],
    locked_refs: set[str],
) -> dict[str, ComponentPlacement]:
    """Convert footprints to ComponentPlacement objects."""
    placements: dict[str, ComponentPlacement] = {}
    for fp in footprints:
        w, h = _estimate_bbox(fp)
        nets = []
        for pad in fp.pads:
            if pad.net_number is not None and pad.net_number > 0 and pad.net_number not in nets:
                nets.append(pad.net_number)
        placements[fp.reference] = ComponentPlacement(
            reference=fp.reference,
            x=fp.position.x,
            y=fp.position.y,
            width=w,
            height=h,
            locked=fp.reference in locked_refs,
            net_connections=nets,
        )
    return placements


def compute_hpwl(
    placements: dict[str, ComponentPlacement],
    net_map: dict[int, list[str]],
) -> float:
    """Compute Half-Perimeter Wire Length (standard EDA metric).

    HPWL = Σ_net (max_x - min_x + max_y - min_y)
    """
    total = 0.0
    for _net_num, refs in net_map.items():
        if len(refs) < 2:
            continue
        xs = []
        ys = []
        for ref in refs:
            if ref in placements:
                xs.append(placements[ref].x)
                ys.append(placements[ref].y)
        if len(xs) >= 2:
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return total


def _count_overlaps(
    placements: dict[str, ComponentPlacement],
    clearance: float,
) -> int:
    """Count pairs of overlapping component bounding boxes."""
    refs = list(placements.keys())
    count = 0
    for i in range(len(refs)):
        a = placements[refs[i]]
        for j in range(i + 1, len(refs)):
            b = placements[refs[j]]
            # Axis-aligned bbox overlap check with clearance
            a_half_w = a.width / 2 + clearance / 2
            a_half_h = a.height / 2 + clearance / 2
            b_half_w = b.width / 2 + clearance / 2
            b_half_h = b.height / 2 + clearance / 2

            if abs(a.x - b.x) < a_half_w + b_half_w and abs(a.y - b.y) < a_half_h + b_half_h:
                count += 1
    return count


def force_directed_placement(
    footprints: list[Footprint],
    board_bbox: BoundingBox,
    locked_references: list[str] | None = None,
    max_iterations: int = 500,
    min_clearance: float = 0.5,
    k_attract: float = 0.01,
    k_repel: float = 2.0,
    initial_temperature: float = 10.0,
    cooling_rate: float = 0.95,
    convergence_threshold: float = 0.01,
) -> PlacementResult:
    """Run force-directed placement optimization.

    Args:
        footprints: Current footprint positions.
        board_bbox: Board boundary.
        locked_references: Components to keep fixed.
        max_iterations: Maximum solver iterations.
        min_clearance: Minimum clearance between components (mm).
        k_attract: Attractive force constant.
        k_repel: Repulsive force constant.
        initial_temperature: Starting temperature for SA schedule.
        cooling_rate: Temperature decay per iteration.
        convergence_threshold: Stop when max displacement < this (mm).

    Returns:
        PlacementResult with new positions and metrics.
    """
    locked_refs = set(locked_references or [])
    placements = _build_placements(footprints, locked_refs)
    net_map = _build_net_map(footprints)
    conn_weights = _build_connection_weights(net_map)

    # Save original positions
    original_positions: dict[str, tuple[float, float]] = {
        ref: (p.x, p.y) for ref, p in placements.items()
    }

    hpwl_before = compute_hpwl(placements, net_map)

    # Min separation for repulsive cutoff
    min_sep = min_clearance + 1.0  # include typical component size
    repulsive_cutoff = 3.0 * min_sep

    temperature = initial_temperature
    converged = False
    iterations_used = 0
    refs = [r for r in placements if not placements[r].locked]

    for iteration in range(max_iterations):
        iterations_used = iteration + 1

        # Accumulate forces
        forces: dict[str, tuple[float, float]] = {ref: (0.0, 0.0) for ref in refs}

        # Attractive forces: connected component pairs
        for (ref_a, ref_b), weight in conn_weights.items():
            if ref_a not in placements or ref_b not in placements:
                continue
            a = placements[ref_a]
            b = placements[ref_b]
            dx = b.x - a.x
            dy = b.y - a.y
            dist = math.hypot(dx, dy)
            if dist < 1e-6:
                continue

            force = k_attract * weight * dist
            fx = force * dx / dist
            fy = force * dy / dist

            if ref_a in forces:
                forces[ref_a] = (forces[ref_a][0] + fx, forces[ref_a][1] + fy)
            if ref_b in forces:
                forces[ref_b] = (forces[ref_b][0] - fx, forces[ref_b][1] - fy)

        # Repulsive forces: all unlocked pairs within cutoff
        for i in range(len(refs)):
            a = placements[refs[i]]
            for j in range(i + 1, len(refs)):
                b = placements[refs[j]]
                dx = b.x - a.x
                dy = b.y - a.y
                dist = math.hypot(dx, dy)

                if dist > repulsive_cutoff:
                    continue
                if dist < 0.01:
                    # Co-located: nudge apart with a deterministic offset
                    dx = 0.01 * (1 + (i % 7) * 0.1)
                    dy = 0.01 * (1 + (j % 7) * 0.1)
                    dist = math.hypot(dx, dy)

                force = k_repel / (dist * dist)
                fx = force * dx / dist
                fy = force * dy / dist

                forces[refs[i]] = (
                    forces[refs[i]][0] - fx,
                    forces[refs[i]][1] - fy,
                )
                forces[refs[j]] = (
                    forces[refs[j]][0] + fx,
                    forces[refs[j]][1] + fy,
                )

        # Apply forces with temperature limit
        max_disp = 0.0
        for ref in refs:
            fx, fy = forces[ref]
            disp = math.hypot(fx, fy)
            if disp > temperature:
                scale = temperature / disp
                fx *= scale
                fy *= scale
                disp = temperature

            placements[ref].x += fx
            placements[ref].y += fy
            max_disp = max(max_disp, disp)

        # Boundary clamping
        for ref in refs:
            p = placements[ref]
            half_w = p.width / 2
            half_h = p.height / 2
            p.x = max(board_bbox.min_x + half_w, min(board_bbox.max_x - half_w, p.x))
            p.y = max(board_bbox.min_y + half_h, min(board_bbox.max_y - half_h, p.y))

        # Cooling
        temperature *= cooling_rate

        # Convergence check
        if max_disp < convergence_threshold:
            converged = True
            break

    hpwl_after = compute_hpwl(placements, net_map)
    overlap_count = _count_overlaps(placements, min_clearance)

    # Build movement list
    movements = []
    for ref, p in placements.items():
        orig_x, orig_y = original_positions[ref]
        dx = p.x - orig_x
        dy = p.y - orig_y
        if abs(dx) > 0.001 or abs(dy) > 0.001:
            movements.append(
                {
                    "reference": ref,
                    "from_x": round(orig_x, 4),
                    "from_y": round(orig_y, 4),
                    "to_x": round(p.x, 4),
                    "to_y": round(p.y, 4),
                    "dx": round(dx, 4),
                    "dy": round(dy, 4),
                }
            )

    reduction_pct = 0.0
    if hpwl_before > 0:
        reduction_pct = (hpwl_before - hpwl_after) / hpwl_before * 100

    return PlacementResult(
        movements=movements,
        hpwl_before=hpwl_before,
        hpwl_after=hpwl_after,
        hpwl_reduction_pct=reduction_pct,
        overlap_count=overlap_count,
        iterations_used=iterations_used,
        converged=converged,
    )


def evaluate_placement(
    footprints: list[Footprint],
    board_bbox: BoundingBox,
    min_clearance: float = 0.5,
) -> PlacementEvaluation:
    """Evaluate current placement quality (read-only).

    Args:
        footprints: Current footprint positions.
        board_bbox: Board boundary.
        min_clearance: Clearance for overlap detection (mm).

    Returns:
        PlacementEvaluation with HPWL, overlap count, density, etc.
    """
    placements = _build_placements(footprints, set())
    net_map = _build_net_map(footprints)

    hpwl_total = compute_hpwl(placements, net_map)
    overlap_count = _count_overlaps(placements, min_clearance)

    # Component density
    component_area = sum(p.width * p.height for p in placements.values())
    board_area = board_bbox.width * board_bbox.height
    density = component_area / max(board_area, 1e-6)

    # Per-net wirelength
    per_net: list[dict[str, Any]] = []
    for net_num, refs in sorted(net_map.items()):
        if len(refs) < 2:
            continue
        xs = [placements[r].x for r in refs if r in placements]
        ys = [placements[r].y for r in refs if r in placements]
        if len(xs) >= 2:
            wl = (max(xs) - min(xs)) + (max(ys) - min(ys))
            per_net.append(
                {
                    "net_number": net_num,
                    "pad_count": len(refs),
                    "hpwl": round(wl, 3),
                }
            )

    return PlacementEvaluation(
        hpwl_total=hpwl_total,
        overlap_count=overlap_count,
        component_count=len(placements),
        density=density,
        per_net_wirelength=per_net,
    )


def spread_components(
    footprints: list[Footprint],
    board_bbox: BoundingBox,
    min_clearance: float = 0.5,
    max_iterations: int = 200,
) -> PlacementResult:
    """Quick overlap resolution using repulsive forces only.

    No attractive forces — just pushes overlapping components apart.

    Args:
        footprints: Current footprint positions.
        board_bbox: Board boundary.
        min_clearance: Minimum clearance between components (mm).
        max_iterations: Maximum iterations.

    Returns:
        PlacementResult with movements and remaining overlaps.
    """
    return force_directed_placement(
        footprints=footprints,
        board_bbox=board_bbox,
        locked_references=[],
        max_iterations=max_iterations,
        min_clearance=min_clearance,
        k_attract=0.0,  # no attractive forces
        k_repel=2.0,
        initial_temperature=5.0,
        cooling_rate=0.97,
        convergence_threshold=0.01,
    )
