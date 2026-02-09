"""Common typed data models shared across KiCad file types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Position:
    """2D position in board coordinates (mm)."""

    x: float
    y: float
    angle: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"x": self.x, "y": self.y}
        if self.angle != 0.0:
            d["angle"] = self.angle
        return d


@dataclass(frozen=True)
class Size:
    """Width/height dimensions (mm)."""

    width: float
    height: float

    def to_dict(self) -> dict[str, Any]:
        return {"width": self.width, "height": self.height}


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box (mm)."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def center(self) -> Position:
        return Position(
            x=(self.min_x + self.max_x) / 2,
            y=(self.min_y + self.max_y) / 2,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_x": self.min_x,
            "min_y": self.min_y,
            "max_x": self.max_x,
            "max_y": self.max_y,
            "width": self.width,
            "height": self.height,
        }
