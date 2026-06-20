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


def _update_pcb_from_schematic_handler(
    session_id: str,
    schematic_path: str | None = None,
    place_new: bool = True,
    remove_extra: bool = False,
    spacing: float = 12.0,
) -> dict[str, Any]:
    """Update the board from the schematic netlist (KiCad's "Update PCB").

    Generates the netlist from the schematic, then on the given board session:
    instantiates missing footprints from their libraries, reconciles values,
    creates net declarations, and assigns nets to pads. Changes are recorded on
    the session — review/rollback, then commit_session to persist. Requires
    kicad-cli (for the netlist) and a board session from start_session.

    Args:
        session_id: Active board session id (from start_session).
        schematic_path: Root .kicad_sch. Defaults to the loaded hierarchy/schematic.
        place_new: Instantiate footprints not yet on the board. Default true.
        remove_extra: Delete board footprints no longer in the schematic. Default false.
        spacing: Grid spacing (mm) for newly placed footprints. Default 12.
    """
    import os
    import tempfile

    from .. import schematic_state
    from ..backends.kicad_cli import KiCadCli, KiCadCliError, KiCadCliNotFound
    from ..sexp import Document
    from ..sync import parse_netlist_doc
    from .mutation import _get_manager

    mgr = _get_manager()
    try:
        session = mgr.get_session(session_id)
    except (KeyError, ValueError):
        return {"error": f"No active session {session_id!r}. Use start_session first."}

    root = schematic_path
    if root is None:
        if schematic_state.hierarchy_loaded():
            root = schematic_state.get_hierarchy().root.file
        elif schematic_state.is_loaded():
            root = str(schematic_state.get_document().path)
        else:
            return {"error": "No schematic_path given and no schematic/hierarchy loaded."}

    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found; required to generate the netlist."}

    out = os.path.join(tempfile.mkdtemp(prefix="kicad-netlist-"), "netlist.net")
    try:
        result = cli.export_netlist(root, out)
    except (KiCadCliError, FileNotFoundError) as exc:
        return {"error": f"Netlist generation failed: {exc}"}
    if not result.success:
        return {"error": result.message}

    components, nets = parse_netlist_doc(Document.load(out))
    summary = mgr.apply_update_from_schematic(
        session,
        components,
        nets,
        place_new=place_new,
        remove_extra=remove_extra,
        spacing=spacing,
    )
    summary["status"] = "ok"
    summary["component_count"] = len(components)
    summary["net_count"] = len(nets)
    summary["hint"] = "Review changes, then commit_session to write the board."
    return summary


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
    name="update_pcb_from_schematic",
    description=(
        "Update the board from the schematic netlist (KiCad's 'Update PCB from "
        "Schematic'): instantiate missing footprints, reconcile values, create nets, "
        "and assign nets to pads on a board session. Requires kicad-cli."
    ),
    parameters={
        "session_id": {"type": "string", "description": "Active board session id."},
        "schematic_path": {
            "type": "string",
            "description": "Root .kicad_sch. Defaults to loaded hierarchy/schematic.",
        },
        "place_new": {
            "type": "boolean",
            "description": "Instantiate footprints not yet on the board. Default true.",
        },
        "remove_extra": {
            "type": "boolean",
            "description": "Delete footprints no longer in the schematic. Default false.",
        },
        "spacing": {
            "type": "number",
            "description": "Grid spacing (mm) for newly placed footprints. Default 12.",
        },
    },
    handler=_update_pcb_from_schematic_handler,
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
