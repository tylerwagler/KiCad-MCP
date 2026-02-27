"""IPC API operations: push/reverse changes to KiCad GUI."""

from __future__ import annotations

import contextlib
from typing import Any

from .types import ChangeRecord


def try_ipc_push(applied: list[ChangeRecord]) -> int:
    """Attempt to push applied changes to KiCad via IPC.

    Returns the number of changes successfully pushed, or 0 if IPC
    is not available.
    """
    try:
        from ..backends.ipc_api import IpcBackend
    except Exception:
        return 0

    ipc = IpcBackend.get()
    if not ipc.is_connected():
        return 0

    pushed = 0
    has_routing_changes = False
    for change in applied:
        try:
            _push_change_to_ipc(ipc, change)
            pushed += 1
            if change.operation in ("route_trace", "add_via", "create_zone"):
                has_routing_changes = True
        except Exception:
            pass  # IPC push is best-effort

    if pushed > 0:
        with contextlib.suppress(Exception):
            ipc.commit_to_undo()

        if has_routing_changes:
            with contextlib.suppress(Exception):
                ipc.refill_zones()

    return pushed


def _push_change_to_ipc(ipc: Any, change: ChangeRecord) -> None:
    """Push a single change to KiCad via IPC."""
    op = change.operation
    if op == "move_component":
        x, y = parse_at_coords(change.after_snapshot)
        if x is not None and y is not None:
            ipc.move_footprint(change.target, x, y)
    elif op == "rotate_component":
        parts = change.after_snapshot.strip("()").split()
        if len(parts) >= 4:
            angle = float(parts[3])
            ipc.rotate_footprint(change.target, angle)
    elif op == "delete_component":
        ipc.delete_footprint(change.target)
    elif op == "route_trace":
        params = parse_segment_snapshot(change.after_snapshot)
        if params:
            ipc.create_track_segment(
                params["start_x"],
                params["start_y"],
                params["end_x"],
                params["end_y"],
                params["width"],
                params["layer"],
                params["net"],
            )
    elif op == "add_via":
        params = parse_via_snapshot(change.after_snapshot)
        if params:
            ipc.create_via(
                params["x"],
                params["y"],
                params["size"],
                params["drill"],
                (params["layer_start"], params["layer_end"]),
                params["net"],
            )
    elif op == "create_zone":
        params = parse_zone_snapshot(change.after_snapshot)
        if params:
            ipc.create_zone(
                params["net"],
                params["layer"],
                params["outline_points"],
                params.get("priority", 0),
                params.get("min_thickness", 0.25),
            )


def parse_at_coords(snapshot: str) -> tuple[float | None, float | None]:
    """Extract x, y from an ``(at X Y ...)`` S-expression string."""
    stripped = snapshot.strip()
    if stripped.startswith("(at "):
        parts = stripped[1:-1].split()
        if len(parts) >= 3:
            try:
                return float(parts[1]), float(parts[2])
            except ValueError:
                pass
    return None, None


def _get_first_value(node: Any, default: str = "") -> str:
    """Get first_value from SExp node, returning default if None."""
    val = getattr(node, "first_value", None) if node else None
    return val if val is not None else default


def parse_segment_snapshot(snapshot: str) -> dict[str, Any] | None:
    """Parse segment S-expression."""
    try:
        from ..sexp.parser import parse as sexp_parse

        node = sexp_parse(snapshot)
        if node.name != "segment":
            return None

        start = node.find("start")
        end = node.find("end")
        width = node.find("width")
        layer = node.find("layer")
        net = node.find("net")

        if start is None or end is None or width is None or layer is None or net is None:
            return None

        # Extract values with proper None handling
        start_vals = getattr(start, "atom_values", None)
        end_vals = getattr(end, "atom_values", None)
        width_val = getattr(width, "first_value", None)
        layer_val = getattr(layer, "first_value", None)
        net_val = getattr(net, "first_value", None)

        if (
            start_vals is None
            or end_vals is None
            or width_val is None
            or layer_val is None
            or net_val is None
        ):
            return None

        return {
            "start_x": float(start_vals[0]) if len(start_vals) > 0 else 0.0,
            "start_y": float(start_vals[1]) if len(start_vals) > 1 else 0.0,
            "end_x": float(end_vals[0]) if len(end_vals) > 0 else 0.0,
            "end_y": float(end_vals[1]) if len(end_vals) > 1 else 0.0,
            "width": float(width_val),
            "layer": str(layer_val).strip('"'),
            "net": int(net_val),
        }
    except Exception:
        return None


def parse_via_snapshot(snapshot: str) -> dict[str, Any] | None:
    """Parse via S-expression."""
    try:
        from ..sexp.parser import parse as sexp_parse

        node = sexp_parse(snapshot)
        if node.name != "via":
            return None

        at = node.find("at")
        size = node.find("size")
        drill = node.find("drill")
        layers = node.find("layers")
        net = node.find("net")

        if not at or not size or not drill or not layers or not net:
            return None

        # Type: ignore for union-attr - all checked above
        layer_vals = layers.atom_values
        size_val = size.first_value
        drill_val = drill.first_value
        return {
            "x": float(at.atom_values[0]),
            "y": float(at.atom_values[1]),
            "size": float(size_val or 0.0),
            "drill": float(drill_val or 0.0),
            "layer_start": layer_vals[0].strip('"'),
            "layer_end": layer_vals[1].strip('"'),
            "net": int(net.first_value or 0),
        }
    except Exception:
        return None


def parse_zone_snapshot(snapshot: str) -> dict[str, Any] | None:
    """Parse zone S-expression."""
    try:
        from ..sexp.parser import parse as sexp_parse

        node = sexp_parse(snapshot)
        if node.name != "zone":
            return None

        net = node.find("net")
        layers = node.find("layers")
        polygon = node.find("polygon")
        priority_node = node.find("priority")

        if net is None or layers is None or polygon is None:
            return None

        pts_node = polygon.find("pts")
        if pts_node is None:
            return None

        outline_points = []
        for xy_node in pts_node.children:
            if xy_node.name == "xy":
                vals = xy_node.atom_values
                if len(vals) >= 2:
                    outline_points.append((float(vals[0]), float(vals[1])))

        layer_val = layers.first_value
        layer = (layer_val or "").strip('"')
        priority_val = priority_node.first_value if priority_node else None
        priority = int(priority_val) if priority_val else 0

        return {
            "net": int(net.first_value or 0),
            "layer": layer,
            "outline_points": outline_points,
            "priority": priority,
            "min_thickness": 0.25,
        }
    except Exception:
        return None


def reverse_ipc_changes(applied: list[ChangeRecord]) -> int:
    """Reverse applied changes in KiCad GUI via IPC."""
    try:
        from ..backends.ipc_api import IpcBackend
    except Exception:
        return 0

    ipc = IpcBackend.get()
    if not ipc.is_connected():
        return 0

    reversed_count = 0
    for change in reversed(applied):
        try:
            op = change.operation
            if op == "move_component":
                x, y = parse_at_coords(change.before_snapshot)
                if x is not None and y is not None:
                    ipc.move_footprint(change.target, x, y)
                    reversed_count += 1
            elif op == "rotate_component":
                stripped = change.before_snapshot.strip()
                if stripped.startswith("(at "):
                    parts = stripped[1:-1].split()
                    if len(parts) >= 3:
                        try:
                            orig_angle = float(parts[3]) if len(parts) >= 4 else 0.0
                            ipc.rotate_footprint(change.target, orig_angle)
                            reversed_count += 1
                        except ValueError:
                            pass
        except Exception:
            pass  # IPC reversal is best-effort

    if reversed_count > 0:
        with contextlib.suppress(Exception):
            ipc.commit_to_undo()

    return reversed_count
