"""Typed data models for KiCad schematic files (.kicad_sch)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .common import Position


@dataclass
class SchSymbol:
    """A symbol instance placed on the schematic."""

    lib_id: str  # e.g., "Device:R"
    reference: str  # e.g., "R1"
    value: str  # e.g., "10k"
    position: Position
    unit: int
    uuid: str
    in_bom: bool = True
    on_board: bool = True
    pins: list[SchPin] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lib_id": self.lib_id,
            "reference": self.reference,
            "value": self.value,
            "position": self.position.to_dict(),
            "unit": self.unit,
            "uuid": self.uuid,
            "in_bom": self.in_bom,
            "on_board": self.on_board,
            "pin_count": len(self.pins),
            "properties": self.properties,
        }


@dataclass
class SchPin:
    """A pin instance on a placed symbol."""

    number: str
    uuid: str

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, "uuid": self.uuid}


@dataclass
class Wire:
    """A wire connecting two points on the schematic."""

    start: Position
    end: Position
    uuid: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "uuid": self.uuid,
        }


@dataclass
class Label:
    """A net label on the schematic."""

    name: str
    position: Position
    uuid: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position.to_dict(),
            "uuid": self.uuid,
        }


@dataclass
class PowerPort:
    """A power port symbol on the schematic."""

    name: str
    position: Position
    uuid: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position.to_dict(),
            "uuid": self.uuid,
        }


@dataclass
class SchematicSummary:
    """High-level summary of a schematic."""

    version: str
    generator: str
    uuid: str
    paper: str
    symbol_count: int
    wire_count: int
    label_count: int
    power_port_count: int
    lib_symbol_count: int
    symbols: list[SchSymbol] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    power_ports: list[PowerPort] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "generator": self.generator,
            "uuid": self.uuid,
            "paper": self.paper,
            "symbol_count": self.symbol_count,
            "wire_count": self.wire_count,
            "label_count": self.label_count,
            "power_port_count": self.power_port_count,
            "lib_symbol_count": self.lib_symbol_count,
            "symbols": [s.to_dict() for s in self.symbols],
            "wires": [w.to_dict() for w in self.wires],
            "labels": [lb.to_dict() for lb in self.labels],
            "power_ports": [p.to_dict() for p in self.power_ports],
        }
