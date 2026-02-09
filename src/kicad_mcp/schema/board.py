"""Typed data models for KiCad PCB board files (.kicad_pcb)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .common import BoundingBox, Position


@dataclass
class Net:
    """A net (electrical connection) on the board."""

    number: int
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, "name": self.name}


@dataclass
class Layer:
    """A layer in the board stackup."""

    number: int
    name: str
    layer_type: str  # "signal", "user"
    user_name: str | None = None  # e.g. "F.Silkscreen" for "F.SilkS"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "number": self.number,
            "name": self.name,
            "type": self.layer_type,
        }
        if self.user_name:
            d["user_name"] = self.user_name
        return d


@dataclass
class Pad:
    """A pad on a footprint."""

    number: str
    pad_type: str  # "smd", "thru_hole", "np_thru_hole", "connect"
    shape: str  # "roundrect", "circle", "rect", "oval", "custom"
    position: Position
    size: tuple[float, float]
    layers: list[str] = field(default_factory=list)
    net_number: int | None = None
    net_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "number": self.number,
            "type": self.pad_type,
            "shape": self.shape,
            "position": self.position.to_dict(),
            "size": {"width": self.size[0], "height": self.size[1]},
            "layers": self.layers,
        }
        if self.net_number is not None:
            d["net"] = {"number": self.net_number, "name": self.net_name or ""}
        return d


@dataclass
class Footprint:
    """A component footprint placed on the board."""

    library: str  # e.g. "Capacitor_SMD:C_0805_2012Metric"
    reference: str  # e.g. "C7"
    value: str  # e.g. "10uF"
    position: Position
    layer: str  # e.g. "F.Cu"
    pads: list[Pad] = field(default_factory=list)
    uuid: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "reference": self.reference,
            "value": self.value,
            "position": self.position.to_dict(),
            "layer": self.layer,
            "pads": [p.to_dict() for p in self.pads],
            "uuid": self.uuid,
        }


@dataclass
class Segment:
    """A track segment (copper trace)."""

    start: Position
    end: Position
    width: float
    layer: str
    net_number: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "width": self.width,
            "layer": self.layer,
            "net": self.net_number,
        }


@dataclass
class BoardSummary:
    """High-level summary of a PCB board."""

    title: str
    version: str
    generator: str
    thickness: float
    layer_count: int
    copper_layers: list[str]
    net_count: int
    footprint_count: int
    segment_count: int
    nets: list[Net]
    layers: list[Layer]
    bounding_box: BoundingBox | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "title": self.title,
            "version": self.version,
            "generator": self.generator,
            "thickness": self.thickness,
            "layer_count": self.layer_count,
            "copper_layers": self.copper_layers,
            "net_count": self.net_count,
            "footprint_count": self.footprint_count,
            "segment_count": self.segment_count,
            "nets": [n.to_dict() for n in self.nets],
            "layers": [lyr.to_dict() for lyr in self.layers],
        }
        if self.bounding_box:
            d["bounding_box"] = self.bounding_box.to_dict()
        return d
