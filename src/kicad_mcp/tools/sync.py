"""Schematic-PCB sync tools — cross-reference, forward/back annotation."""

from __future__ import annotations

from typing import Any

from .registry import register_tool

# ── Handlers ────────────────────────────────────────────────────────


def _cross_reference_check_handler() -> dict[str, Any]:
    """Compare schematic symbols against board footprints.

    Both a schematic and a board must be loaded first.
    Reports missing components, value mismatches, and footprint mismatches.
    """
    from .. import schematic_state, state
    from ..sync import cross_reference

    if not state.is_loaded():
        return {"error": "No board loaded. Use open_project first."}
    if not schematic_state.is_loaded():
        return {"error": "No schematic loaded. Use open_schematic first."}

    symbols = schematic_state.get_symbols()
    footprints = state.get_footprints()
    return cross_reference(symbols, footprints)


def _forward_annotate_handler(save: bool = False) -> dict[str, Any]:
    """Push schematic values onto the board (sch→pcb).

    Updates board footprint Value properties to match the schematic.
    Missing components are flagged but not auto-placed.

    Args:
        save: If true, save the board file after annotation.
    """
    from .. import schematic_state, state
    from ..sync import forward_annotate

    if not state.is_loaded():
        return {"error": "No board loaded. Use open_project first."}
    if not schematic_state.is_loaded():
        return {"error": "No schematic loaded. Use open_schematic first."}

    symbols = schematic_state.get_symbols()
    board_doc = state.get_document()
    result = forward_annotate(symbols, board_doc)

    if save and not result["errors"]:
        board_doc.save()
        result["saved"] = True

    return result


def _back_annotate_handler(save: bool = False) -> dict[str, Any]:
    """Push board values back to the schematic (pcb→sch).

    Updates schematic symbol Value properties to match the board.

    Args:
        save: If true, save the schematic file after annotation.
    """
    from .. import schematic_state, state
    from ..sync import back_annotate

    if not state.is_loaded():
        return {"error": "No board loaded. Use open_project first."}
    if not schematic_state.is_loaded():
        return {"error": "No schematic loaded. Use open_schematic first."}

    footprints = state.get_footprints()
    sch_doc = schematic_state.get_document()
    result = back_annotate(footprints, sch_doc)

    if save and not result["errors"]:
        sch_doc.save()
        result["saved"] = True

    return result


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="cross_reference_check",
    description="Compare schematic symbols against board footprints. "
    "Reports missing components, value mismatches, and footprint mismatches.",
    parameters={},
    handler=_cross_reference_check_handler,
    category="sync",
)

register_tool(
    name="forward_annotate",
    description="Push schematic values onto the board (sch→pcb). "
    "Updates board footprint values to match the schematic.",
    parameters={
        "save": {
            "type": "boolean",
            "description": "Save the board file after annotation. Default: false.",
        },
    },
    handler=_forward_annotate_handler,
    category="sync",
)

register_tool(
    name="back_annotate",
    description="Push board values back to the schematic (pcb→sch). "
    "Updates schematic symbol values to match the board.",
    parameters={
        "save": {
            "type": "boolean",
            "description": "Save the schematic file after annotation. Default: false.",
        },
    },
    handler=_back_annotate_handler,
    category="sync",
)
