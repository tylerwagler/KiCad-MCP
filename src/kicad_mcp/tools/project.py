"""Project management tools — create and save KiCad projects."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .registry import register_tool

# ── Templates ──────────────────────────────────────────────────────

_KICAD_PRO_TEMPLATE: dict[str, Any] = {
    "board": {"design_settings": {"defaults": {"board_outline_line_width": 0.05}}},
    "boards": [],
    "cvpcb": {"equivalence_files": []},
    "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
    "meta": {"filename": "", "version": 1},
    "net_settings": {"classes": []},
    "pcbnew": {"last_paths": {"gencad": "", "idf": "", "netlist": "", "vrml": ""}},
    "schematic": {"legacy_lib_list": []},
    "sheets": [],
    "text_variables": {},
}


def _minimal_kicad_pcb(
    width: float | None = None,
    height: float | None = None,
) -> str:
    """Generate a minimal .kicad_pcb S-expression."""
    lines = [
        '(kicad_pcb (version 20241229) (generator "kicad_mcp") (generator_version "9.0")',
        "  (general (thickness 1.6) (legacy_teardrops no))",
        '  (paper "A4")',
        "  (layers",
        '    (0 "F.Cu" signal)',
        '    (31 "B.Cu" signal)',
        '    (32 "B.Adhes" user "B.Adhesive")',
        '    (33 "F.Adhes" user "F.Adhesive")',
        '    (34 "B.Paste" user)',
        '    (35 "F.Paste" user)',
        '    (36 "B.SilkS" user "B.Silkscreen")',
        '    (37 "F.SilkS" user "F.Silkscreen")',
        '    (38 "B.Mask" user)',
        '    (39 "F.Mask" user)',
        '    (40 "Dwgs.User" user "User.Drawings")',
        '    (41 "Cmts.User" user "User.Comments")',
        '    (42 "Eco1.User" user "User.Eco1")',
        '    (43 "Eco2.User" user "User.Eco2")',
        '    (44 "Edge.Cuts" user)',
        '    (45 "Margin" user)',
        '    (46 "B.CrtYd" user "B.Courtyard")',
        '    (47 "F.CrtYd" user "F.Courtyard")',
        '    (48 "B.Fab" user)',
        '    (49 "F.Fab" user)',
        "  )",
        "  (setup",
        "    (pad_to_mask_clearance 0)",
        "    (allow_soldermask_bridges_in_footprints no)",
        "    (pcbplotparams",
        "      (layerselection 0x00010fc_ffffffff)"
        " (plot_on_all_layers_selection 0x0000000_00000000))",
        "  )",
        '  (net 0 "")',
    ]

    if width is not None and height is not None:
        for x1, y1, x2, y2 in [
            (0, 0, width, 0),
            (width, 0, width, height),
            (width, height, 0, height),
            (0, height, 0, 0),
        ]:
            line_uuid = str(uuid.uuid4())
            lines.append(
                f"  (gr_line (start {x1} {y1}) (end {x2} {y2})"
                f" (stroke (width 0.05) (type default))"
                f' (layer "Edge.Cuts") (uuid "{line_uuid}"))'
            )

    lines.append(")")
    return "\n".join(lines)


def _minimal_kicad_sch() -> str:
    """Generate a minimal .kicad_sch S-expression."""
    sch_uuid = str(uuid.uuid4())
    return (
        f'(kicad_sch (version 20231120) (generator "kicad_mcp") (generator_version "9.0")\n'
        f'  (uuid "{sch_uuid}")\n'
        f'  (paper "A4")\n'
        f"  (lib_symbols)\n"
        f'  (sheet_instances (path "/"  (page "1")))\n'
        f")"
    )


# ── Handlers ────────────────────────────────────────────────────────


def _create_project_handler(
    name: str,
    directory: str,
    board_size_x: float | None = None,
    board_size_y: float | None = None,
) -> dict[str, Any]:
    """Create a new KiCad project with minimal template files.

    Args:
        name: Project name (used for filenames).
        directory: Directory to create the project in.
        board_size_x: Optional board width in mm.
        board_size_y: Optional board height in mm.
    """
    proj_dir = Path(directory)
    proj_dir.mkdir(parents=True, exist_ok=True)

    # Generate .kicad_pro
    pro_data = dict(_KICAD_PRO_TEMPLATE)
    pro_data["meta"]["filename"] = f"{name}.kicad_pro"
    pro_path = proj_dir / f"{name}.kicad_pro"
    pro_path.write_text(json.dumps(pro_data, indent=2), encoding="utf-8")

    # Generate .kicad_pcb
    pcb_path = proj_dir / f"{name}.kicad_pcb"
    pcb_path.write_text(
        _minimal_kicad_pcb(board_size_x, board_size_y),
        encoding="utf-8",
    )

    # Generate .kicad_sch
    sch_path = proj_dir / f"{name}.kicad_sch"
    sch_path.write_text(_minimal_kicad_sch(), encoding="utf-8")

    created = [str(pro_path), str(pcb_path), str(sch_path)]
    return {
        "status": "created",
        "project_name": name,
        "directory": str(proj_dir),
        "files": created,
    }


def _save_project_handler(output_path: str | None = None) -> dict[str, Any]:
    """Save the current board to disk.

    Args:
        output_path: Optional output path. If not provided, overwrites the original.
    """
    from .. import state

    doc = state.get_document()
    saved_path = doc.save(output_path)
    return {"status": "saved", "path": str(saved_path)}


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="create_project",
    description="Create a new KiCad project with board, schematic, and project files.",
    parameters={
        "name": {"type": "string", "description": "Project name."},
        "directory": {"type": "string", "description": "Target directory."},
        "board_size_x": {"type": "number", "description": "Board width (mm). Optional."},
        "board_size_y": {"type": "number", "description": "Board height (mm). Optional."},
    },
    handler=_create_project_handler,
    category="project",
)

register_tool(
    name="save_project",
    description="Save the current board to disk.",
    parameters={
        "output_path": {"type": "string", "description": "Optional output path."},
    },
    handler=_save_project_handler,
    category="project",
)
