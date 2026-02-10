"""Obstacle map for PCB auto-routing — sparse grid with pad/trace rasterization."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..schema.board import Footprint, Segment
from ..schema.common import BoundingBox


@dataclass
class ObstacleMap:
    """Sparse 3D obstacle grid for A* routing.

    Coordinates: (col, row, layer_idx). Sparse ``blocked`` set is memory-efficient —
    a 100x100 mm board at 0.25 mm resolution = 400x400 = 160 K cells per layer,
    but most are empty.
    """

    origin_x: float  # board min_x (mm)
    origin_y: float  # board min_y (mm)
    width_mm: float
    height_mm: float
    resolution: float  # mm per cell
    cols: int
    rows: int
    layers: list[str]  # ordered copper layers, e.g. ["F.Cu", "B.Cu"]
    blocked: set[tuple[int, int, int]] = field(default_factory=set)
    net_ownership: dict[tuple[int, int, int], int] = field(default_factory=dict)

    # ── Coordinate conversion ──────────────────────────────────────

    def mm_to_col(self, x_mm: float) -> int:
        """Convert board X (mm) to grid column."""
        return round((x_mm - self.origin_x) / self.resolution)

    def mm_to_row(self, y_mm: float) -> int:
        """Convert board Y (mm) to grid row."""
        return round((y_mm - self.origin_y) / self.resolution)

    def col_to_mm(self, col: int) -> float:
        """Convert grid column to board X (mm)."""
        return self.origin_x + col * self.resolution

    def row_to_mm(self, row: int) -> float:
        """Convert grid row to board Y (mm)."""
        return self.origin_y + row * self.resolution

    def layer_index(self, layer_name: str) -> int:
        """Get the index of a copper layer."""
        try:
            return self.layers.index(layer_name)
        except ValueError:
            raise ValueError(f"Layer {layer_name!r} not in {self.layers}") from None

    def in_bounds(self, col: int, row: int) -> bool:
        """Check if a grid cell is within bounds."""
        return 0 <= col < self.cols and 0 <= row < self.rows

    def is_blocked(self, col: int, row: int, layer_idx: int) -> bool:
        """Check if a cell is blocked."""
        return (col, row, layer_idx) in self.blocked

    # ── Rasterization ──────────────────────────────────────────────

    def mark_rect(
        self,
        cx_mm: float,
        cy_mm: float,
        half_w_mm: float,
        half_h_mm: float,
        layer_idx: int,
        net_number: int | None = None,
    ) -> None:
        """Mark a rectangle (center + half-extents) as blocked on a layer."""
        c_min = max(0, self.mm_to_col(cx_mm - half_w_mm))
        c_max = min(self.cols - 1, self.mm_to_col(cx_mm + half_w_mm))
        r_min = max(0, self.mm_to_row(cy_mm - half_h_mm))
        r_max = min(self.rows - 1, self.mm_to_row(cy_mm + half_h_mm))

        for c in range(c_min, c_max + 1):
            for r in range(r_min, r_max + 1):
                cell = (c, r, layer_idx)
                self.blocked.add(cell)
                if net_number is not None:
                    self.net_ownership[cell] = net_number

    def mark_segment_line(
        self,
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        half_width_mm: float,
        layer_idx: int,
        net_number: int | None = None,
    ) -> None:
        """Mark cells along a line segment (with width) as blocked.

        Uses perpendicular-distance sweep: for each cell in the segment's
        bounding box, check if the perpendicular distance to the line is
        within half_width.
        """
        c_min = max(0, self.mm_to_col(min(x1_mm, x2_mm) - half_width_mm))
        c_max = min(self.cols - 1, self.mm_to_col(max(x1_mm, x2_mm) + half_width_mm))
        r_min = max(0, self.mm_to_row(min(y1_mm, y2_mm) - half_width_mm))
        r_max = min(self.rows - 1, self.mm_to_row(max(y1_mm, y2_mm) + half_width_mm))

        dx = x2_mm - x1_mm
        dy = y2_mm - y1_mm
        seg_len_sq = dx * dx + dy * dy

        for c in range(c_min, c_max + 1):
            px = self.col_to_mm(c)
            for r in range(r_min, r_max + 1):
                py = self.row_to_mm(r)
                # Point-to-segment distance
                if seg_len_sq < 1e-12:
                    dist = math.hypot(px - x1_mm, py - y1_mm)
                else:
                    t = max(
                        0.0,
                        min(
                            1.0,
                            ((px - x1_mm) * dx + (py - y1_mm) * dy) / seg_len_sq,
                        ),
                    )
                    proj_x = x1_mm + t * dx
                    proj_y = y1_mm + t * dy
                    dist = math.hypot(px - proj_x, py - proj_y)

                if dist <= half_width_mm:
                    cell = (c, r, layer_idx)
                    self.blocked.add(cell)
                    if net_number is not None:
                        self.net_ownership[cell] = net_number

    def clear_net(self, net_number: int) -> None:
        """Remove all cells owned by a specific net from the blocked set.

        This allows a net to route through its own copper.
        """
        to_remove = [cell for cell, net in self.net_ownership.items() if net == net_number]
        for cell in to_remove:
            self.blocked.discard(cell)
            del self.net_ownership[cell]

    def get_stats(self) -> dict[str, Any]:
        """Return grid statistics."""
        total_cells = self.cols * self.rows * len(self.layers)
        return {
            "cols": self.cols,
            "rows": self.rows,
            "layers": len(self.layers),
            "total_cells": total_cells,
            "blocked_cells": len(self.blocked),
            "blocked_pct": round(len(self.blocked) / max(total_cells, 1) * 100, 2),
            "resolution_mm": self.resolution,
        }


def build_obstacle_map(
    footprints: list[Footprint],
    segments: list[Segment],
    board_bbox: BoundingBox,
    layers: list[str] | None = None,
    resolution: float = 0.25,
    clearance: float = 0.2,
    target_net: int | None = None,
) -> ObstacleMap:
    """Build an obstacle map from board data.

    Args:
        footprints: Extracted footprints with pad positions.
        segments: Existing trace segments.
        board_bbox: Board bounding box from Edge.Cuts.
        layers: Copper layers to include. Defaults to ["F.Cu", "B.Cu"].
        resolution: Grid resolution in mm per cell.
        clearance: Clearance around obstacles in mm.
        target_net: If set, clear this net's cells (it can route through own copper).
    """
    if layers is None:
        layers = ["F.Cu", "B.Cu"]

    # Add margin around board
    margin = clearance
    width_mm = board_bbox.width + 2 * margin
    height_mm = board_bbox.height + 2 * margin
    origin_x = board_bbox.min_x - margin
    origin_y = board_bbox.min_y - margin

    cols = max(1, math.ceil(width_mm / resolution))
    rows = max(1, math.ceil(height_mm / resolution))

    grid = ObstacleMap(
        origin_x=origin_x,
        origin_y=origin_y,
        width_mm=width_mm,
        height_mm=height_mm,
        resolution=resolution,
        cols=cols,
        rows=rows,
        layers=list(layers),
    )

    # Mark cells outside board outline as blocked (boundary enforcement)
    board_c_min = grid.mm_to_col(board_bbox.min_x)
    board_c_max = grid.mm_to_col(board_bbox.max_x)
    board_r_min = grid.mm_to_row(board_bbox.min_y)
    board_r_max = grid.mm_to_row(board_bbox.max_y)

    for li in range(len(layers)):
        for c in range(cols):
            for r in range(rows):
                if c < board_c_min or c > board_c_max or r < board_r_min or r > board_r_max:
                    grid.blocked.add((c, r, li))

    # Rasterize pads
    for fp in footprints:
        fp_x = fp.position.x
        fp_y = fp.position.y
        fp_angle_rad = math.radians(fp.position.angle)

        for pad in fp.pads:
            # Compute absolute pad position (rotate pad offset by footprint angle)
            if abs(fp.position.angle) > 0.01:
                cos_a = math.cos(fp_angle_rad)
                sin_a = math.sin(fp_angle_rad)
                pad_x = fp_x + pad.position.x * cos_a - pad.position.y * sin_a
                pad_y = fp_y + pad.position.x * sin_a + pad.position.y * cos_a
            else:
                pad_x = fp_x + pad.position.x
                pad_y = fp_y + pad.position.y

            half_w = pad.size[0] / 2 + clearance
            half_h = pad.size[1] / 2 + clearance

            # Mark on each pad layer that's in our layer list
            for pad_layer in pad.layers:
                # Handle wildcard layers like "*.Cu"
                if pad_layer == "*.Cu":
                    matching = list(range(len(layers)))
                elif pad_layer in layers:
                    matching = [layers.index(pad_layer)]
                else:
                    matching = []

                for li in matching:
                    grid.mark_rect(pad_x, pad_y, half_w, half_h, li, pad.net_number)

    # Rasterize existing trace segments
    for seg in segments:
        if seg.layer in layers:
            li = layers.index(seg.layer)
            half_w = seg.width / 2 + clearance
            grid.mark_segment_line(
                seg.start.x,
                seg.start.y,
                seg.end.x,
                seg.end.y,
                half_w,
                li,
                seg.net_number,
            )

    # Clear target net's cells so it can route through its own copper
    if target_net is not None:
        grid.clear_net(target_net)

    return grid
