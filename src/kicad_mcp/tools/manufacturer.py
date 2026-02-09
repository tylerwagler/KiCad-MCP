"""Manufacturer tools — DRC presets and manufacturability checking."""

from __future__ import annotations

from typing import Any

from .registry import register_tool


def _list_manufacturer_presets_handler() -> dict[str, Any]:
    """List all available manufacturer DRC presets."""
    from ..manufacturers import PRESETS

    return {
        "count": len(PRESETS),
        "presets": [
            {
                "name": p.name,
                "manufacturer": p.manufacturer,
                "service_level": p.service_level,
                "description": p.description,
            }
            for p in PRESETS.values()
        ],
    }


def _get_preset_rules_handler(preset_name: str) -> dict[str, Any]:
    """Get the detailed DRC rules for a specific manufacturer preset.

    Args:
        preset_name: Name of the preset (e.g., 'jlcpcb_standard').
    """
    from ..manufacturers import PRESETS

    if preset_name not in PRESETS:
        available = ", ".join(sorted(PRESETS.keys()))
        return {"error": f"Unknown preset: {preset_name!r}. Available: {available}"}

    return PRESETS[preset_name].to_dict()


def _check_manufacturability_handler(preset_name: str) -> dict[str, Any]:
    """Check the current board against a manufacturer's DRC rules.

    Args:
        preset_name: Name of the preset to check against (e.g., 'jlcpcb_standard').
    """
    from .. import state
    from ..manufacturers import PRESETS

    if preset_name not in PRESETS:
        available = ", ".join(sorted(PRESETS.keys()))
        return {"error": f"Unknown preset: {preset_name!r}. Available: {available}"}

    preset = PRESETS[preset_name]
    summary = state.get_summary()

    violations = preset.check_violations(
        layer_count=len(summary.copper_layers),
        board_thickness=summary.thickness,
    )

    return {
        "preset": preset_name,
        "manufacturer": preset.manufacturer,
        "board": summary.title,
        "passed": len(violations) == 0,
        "violation_count": len(violations),
        "violations": violations,
        "notes": preset.notes,
    }


# Register manufacturer tools (all routed)
register_tool(
    name="list_manufacturer_presets",
    description="List all available manufacturer DRC rule presets (JLCPCB, OSHPark, PCBWay, etc.).",
    parameters={},
    handler=_list_manufacturer_presets_handler,
    category="manufacturer",
)

register_tool(
    name="get_preset_rules",
    description="Get detailed DRC rules for a specific manufacturer preset.",
    parameters={
        "preset_name": {"type": "string", "description": "Preset name (e.g., 'jlcpcb_standard')."},
    },
    handler=_get_preset_rules_handler,
    category="manufacturer",
)

register_tool(
    name="check_manufacturability",
    description="Check the current board against a manufacturer's DRC rules for manufacturability.",
    parameters={
        "preset_name": {"type": "string", "description": "Preset name (e.g., 'jlcpcb_standard')."},
    },
    handler=_check_manufacturability_handler,
    category="manufacturer",
)
