"""Visual feedback tools — render a 2D view of the board for inspection."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .registry import register_tool

# Default layer set for a readable 2D overview (copper + silk + outline).
_DEFAULT_VIEW_LAYERS = ["F.Cu", "B.Cu", "F.SilkS", "B.SilkS", "Edge.Cuts"]

_SVG_DIM_RE = re.compile(r'(width|height)\s*=\s*"([0-9.]+)([a-z%]*)"')


def _parse_svg_dimensions(svg_text: str) -> dict[str, str]:
    """Pull width/height attributes off the root <svg> tag (best-effort)."""
    dims: dict[str, str] = {}
    head = svg_text[:1000]
    for match in _SVG_DIM_RE.finditer(head):
        dims[match.group(1)] = f"{match.group(2)}{match.group(3)}"
        if "width" in dims and "height" in dims:
            break
    return dims


def _get_board_2d_view_handler(
    output_path: str | None = None,
    layers: str | None = None,
) -> dict[str, Any]:
    """Render a 2D SVG view of the current board for visual inspection.

    Produces an SVG file (openable in any browser/viewer) plus structured
    board statistics so the model has context alongside the rendered view.

    Args:
        output_path: Where to write the .svg. A temp file is used if omitted.
        layers: Comma-separated layers to render. Defaults to copper + silk + edge.
    """
    from .. import state
    from ..backends.kicad_cli import KiCadCli, KiCadCliError, KiCadCliNotFound
    from ..security import SecurityError, get_validator

    board_path = state.get_board_path()
    if not board_path:
        return {"error": "No board loaded. Use open_project first."}

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".svg", prefix="board_view_")
        os.close(fd)

    try:
        get_validator().validate_output(output_path)
    except SecurityError as exc:
        return {"error": f"Security error: {exc}"}

    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found. Install KiCad 8+ to render board views."}

    layer_list = [lyr.strip() for lyr in layers.split(",")] if layers else _DEFAULT_VIEW_LAYERS

    try:
        result = cli.export_svg(board_path, output_path, layers=layer_list)
    except KiCadCliError as exc:
        return {"error": f"Board render failed: {exc}"}

    if not result.success:
        return {"error": result.message}

    # Gather dimensions and a compact board summary for context.
    dimensions: dict[str, str] = {}
    with contextlib.suppress(OSError):
        dimensions = _parse_svg_dimensions(Path(output_path).read_text(encoding="utf-8"))

    out: dict[str, Any] = {
        "status": "rendered",
        "image_path": output_path,
        "format": "svg",
        "layers": layer_list,
        "dimensions": dimensions,
    }

    try:
        summary = state.get_summary()
        out["board"] = {
            "title": summary.title,
            "footprint_count": summary.footprint_count,
            "net_count": summary.net_count,
            "layer_count": summary.layer_count,
        }
    except RuntimeError:
        pass

    return out


register_tool(
    name="get_board_2d_view",
    description=(
        "Render a 2D SVG view of the current board (copper + silk + outline) for visual "
        "inspection, and return the file path plus board stats."
    ),
    parameters={
        "output_path": {
            "type": "string",
            "description": "Output .svg path. A temp file is used if omitted.",
        },
        "layers": {
            "type": "string",
            "description": "Comma-separated layers to render (optional).",
        },
    },
    handler=_get_board_2d_view_handler,
    category="visual",
)
