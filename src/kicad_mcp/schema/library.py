"""Typed data models for KiCad library entries (symbols and footprints)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LibraryEntry:
    """An entry in a sym-lib-table or fp-lib-table."""

    name: str
    lib_type: str  # "KiCad", "Legacy", etc.
    uri: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.lib_type,
            "uri": self.uri,
            "description": self.description,
        }


@dataclass(frozen=True)
class SymbolInfo:
    """Summary of a symbol in a .kicad_sym library."""

    name: str
    library: str  # Library name (e.g., "Device")
    reference: str  # Default reference prefix (e.g., "R", "C")
    value: str
    description: str = ""
    keywords: str = ""
    footprint: str = ""
    datasheet: str = ""
    pin_count: int = 0
    is_power: bool = False

    @property
    def full_id(self) -> str:
        return f"{self.library}:{self.name}"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "library": self.library,
            "full_id": self.full_id,
            "reference": self.reference,
            "value": self.value,
            "description": self.description,
            "keywords": self.keywords,
            "pin_count": self.pin_count,
            "is_power": self.is_power,
        }
        if self.footprint:
            d["footprint"] = self.footprint
        if self.datasheet and self.datasheet != "~":
            d["datasheet"] = self.datasheet
        return d


@dataclass(frozen=True)
class FootprintInfo:
    """Summary of a footprint in a .pretty library."""

    name: str
    library: str  # Library name (e.g., "Resistor_SMD")
    description: str = ""
    tags: str = ""
    attribute: str = ""  # "smd", "through_hole", ""
    pad_count: int = 0
    pads: list[dict[str, Any]] = field(default_factory=list)

    @property
    def full_id(self) -> str:
        return f"{self.library}:{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "library": self.library,
            "full_id": self.full_id,
            "description": self.description,
            "tags": self.tags,
            "attribute": self.attribute,
            "pad_count": self.pad_count,
        }
