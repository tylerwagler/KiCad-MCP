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
    dnp: bool = False  # "Do Not Populate" — kept in BOM but flagged (KiCad default)
    pins: list[SchPin] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    instances: list[SymbolInstance] = field(default_factory=list)

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
            "dnp": self.dnp,
            "pin_count": len(self.pins),
            "properties": self.properties,
            "instances": [i.to_dict() for i in self.instances],
        }


@dataclass
class SchPin:
    """A pin instance on a placed symbol."""

    number: str
    uuid: str

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, "uuid": self.uuid}


@dataclass
class SymbolInstance:
    """A per-hierarchy-path instance of a symbol.

    A symbol defined once in a reused sheet appears once per sheet placement,
    each with its own reference designator and unit, keyed by the hierarchical
    instance path (e.g. ``/<root_uuid>/<sheet_uuid>``).
    """

    path: str
    reference: str
    unit: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "reference": self.reference, "unit": self.unit}


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
class SheetPin:
    """A hierarchical pin on a (sheet) block — the parent-side port.

    ``shape`` is one of input/output/bidirectional/tri_state/passive and must
    match the connecting child-sheet hierarchical label.
    """

    name: str
    shape: str
    position: Position
    uuid: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "shape": self.shape,
            "position": self.position.to_dict(),
            "uuid": self.uuid,
        }


@dataclass
class Sheet:
    """A sub-sheet placed in a parent schematic (points at a child file)."""

    name: str  # "Sheetname" property
    file: str  # "Sheetfile" property — path relative to the parent file
    uuid: str  # the (sheet) block's own uuid (a path segment for children)
    position: Position
    size: tuple[float, float] = (0.0, 0.0)
    page: str = ""  # page number from this sheet's instances block
    pins: list[SheetPin] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file": self.file,
            "uuid": self.uuid,
            "position": self.position.to_dict(),
            "size": {"width": self.size[0], "height": self.size[1]},
            "page": self.page,
            "pins": [p.to_dict() for p in self.pins],
        }


@dataclass
class HierarchicalLabel:
    """A hierarchical label inside a schematic — the child-side port.

    Connects to a same-named sheet pin on the parent's (sheet) block.
    """

    name: str
    shape: str
    position: Position
    uuid: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "shape": self.shape,
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
    sheets: list[Sheet] = field(default_factory=list)
    hierarchical_labels: list[HierarchicalLabel] = field(default_factory=list)

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
            "sheet_count": len(self.sheets),
            "hierarchical_label_count": len(self.hierarchical_labels),
            "symbols": [s.to_dict() for s in self.symbols],
            "wires": [w.to_dict() for w in self.wires],
            "labels": [lb.to_dict() for lb in self.labels],
            "power_ports": [p.to_dict() for p in self.power_ports],
            "sheets": [sh.to_dict() for sh in self.sheets],
            "hierarchical_labels": [h.to_dict() for h in self.hierarchical_labels],
        }
