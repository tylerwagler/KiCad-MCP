"""Auto-routing tools — A* pathfinding for single nets and batch routing."""

from __future__ import annotations

import math
from typing import Any

from ..algorithms.types import RouteResult
from ..schema.board import Footprint
from ..session.manager import Session, SessionManager
from .registry import register_tool


def _get_mgr() -> SessionManager:
    from .mutation import _get_manager

    return _get_manager()


# ── Handlers ────────────────────────────────────────────────────────


def _auto_route_net_handler(
    session_id: str,
    net_name: str | None = None,
    net_number: int | None = None,
    start_reference: str | None = None,
    start_pad: str | None = None,
    end_reference: str | None = None,
    end_pad: str | None = None,
    trace_width: float = 0.25,
    clearance: float = 0.2,
    via_size: float = 0.8,
    via_drill: float = 0.4,
    grid_resolution: float = 0.25,
    routing_mode: str = "45deg",
    preferred_layer: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Auto-route a single net or pad pair using A* pathfinding.

    Args:
        session_id: Active session ID.
        net_name: Net name to route (routes all pads in the net).
        net_number: Net number to route (alternative to net_name).
        start_reference: Start component reference (for pad pair routing).
        start_pad: Start pad number (for pad pair routing).
        end_reference: End component reference (for pad pair routing).
        end_pad: End pad number (for pad pair routing).
        trace_width: Trace width in mm. Default: 0.25.
        clearance: Clearance around obstacles in mm. Default: 0.2.
        via_size: Via pad size in mm. Default: 0.8.
        via_drill: Via drill diameter in mm. Default: 0.4.
        grid_resolution: Grid resolution in mm. Default: 0.25.
        routing_mode: "45deg" or "manhattan". Default: "45deg".
        preferred_layer: Preferred copper layer. Default: first available.
        apply: If True, apply changes to session. Default: False (preview).
    """
    from ..algorithms.astar import _minimum_spanning_tree, astar_route
    from ..algorithms.grid import build_obstacle_map
    from ..schema.extract import (
        extract_board_outline,
        extract_footprints,
        extract_nets,
        extract_segments,
    )

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    assert session._working_doc is not None
    doc = session._working_doc

    footprints = extract_footprints(doc)
    segments = extract_segments(doc)
    board_bbox = extract_board_outline(doc)

    if board_bbox is None:
        return {"error": "No board outline (Edge.Cuts) found"}

    nets = extract_nets(doc)
    diagonal = routing_mode != "manhattan"
    default_layer = preferred_layer or "F.Cu"
    layers = ["F.Cu", "B.Cu"]

    # Resolve net
    target_net_number = net_number
    target_net_name = net_name or ""
    if net_name and target_net_number is None:
        for n in nets:
            if n.name == net_name:
                target_net_number = n.number
                break
        if target_net_number is None:
            return {"error": f"Net {net_name!r} not found"}
    if target_net_number is not None and not target_net_name:
        for n in nets:
            if n.number == target_net_number:
                target_net_name = n.name
                break

    # Build obstacle map
    grid = build_obstacle_map(
        footprints,
        segments,
        board_bbox,
        layers=layers,
        resolution=grid_resolution,
        clearance=clearance,
        target_net=target_net_number,
    )

    # Find pads to route
    if start_reference and end_reference:
        # Pad pair mode
        start_pos = _find_pad_position(footprints, start_reference, start_pad)
        end_pos = _find_pad_position(footprints, end_reference, end_pad)

        if start_pos is None:
            return {"error": f"Start pad not found: {start_reference}:{start_pad}"}
        if end_pos is None:
            return {"error": f"End pad not found: {end_reference}:{end_pad}"}

        result = astar_route(
            grid,
            start_pos[0],
            start_pos[1],
            default_layer,
            end_pos[0],
            end_pos[1],
            default_layer,
            net_name=target_net_name,
            net_number=target_net_number or 0,
            via_cost=5.0,
            diagonal=diagonal,
        )
    elif target_net_number is not None:
        # Full net mode: find all pads for this net, compute MST, route edges
        pads = _collect_net_pads(footprints, target_net_number)
        if len(pads) < 2:
            return {"error": f"Net {target_net_name} has fewer than 2 pads"}

        mst_edges = _minimum_spanning_tree(pads)
        all_waypoints = []
        all_vias = []
        total_segs = 0
        total_vias = 0
        total_cost = 0.0

        for i, j in mst_edges:
            r = astar_route(
                grid,
                pads[i]["x"],
                pads[i]["y"],
                default_layer,
                pads[j]["x"],
                pads[j]["y"],
                default_layer,
                net_name=target_net_name,
                net_number=target_net_number,
                via_cost=5.0,
                diagonal=diagonal,
            )
            if not r.success:
                return {
                    "status": "partial_failure",
                    "result": r.to_dict(),
                }
            all_waypoints.extend(r.waypoints)
            all_vias.extend(r.via_locations)
            total_segs += r.segment_count
            total_vias += r.via_count
            total_cost += r.total_cost

            # Update grid with routed path
            for wp_idx in range(1, len(r.waypoints)):
                prev_wp = r.waypoints[wp_idx - 1]
                curr_wp = r.waypoints[wp_idx]
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
                        grid.resolution,
                        li,
                        target_net_number,
                    )

        from ..algorithms.types import RouteResult

        result = RouteResult(
            success=True,
            net_name=target_net_name,
            net_number=target_net_number,
            waypoints=all_waypoints,
            via_locations=all_vias,
            segment_count=total_segs,
            via_count=total_vias,
            total_cost=total_cost,
        )
    else:
        return {"error": "Specify net_name, net_number, or start/end pad pair"}

    if not result.success:
        return {"status": "no_route_found", "result": result.to_dict()}

    # Apply if requested
    if apply and result.success:
        changes = _apply_route_result(mgr, session, result, trace_width, via_size, via_drill)
        return {
            "status": "applied",
            "result": result.to_dict(),
            "changes_applied": len(changes),
        }

    return {"status": "preview", "result": result.to_dict()}


def _find_pad_position(
    footprints: list[Footprint], reference: str, pad_number: str | None
) -> tuple[float, float] | None:
    """Find absolute position of a pad on a footprint."""
    import math as _math

    for fp in footprints:
        if fp.reference != reference:
            continue
        if not fp.pads:
            return (fp.position.x, fp.position.y)
        if pad_number:
            for pad in fp.pads:
                if pad.number == pad_number:
                    angle_rad = _math.radians(fp.position.angle)
                    if abs(fp.position.angle) > 0.01:
                        cos_a = _math.cos(angle_rad)
                        sin_a = _math.sin(angle_rad)
                        px = fp.position.x + pad.position.x * cos_a - pad.position.y * sin_a
                        py = fp.position.y + pad.position.x * sin_a + pad.position.y * cos_a
                    else:
                        px = fp.position.x + pad.position.x
                        py = fp.position.y + pad.position.y
                    return (px, py)
        else:
            # Use first pad
            pad = fp.pads[0]
            return (fp.position.x + pad.position.x, fp.position.y + pad.position.y)
    return None


def _collect_net_pads(footprints: list[Footprint], net_number: int) -> list[dict[str, Any]]:
    """Collect all pads belonging to a net."""
    import math as _math

    pads = []
    for fp in footprints:
        angle_rad = _math.radians(fp.position.angle)
        for pad in fp.pads:
            if pad.net_number == net_number:
                if abs(fp.position.angle) > 0.01:
                    cos_a = _math.cos(angle_rad)
                    sin_a = _math.sin(angle_rad)
                    px = fp.position.x + pad.position.x * cos_a - pad.position.y * sin_a
                    py = fp.position.y + pad.position.x * sin_a + pad.position.y * cos_a
                else:
                    px = fp.position.x + pad.position.x
                    py = fp.position.y + pad.position.y
                pads.append(
                    {
                        "reference": fp.reference,
                        "pad": pad.number,
                        "x": px,
                        "y": py,
                    }
                )
    return pads


def _apply_route_result(
    mgr: SessionManager,
    session: Session,
    result: RouteResult,
    trace_width: float,
    via_size: float,
    via_drill: float,
) -> list[Any]:
    """Apply a RouteResult to the session."""
    changes: list[Any] = []
    waypoints = result.waypoints
    net_number = result.net_number

    for i in range(1, len(waypoints)):
        prev = waypoints[i - 1]
        curr = waypoints[i]

        if prev.layer != curr.layer:
            # Via insertion
            record = mgr.apply_add_via(
                session,
                prev.x,
                prev.y,
                net_number,
                size=via_size,
                drill=via_drill,
                layers=(prev.layer, curr.layer),
            )
            changes.append(record)
        else:
            # Trace segment
            record = mgr.apply_route_trace(
                session,
                prev.x,
                prev.y,
                curr.x,
                curr.y,
                trace_width,
                curr.layer,
                net_number,
            )
            changes.append(record)

    return changes


def _auto_route_all_handler(
    session_id: str,
    trace_width: float = 0.25,
    clearance: float = 0.2,
    via_size: float = 0.8,
    via_drill: float = 0.4,
    grid_resolution: float = 0.25,
    routing_mode: str = "45deg",
    max_nets: int | None = None,
    preferred_layer: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Batch-route all unrouted nets using A* pathfinding.

    Args:
        session_id: Active session ID.
        trace_width: Trace width in mm. Default: 0.25.
        clearance: Clearance around obstacles in mm. Default: 0.2.
        via_size: Via pad size in mm. Default: 0.8.
        via_drill: Via drill diameter in mm. Default: 0.4.
        grid_resolution: Grid resolution in mm. Default: 0.25.
        routing_mode: "45deg" or "manhattan". Default: "45deg".
        max_nets: Maximum number of nets to route. Default: all.
        preferred_layer: Preferred copper layer.
        apply: If True, apply changes to session. Default: False (preview).
    """
    from ..algorithms.astar import route_all_nets
    from ..algorithms.grid import build_obstacle_map
    from ..schema.extract import (
        extract_board_outline,
        extract_footprints,
        extract_segments,
    )

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    assert session._working_doc is not None
    doc = session._working_doc

    footprints = extract_footprints(doc)
    segments = extract_segments(doc)
    board_bbox = extract_board_outline(doc)

    if board_bbox is None:
        return {"error": "No board outline (Edge.Cuts) found"}

    unrouted = mgr.get_ratsnest(session)
    if not unrouted:
        return {"status": "complete", "message": "All nets already routed"}

    layers = ["F.Cu", "B.Cu"]
    diagonal = routing_mode != "manhattan"

    grid = build_obstacle_map(
        footprints,
        segments,
        board_bbox,
        layers=layers,
        resolution=grid_resolution,
        clearance=clearance,
    )

    batch_result = route_all_nets(
        grid,
        unrouted,
        via_cost=5.0,
        diagonal=diagonal,
        max_nets=max_nets,
        preferred_layer=preferred_layer,
    )

    if apply:
        total_changes = 0
        for route in batch_result.results:
            if route.success:
                changes = _apply_route_result(mgr, session, route, trace_width, via_size, via_drill)
                total_changes += len(changes)

        return {
            "status": "applied",
            "result": batch_result.to_dict(),
            "changes_applied": total_changes,
        }

    return {"status": "preview", "result": batch_result.to_dict()}


def _preview_route_handler(
    session_id: str,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    layer: str = "F.Cu",
    grid_resolution: float = 0.25,
    clearance: float = 0.2,
) -> dict[str, Any]:
    """Quick feasibility estimate for a route (no full A*).

    Args:
        session_id: Active session ID.
        start_x: Start X coordinate (mm).
        start_y: Start Y coordinate (mm).
        end_x: End X coordinate (mm).
        end_y: End Y coordinate (mm).
        layer: Copper layer to check. Default: "F.Cu".
        grid_resolution: Grid resolution in mm. Default: 0.25.
        clearance: Clearance in mm. Default: 0.2.
    """
    from ..algorithms.grid import build_obstacle_map
    from ..algorithms.types import RoutePreview
    from ..schema.extract import (
        extract_board_outline,
        extract_footprints,
        extract_segments,
    )

    mgr = _get_mgr()
    try:
        session = mgr.get_session(session_id)
    except KeyError:
        return {"error": f"Session {session_id!r} not found"}

    assert session._working_doc is not None
    doc = session._working_doc

    footprints = extract_footprints(doc)
    segments = extract_segments(doc)
    board_bbox = extract_board_outline(doc)

    if board_bbox is None:
        return {"error": "No board outline (Edge.Cuts) found"}

    layers = ["F.Cu", "B.Cu"]
    grid = build_obstacle_map(
        footprints,
        segments,
        board_bbox,
        layers=layers,
        resolution=grid_resolution,
        clearance=clearance,
    )

    manhattan = abs(end_x - start_x) + abs(end_y - start_y)
    straight = math.hypot(end_x - start_x, end_y - start_y)

    # Sample obstacle density in corridor between start and end
    try:
        li = grid.layer_index(layer)
    except ValueError:
        li = 0

    c1, r1 = grid.mm_to_col(start_x), grid.mm_to_row(start_y)
    c2, r2 = grid.mm_to_col(end_x), grid.mm_to_row(end_y)

    min_c = max(0, min(c1, c2))
    max_c = min(grid.cols - 1, max(c1, c2))
    min_r = max(0, min(r1, r2))
    max_r = min(grid.rows - 1, max(r1, r2))

    total = 0
    blocked_count = 0
    for c in range(min_c, max_c + 1):
        for r in range(min_r, max_r + 1):
            total += 1
            if grid.is_blocked(c, r, li):
                blocked_count += 1

    density = blocked_count / max(total, 1)
    feasible = density < 0.8  # rough threshold

    preview = RoutePreview(
        manhattan_distance=manhattan,
        straight_line_distance=straight,
        obstacle_density=density,
        estimated_feasible=feasible,
    )
    return {"status": "preview", "result": preview.to_dict()}


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="auto_route_net",
    description="Auto-route a single net or pad pair using A* pathfinding.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "net_name": {"type": "string", "description": "Net name to route."},
        "net_number": {"type": "integer", "description": "Net number to route."},
        "start_reference": {"type": "string", "description": "Start component reference."},
        "start_pad": {"type": "string", "description": "Start pad number."},
        "end_reference": {"type": "string", "description": "End component reference."},
        "end_pad": {"type": "string", "description": "End pad number."},
        "trace_width": {"type": "number", "description": "Trace width (mm). Default: 0.25."},
        "clearance": {"type": "number", "description": "Clearance (mm). Default: 0.2."},
        "via_size": {"type": "number", "description": "Via size (mm). Default: 0.8."},
        "via_drill": {"type": "number", "description": "Via drill (mm). Default: 0.4."},
        "grid_resolution": {
            "type": "number",
            "description": "Grid resolution (mm). Default: 0.25.",
        },
        "routing_mode": {
            "type": "string",
            "description": "'45deg' or 'manhattan'. Default: '45deg'.",
        },
        "preferred_layer": {"type": "string", "description": "Preferred copper layer."},
        "apply": {"type": "boolean", "description": "Apply to session. Default: false."},
    },
    handler=_auto_route_net_handler,
    category="autoroute",
)

register_tool(
    name="auto_route_all",
    description="Batch-route all unrouted nets using A* pathfinding.",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "trace_width": {"type": "number", "description": "Trace width (mm). Default: 0.25."},
        "clearance": {"type": "number", "description": "Clearance (mm). Default: 0.2."},
        "via_size": {"type": "number", "description": "Via size (mm). Default: 0.8."},
        "via_drill": {"type": "number", "description": "Via drill (mm). Default: 0.4."},
        "grid_resolution": {
            "type": "number",
            "description": "Grid resolution (mm). Default: 0.25.",
        },
        "routing_mode": {
            "type": "string",
            "description": "'45deg' or 'manhattan'. Default: '45deg'.",
        },
        "max_nets": {"type": "integer", "description": "Max nets to route."},
        "preferred_layer": {"type": "string", "description": "Preferred copper layer."},
        "apply": {"type": "boolean", "description": "Apply to session. Default: false."},
    },
    handler=_auto_route_all_handler,
    category="autoroute",
)

register_tool(
    name="preview_route",
    description="Quick feasibility estimate for a route (obstacle density, distance).",
    parameters={
        "session_id": {"type": "string", "description": "Active session ID."},
        "start_x": {"type": "number", "description": "Start X (mm)."},
        "start_y": {"type": "number", "description": "Start Y (mm)."},
        "end_x": {"type": "number", "description": "End X (mm)."},
        "end_y": {"type": "number", "description": "End Y (mm)."},
        "layer": {"type": "string", "description": "Copper layer. Default: 'F.Cu'."},
        "grid_resolution": {
            "type": "number",
            "description": "Grid resolution (mm). Default: 0.25.",
        },
        "clearance": {"type": "number", "description": "Clearance (mm). Default: 0.2."},
    },
    handler=_preview_route_handler,
    category="autoroute",
)
