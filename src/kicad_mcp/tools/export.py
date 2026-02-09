"""Export tools — Gerber, PDF, SVG, STEP, BOM, position files."""

from __future__ import annotations

from typing import Any

from .registry import register_tool


def _export_gerbers_handler(output_dir: str) -> dict[str, Any]:
    """Export Gerber files for PCB manufacturing.

    Args:
        output_dir: Directory to save Gerber files.
    """
    from .. import state
    from ..backends.kicad_cli import KiCadCli, KiCadCliNotFound

    board_path = state.get_board_path()
    if not board_path:
        return {"error": "No board loaded. Use open_project first."}

    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found. Install KiCad 8+."}

    result = cli.export_gerbers(board_path, output_dir)
    d = result.to_dict()

    # Also export drill files alongside gerbers
    drill_result = cli.export_drill(board_path, output_dir)
    d["drill"] = drill_result.to_dict()

    return d


def _export_pdf_handler(output_path: str, layers: str | None = None) -> dict[str, Any]:
    """Export board layout to PDF.

    Args:
        output_path: Path for the output PDF file.
        layers: Comma-separated layer names (e.g., 'F.Cu,B.Cu,Edge.Cuts'). All layers if omitted.
    """
    from .. import state
    from ..backends.kicad_cli import KiCadCli, KiCadCliNotFound

    board_path = state.get_board_path()
    if not board_path:
        return {"error": "No board loaded. Use open_project first."}

    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found. Install KiCad 8+."}

    layer_list = [lyr.strip() for lyr in layers.split(",")] if layers else None
    result = cli.export_pdf(board_path, output_path, layers=layer_list)
    return result.to_dict()


def _export_svg_handler(output_path: str, layers: str | None = None) -> dict[str, Any]:
    """Export board layout to SVG.

    Args:
        output_path: Path for the output SVG file.
        layers: Comma-separated layer names. All layers if omitted.
    """
    from .. import state
    from ..backends.kicad_cli import KiCadCli, KiCadCliNotFound

    board_path = state.get_board_path()
    if not board_path:
        return {"error": "No board loaded. Use open_project first."}

    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found. Install KiCad 8+."}

    layer_list = [lyr.strip() for lyr in layers.split(",")] if layers else None
    result = cli.export_svg(board_path, output_path, layers=layer_list)
    return result.to_dict()


def _export_step_handler(output_path: str) -> dict[str, Any]:
    """Export board as 3D STEP model for mechanical integration.

    Args:
        output_path: Path for the output STEP file.
    """
    from .. import state
    from ..backends.kicad_cli import KiCadCli, KiCadCliNotFound

    board_path = state.get_board_path()
    if not board_path:
        return {"error": "No board loaded. Use open_project first."}

    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found. Install KiCad 8+."}

    result = cli.export_step(board_path, output_path)
    return result.to_dict()


def _export_pos_handler(output_path: str, side: str = "both") -> dict[str, Any]:
    """Export component position file (pick-and-place) for assembly.

    Args:
        output_path: Path for the output position file.
        side: Board side: 'front', 'back', or 'both'.
    """
    from .. import state
    from ..backends.kicad_cli import KiCadCli, KiCadCliNotFound

    board_path = state.get_board_path()
    if not board_path:
        return {"error": "No board loaded. Use open_project first."}

    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found. Install KiCad 8+."}

    result = cli.export_pos(board_path, output_path, side=side)
    return result.to_dict()


def _export_bom_handler() -> dict[str, Any]:
    """Export a Bill of Materials (BOM) from the currently loaded board.

    Generates BOM from the parsed board data (no kicad-cli required).
    """
    from .. import state

    footprints = state.get_footprints()

    # Group by value+library for BOM
    bom: dict[str, dict[str, Any]] = {}
    for fp in footprints:
        if not fp.reference:
            continue
        key = f"{fp.value}|{fp.library}"
        if key not in bom:
            bom[key] = {
                "value": fp.value,
                "library": fp.library,
                "references": [],
                "quantity": 0,
            }
        bom[key]["references"].append(fp.reference)
        bom[key]["quantity"] += 1

    items = sorted(bom.values(), key=lambda x: x["references"][0])
    return {
        "total_components": len(footprints),
        "unique_values": len(items),
        "items": items,
    }


# Register export tools (all routed except BOM)
register_tool(
    name="export_gerbers",
    description="Export Gerber + drill files for PCB manufacturing.",
    parameters={
        "output_dir": {"type": "string", "description": "Output directory for Gerber files."},
    },
    handler=_export_gerbers_handler,
    category="export",
)

register_tool(
    name="export_pdf",
    description="Export board layout to PDF.",
    parameters={
        "output_path": {"type": "string", "description": "Output PDF path."},
        "layers": {"type": "string", "description": "Comma-separated layers (optional)."},
    },
    handler=_export_pdf_handler,
    category="export",
)

register_tool(
    name="export_svg",
    description="Export board layout to SVG.",
    parameters={
        "output_path": {"type": "string", "description": "Output SVG path."},
        "layers": {"type": "string", "description": "Comma-separated layers (optional)."},
    },
    handler=_export_svg_handler,
    category="export",
)

register_tool(
    name="export_step",
    description="Export board as 3D STEP model.",
    parameters={
        "output_path": {"type": "string", "description": "Output STEP file path."},
    },
    handler=_export_step_handler,
    category="export",
)

register_tool(
    name="export_pos",
    description="Export component position file (pick-and-place).",
    parameters={
        "output_path": {"type": "string", "description": "Output position file path."},
        "side": {"type": "string", "description": "'front', 'back', or 'both'."},
    },
    handler=_export_pos_handler,
    category="export",
)

register_tool(
    name="export_bom",
    description="Export Bill of Materials (BOM) from the board. No kicad-cli required.",
    parameters={},
    handler=_export_bom_handler,
    category="export",
)
