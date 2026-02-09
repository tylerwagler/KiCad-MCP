"""Manufacturer DRC presets — design rules for common PCB fabrication houses.

Each preset defines the minimum manufacturing capabilities:
- Trace widths, clearances, via sizes
- Layer counts, board thickness
- Special capabilities (e.g., blind vias, impedance control)

Sources:
- JLCPCB: https://jlcpcb.com/capabilities/pcb-capabilities
- OSHPark: https://docs.oshpark.com/services/
- PCBWay: https://www.pcbway.com/capabilities.html
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ManufacturerPreset:
    """DRC rule preset for a specific manufacturer and service level."""

    name: str
    manufacturer: str
    service_level: str  # e.g., "standard", "advanced"
    description: str

    # Trace rules (mm)
    min_trace_width: float
    min_clearance: float

    # Via rules (mm)
    min_via_diameter: float
    min_via_drill: float

    # Hole rules (mm)
    min_hole_diameter: float

    # Board rules
    min_layers: int = 1
    max_layers: int = 2
    min_board_thickness: float = 0.6
    max_board_thickness: float = 2.4

    # Annular ring (mm)
    min_annular_ring: float = 0.13

    # Silkscreen (mm)
    min_silkscreen_width: float = 0.15
    min_silkscreen_height: float = 1.0

    # Solder mask
    min_solder_mask_bridge: float = 0.1

    # Special capabilities
    supports_blind_vias: bool = False
    supports_buried_vias: bool = False
    supports_impedance_control: bool = False
    supports_castellated_holes: bool = False

    # Pricing context
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "service_level": self.service_level,
            "description": self.description,
            "rules": {
                "min_trace_width_mm": self.min_trace_width,
                "min_clearance_mm": self.min_clearance,
                "min_via_diameter_mm": self.min_via_diameter,
                "min_via_drill_mm": self.min_via_drill,
                "min_hole_diameter_mm": self.min_hole_diameter,
                "min_annular_ring_mm": self.min_annular_ring,
                "min_silkscreen_width_mm": self.min_silkscreen_width,
                "min_solder_mask_bridge_mm": self.min_solder_mask_bridge,
            },
            "board": {
                "min_layers": self.min_layers,
                "max_layers": self.max_layers,
                "min_thickness_mm": self.min_board_thickness,
                "max_thickness_mm": self.max_board_thickness,
            },
            "capabilities": {
                "blind_vias": self.supports_blind_vias,
                "buried_vias": self.supports_buried_vias,
                "impedance_control": self.supports_impedance_control,
                "castellated_holes": self.supports_castellated_holes,
            },
            "notes": self.notes,
        }

    def check_violations(
        self,
        trace_width: float | None = None,
        clearance: float | None = None,
        via_diameter: float | None = None,
        via_drill: float | None = None,
        hole_diameter: float | None = None,
        layer_count: int | None = None,
        board_thickness: float | None = None,
    ) -> list[dict[str, Any]]:
        """Check values against this preset's rules and return violations."""
        violations: list[dict[str, Any]] = []

        if trace_width is not None and trace_width < self.min_trace_width:
            violations.append(
                {
                    "rule": "min_trace_width",
                    "value": trace_width,
                    "minimum": self.min_trace_width,
                    "message": f"Trace width {trace_width}mm < minimum {self.min_trace_width}mm",
                }
            )

        if clearance is not None and clearance < self.min_clearance:
            violations.append(
                {
                    "rule": "min_clearance",
                    "value": clearance,
                    "minimum": self.min_clearance,
                    "message": f"Clearance {clearance}mm < minimum {self.min_clearance}mm",
                }
            )

        if via_diameter is not None and via_diameter < self.min_via_diameter:
            violations.append(
                {
                    "rule": "min_via_diameter",
                    "value": via_diameter,
                    "minimum": self.min_via_diameter,
                    "message": f"Via diameter {via_diameter}mm < minimum {self.min_via_diameter}mm",
                }
            )

        if via_drill is not None and via_drill < self.min_via_drill:
            violations.append(
                {
                    "rule": "min_via_drill",
                    "value": via_drill,
                    "minimum": self.min_via_drill,
                    "message": f"Via drill {via_drill}mm < minimum {self.min_via_drill}mm",
                }
            )

        if hole_diameter is not None and hole_diameter < self.min_hole_diameter:
            violations.append(
                {
                    "rule": "min_hole_diameter",
                    "value": hole_diameter,
                    "minimum": self.min_hole_diameter,
                    "message": (
                        f"Hole diameter {hole_diameter}mm < minimum {self.min_hole_diameter}mm"
                    ),
                }
            )

        if layer_count is not None and layer_count > self.max_layers:
            violations.append(
                {
                    "rule": "max_layers",
                    "value": layer_count,
                    "maximum": self.max_layers,
                    "message": f"Layer count {layer_count} > maximum {self.max_layers}",
                }
            )

        if board_thickness is not None:
            if board_thickness < self.min_board_thickness:
                violations.append(
                    {
                        "rule": "min_board_thickness",
                        "value": board_thickness,
                        "minimum": self.min_board_thickness,
                        "message": (
                            f"Board thickness {board_thickness}mm"
                            f" < minimum {self.min_board_thickness}mm"
                        ),
                    }
                )
            if board_thickness > self.max_board_thickness:
                violations.append(
                    {
                        "rule": "max_board_thickness",
                        "value": board_thickness,
                        "maximum": self.max_board_thickness,
                        "message": (
                            f"Board thickness {board_thickness}mm"
                            f" > maximum {self.max_board_thickness}mm"
                        ),
                    }
                )

        return violations


# ============================================================================
# Manufacturer Presets
# ============================================================================

JLCPCB_STANDARD = ManufacturerPreset(
    name="jlcpcb_standard",
    manufacturer="JLCPCB",
    service_level="standard",
    description="JLCPCB standard 2-layer PCB service (cheapest, most common)",
    min_trace_width=0.127,  # 5 mil
    min_clearance=0.127,  # 5 mil
    min_via_diameter=0.45,
    min_via_drill=0.2,
    min_hole_diameter=0.2,
    min_layers=1,
    max_layers=2,
    min_board_thickness=0.6,
    max_board_thickness=2.0,
    min_annular_ring=0.13,
    min_silkscreen_width=0.15,
    min_solder_mask_bridge=0.1,
    notes="$2 for 5 boards. 1-2 day lead time. Free shipping with JLCPCB Parts.",
)

JLCPCB_4LAYER = ManufacturerPreset(
    name="jlcpcb_4layer",
    manufacturer="JLCPCB",
    service_level="4-layer",
    description="JLCPCB 4-layer PCB service",
    min_trace_width=0.09,  # 3.5 mil
    min_clearance=0.09,  # 3.5 mil
    min_via_diameter=0.45,
    min_via_drill=0.2,
    min_hole_diameter=0.2,
    min_layers=4,
    max_layers=4,
    min_board_thickness=0.6,
    max_board_thickness=2.4,
    min_annular_ring=0.13,
    min_silkscreen_width=0.15,
    min_solder_mask_bridge=0.1,
    supports_impedance_control=True,
    notes="Starts at ~$7 for 5 boards.",
)

OSHPARK_2LAYER = ManufacturerPreset(
    name="oshpark_2layer",
    manufacturer="OSH Park",
    service_level="standard",
    description="OSH Park 2-layer purple boards (ENIG finish)",
    min_trace_width=0.152,  # 6 mil
    min_clearance=0.152,  # 6 mil
    min_via_diameter=0.4,
    min_via_drill=0.254,  # 10 mil
    min_hole_diameter=0.254,
    min_layers=1,
    max_layers=2,
    min_board_thickness=1.6,
    max_board_thickness=1.6,
    min_annular_ring=0.178,  # 7 mil
    min_silkscreen_width=0.15,
    min_solder_mask_bridge=0.1,
    notes="$5/sq inch. ENIG finish. Purple soldermask. ~12 day lead time.",
)

OSHPARK_4LAYER = ManufacturerPreset(
    name="oshpark_4layer",
    manufacturer="OSH Park",
    service_level="4-layer",
    description="OSH Park 4-layer boards (ENIG finish, controlled impedance)",
    min_trace_width=0.127,  # 5 mil
    min_clearance=0.127,  # 5 mil
    min_via_diameter=0.4,
    min_via_drill=0.254,
    min_hole_diameter=0.254,
    min_layers=4,
    max_layers=4,
    min_board_thickness=1.6,
    max_board_thickness=1.6,
    min_annular_ring=0.178,
    min_silkscreen_width=0.15,
    min_solder_mask_bridge=0.1,
    supports_impedance_control=True,
    notes="$10/sq inch. ENIG finish. Controlled impedance on inner layers.",
)

PCBWAY_STANDARD = ManufacturerPreset(
    name="pcbway_standard",
    manufacturer="PCBWay",
    service_level="standard",
    description="PCBWay standard 2-layer PCB service",
    min_trace_width=0.1,  # ~4 mil
    min_clearance=0.1,
    min_via_diameter=0.4,
    min_via_drill=0.2,
    min_hole_diameter=0.2,
    min_layers=1,
    max_layers=2,
    min_board_thickness=0.4,
    max_board_thickness=2.4,
    min_annular_ring=0.15,
    min_silkscreen_width=0.15,
    min_solder_mask_bridge=0.1,
    supports_castellated_holes=True,
    notes="$5 for 10 boards. Supports many surface finishes.",
)

PCBWAY_ADVANCED = ManufacturerPreset(
    name="pcbway_advanced",
    manufacturer="PCBWay",
    service_level="advanced",
    description="PCBWay advanced multi-layer service (up to 14 layers)",
    min_trace_width=0.075,  # 3 mil
    min_clearance=0.075,
    min_via_diameter=0.35,
    min_via_drill=0.15,
    min_hole_diameter=0.15,
    min_layers=1,
    max_layers=14,
    min_board_thickness=0.4,
    max_board_thickness=3.2,
    min_annular_ring=0.1,
    min_silkscreen_width=0.1,
    min_solder_mask_bridge=0.08,
    supports_blind_vias=True,
    supports_buried_vias=True,
    supports_impedance_control=True,
    supports_castellated_holes=True,
    notes="Higher cost but supports advanced features.",
)

# Registry of all presets by name
PRESETS: dict[str, ManufacturerPreset] = {
    p.name: p
    for p in [
        JLCPCB_STANDARD,
        JLCPCB_4LAYER,
        OSHPARK_2LAYER,
        OSHPARK_4LAYER,
        PCBWAY_STANDARD,
        PCBWAY_ADVANCED,
    ]
}
