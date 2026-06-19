"""Hierarchical (multi-sheet) schematic tools — navigate and edit sheet trees.

These operate on the hierarchy state in ``schematic_state`` (loaded via
``open_hierarchy``). ``select_sheet`` repoints the single-file API at a chosen
sheet so the existing schematic edit tools (add_symbol, add_wire, …) act on it.
"""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path
from typing import Any

from ..sexp.parser import _quote_if_needed
from ..sexp.parser import parse as sexp_parse
from .registry import register_tool

_VALID_SHAPES = frozenset({"input", "output", "bidirectional", "tri_state", "passive"})

# Static KiCad 10 schematic stamps for newly created sub-sheet files. (The
# dynamic kicad-cli detection lives on a separate branch; reconcile on merge.)
_SCH_VERSION = "20260306"
_GENERATOR_VERSION = "10.0"


def _name_ok(name: str) -> bool:
    return bool(name) and len(name) <= 255 and "\n" not in name and '"' not in name


def _insert_before_sheet_instances(root: Any, node: Any) -> None:
    """Insert a child node before ``sheet_instances`` (KiCad's expected order)."""
    idx = len(root.children)
    for i, child in enumerate(root.children):
        if child.name == "sheet_instances":
            idx = i
            break
    root.children.insert(idx, node)


# ── Read tools ───────────────────────────────────────────────────────


def _open_hierarchy_handler(root_path: str) -> dict[str, Any]:
    """Open a root schematic and resolve its full sheet hierarchy.

    Args:
        root_path: Path to the root .kicad_sch file.
    """
    from .. import schematic_state

    h = schematic_state.load_hierarchy(root_path)
    nodes = list(h.iter_nodes())
    return {
        "status": "ok",
        "root": h.root.file,
        "sheet_count": len(nodes),
        "component_count": len(h.enumerate_components()),
        "missing_sheets": [n.name for n in nodes if n.missing],
        "cycles": [n.name for n in nodes if n.is_cycle],
        "tree": h.root.to_dict(),
    }


def _get_sheet_hierarchy_handler() -> dict[str, Any]:
    """Return the resolved sheet hierarchy tree."""
    from .. import schematic_state

    return schematic_state.get_hierarchy().root.to_dict()


def _list_hierarchical_symbols_handler() -> dict[str, Any]:
    """List every component instance across all sheets, with true references.

    A reused sheet yields one entry per placement (e.g. R1 and R2 for the same
    symbol placed in two sheet copies).
    """
    from .. import schematic_state

    comps = schematic_state.get_hierarchy().enumerate_components()
    return {"count": len(comps), "components": [c.to_dict() for c in comps]}


def _list_sheets_handler() -> dict[str, Any]:
    """List the sub-sheets referenced by the active schematic document."""
    from .. import schematic_state
    from ..schema.extract_schematic import extract_sheets

    doc = schematic_state.get_document()
    sheets = extract_sheets(doc)
    return {"count": len(sheets), "sheets": [s.to_dict() for s in sheets]}


def _select_sheet_handler(instance_path: str) -> dict[str, Any]:
    """Make a sheet placement active so edit tools target its document.

    Args:
        instance_path: The placement's UUID path (from get_sheet_hierarchy),
            e.g. "/<root_uuid>/<sheet_uuid>".
    """
    from .. import schematic_state

    node = schematic_state.set_current_sheet(instance_path)
    return {
        "status": "ok",
        "sheet": node.name,
        "instance_path": node.instance_path,
        "file": node.file,
    }


# ── Edit tools ───────────────────────────────────────────────────────


def _add_hierarchical_label_handler(
    name: str,
    shape: str = "input",
    x: float = 0,
    y: float = 0,
    angle: float = 0,
) -> dict[str, Any]:
    """Add a hierarchical label (child-side port) to the active sheet.

    Args:
        name: Port/net name; must match the parent sheet pin.
        shape: input/output/bidirectional/tri_state/passive.
        x: X position. y: Y position. angle: rotation degrees.
    """
    from .. import schematic_state

    if not _name_ok(name):
        return {"error": f"Invalid label name: {name!r}"}
    if shape not in _VALID_SHAPES:
        return {"error": f"Invalid shape {shape!r}. Use one of {sorted(_VALID_SHAPES)}"}

    doc = schematic_state.get_document()
    luuid = str(_uuid.uuid4())
    text = (
        f"(hierarchical_label {_quote_if_needed(name)} (shape {shape})"
        f" (at {x} {y} {angle}) (effects (font (size 1.27 1.27)))"
        f' (uuid "{luuid}"))'
    )
    _insert_before_sheet_instances(doc.root, sexp_parse(text))
    schematic_state.refresh()
    return {"status": "added", "name": name, "shape": shape, "uuid": luuid}


def _add_sheet_pin_handler(
    sheet_uuid: str,
    name: str,
    shape: str = "input",
    x: float = 0,
    y: float = 0,
    angle: float = 0,
) -> dict[str, Any]:
    """Add a hierarchical pin to an existing (sheet) block in the active document.

    Args:
        sheet_uuid: UUID of the target (sheet) block.
        name: Pin/net name; should match a child hierarchical label.
        shape: input/output/bidirectional/tri_state/passive.
        x: X position. y: Y position. angle: rotation degrees.
    """
    from .. import schematic_state

    if not _name_ok(name):
        return {"error": f"Invalid pin name: {name!r}"}
    if shape not in _VALID_SHAPES:
        return {"error": f"Invalid shape {shape!r}. Use one of {sorted(_VALID_SHAPES)}"}

    doc = schematic_state.get_document()
    sheet_node = None
    for node in doc.root.find_all("sheet"):
        uuid_node = node.get("uuid")
        if uuid_node and uuid_node.first_value == sheet_uuid:
            sheet_node = node
            break
    if sheet_node is None:
        return {"error": f"No (sheet) block with uuid {sheet_uuid!r}"}

    puuid = str(_uuid.uuid4())
    text = (
        f"(pin {_quote_if_needed(name)} {shape} (at {x} {y} {angle})"
        f' (uuid "{puuid}") (effects (font (size 1.27 1.27))))'
    )
    pin_node = sexp_parse(text)
    # Pins go before the sheet's (instances) block if present, else append.
    idx = len(sheet_node.children)
    for i, child in enumerate(sheet_node.children):
        if child.name == "instances":
            idx = i
            break
    sheet_node.children.insert(idx, pin_node)
    schematic_state.refresh()
    return {"status": "added", "sheet_uuid": sheet_uuid, "name": name, "uuid": puuid}


def _add_sheet_handler(
    name: str,
    file: str,
    x: float = 50,
    y: float = 50,
    width: float = 30,
    height: float = 20,
    pins: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Add a sub-sheet to the active schematic, creating its child file.

    The child file is created with one hierarchical label per pin (matching the
    sheet pins), so both sides of each port exist.

    Args:
        name: Sheet name (Sheetname).
        file: Child filename (e.g. "power.kicad_sch"), relative to the parent.
        x: X position. y: Y position. width/height: sheet box size (mm).
        pins: Optional list of {name, shape} for sheet pins / hierarchical labels.
    """
    from .. import schematic_state

    if not _name_ok(name):
        return {"error": f"Invalid sheet name: {name!r}"}
    if not file.endswith(".kicad_sch"):
        return {"error": "file must end with .kicad_sch"}
    pins = pins or []
    for p in pins:
        if not _name_ok(p.get("name", "")):
            return {"error": f"Invalid pin name: {p.get('name')!r}"}
        if p.get("shape", "input") not in _VALID_SHAPES:
            return {"error": f"Invalid pin shape: {p.get('shape')!r}"}

    parent_doc = schematic_state.get_document()
    if parent_doc.path is None:
        return {"error": "Active schematic has no path; save it first"}
    parent_dir = Path(parent_doc.path).parent
    child_path = parent_dir / file
    if child_path.exists():
        return {"error": f"Child file already exists: {child_path}"}

    sheet_uuid = str(_uuid.uuid4())
    child_uuid = str(_uuid.uuid4())

    # Parent instance path that this sheet's contents live under.
    if schematic_state.hierarchy_loaded():
        parent_path = schematic_state.get_current_node().instance_path
        project_name = Path(schematic_state.get_hierarchy().root.file).stem
    else:
        ru = parent_doc.root.get("uuid")
        parent_path = "/" + (ru.first_value or "") if ru else "/"
        project_name = Path(parent_doc.path).stem

    next_page = str(len(parent_doc.root.find_all("sheet")) + 2)

    # Build the child file with matching hierarchical labels.
    hlabels = "\n".join(
        f"\t(hierarchical_label {_quote_if_needed(p['name'])}"
        f" (shape {p.get('shape', 'input')}) (at 30 {40 + i * 5} 180)"
        f" (effects (font (size 1.27 1.27)) (justify right))"
        f' (uuid "{_uuid.uuid4()}"))'
        for i, p in enumerate(pins)
    )
    child_content = (
        f"(kicad_sch\n"
        f"\t(version {_SCH_VERSION})\n"
        f'\t(generator "kicad_mcp")\n'
        f'\t(generator_version "{_GENERATOR_VERSION}")\n'
        f'\t(uuid "{child_uuid}")\n'
        f'\t(paper "A4")\n'
        f"\t(lib_symbols)\n"
    )
    if hlabels:
        child_content += hlabels + "\n"
    child_content += '\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n)\n'
    child_path.write_text(child_content, encoding="utf-8")

    # Build the (sheet) block in the parent.
    pin_text = "".join(
        f" (pin {_quote_if_needed(p['name'])} {p.get('shape', 'input')}"
        f" (at {x} {y + 5 + i * 2.54} 180)"
        f' (uuid "{_uuid.uuid4()}") (effects (font (size 1.27 1.27))))'
        for i, p in enumerate(pins)
    )
    sheet_text = (
        f"(sheet (at {x} {y}) (size {width} {height})"
        f" (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)"
        f' (uuid "{sheet_uuid}")'
        f' (property "Sheetname" {_quote_if_needed(name)} (at {x} {y - 1} 0)'
        f" (effects (font (size 1.27 1.27))))"
        f' (property "Sheetfile" {_quote_if_needed(file)} (at {x} {y + height + 1} 0)'
        f" (effects (font (size 1.27 1.27))))"
        f"{pin_text}"
        f" (instances (project {_quote_if_needed(project_name)}"
        f' (path "{parent_path}" (page "{next_page}"))))'
        f")"
    )
    _insert_before_sheet_instances(parent_doc.root, sexp_parse(sheet_text))
    schematic_state.refresh()

    # Keep the in-memory hierarchy tree consistent without reloading from disk.
    if schematic_state.hierarchy_loaded():
        schematic_state.register_child_sheet(
            parent_path, sheet_uuid, str(child_path.resolve()), name, next_page
        )

    return {
        "status": "added",
        "sheet_name": name,
        "sheet_uuid": sheet_uuid,
        "child_file": str(child_path),
        "child_uuid": child_uuid,
        "page": next_page,
        "pins": [p["name"] for p in pins],
    }


def _remove_sheet_handler(sheet_uuid: str, delete_file: bool = False) -> dict[str, Any]:
    """Remove a (sheet) block from the active document.

    Args:
        sheet_uuid: UUID of the (sheet) block to remove.
        delete_file: If true, also delete the child file when no other sheet in
            the active document references it.
    """
    from .. import schematic_state
    from ..schema.extract_schematic import extract_sheets

    doc = schematic_state.get_document()
    target = None
    for node in doc.root.find_all("sheet"):
        uuid_node = node.get("uuid")
        if uuid_node and uuid_node.first_value == sheet_uuid:
            target = node
            break
    if target is None:
        return {"error": f"No (sheet) block with uuid {sheet_uuid!r}"}

    # Figure out the child file before mutating.
    sheet = next((s for s in extract_sheets(doc) if s.uuid == sheet_uuid), None)
    child_file = sheet.file if sheet else ""

    doc.root.children.remove(target)
    schematic_state.refresh()

    deleted_file = False
    if delete_file and child_file and doc.path is not None:
        still_referenced = any(s.file == child_file for s in extract_sheets(doc))
        if not still_referenced:
            child_path = Path(doc.path).parent / child_file
            if child_path.exists():
                child_path.unlink()
                deleted_file = True

    if schematic_state.hierarchy_loaded():
        schematic_state.unregister_child_sheet(sheet_uuid)

    return {"status": "removed", "sheet_uuid": sheet_uuid, "file_deleted": deleted_file}


def _save_hierarchy_handler() -> dict[str, Any]:
    """Save every loaded sheet document in the hierarchy to disk."""
    from .. import schematic_state

    saved = schematic_state.save_hierarchy()
    return {"status": "saved", "count": len(saved), "files": saved}


# ── Registration ─────────────────────────────────────────────────────

register_tool(
    name="open_hierarchy",
    description="Open a root schematic and resolve its full multi-sheet hierarchy.",
    parameters={
        "root_path": {"type": "string", "description": "Path to root .kicad_sch."},
    },
    handler=_open_hierarchy_handler,
    category="hierarchy",
)

register_tool(
    name="get_sheet_hierarchy",
    description="Return the resolved sheet hierarchy tree (sheets, pages, paths).",
    parameters={},
    handler=_get_sheet_hierarchy_handler,
    category="hierarchy",
)

register_tool(
    name="list_hierarchical_symbols",
    description=(
        "List every component instance across all sheets with its true reference "
        "(reused sheets yield one entry per placement)."
    ),
    parameters={},
    handler=_list_hierarchical_symbols_handler,
    category="hierarchy",
)

register_tool(
    name="list_sheets",
    description="List the sub-sheets referenced by the active schematic.",
    parameters={},
    handler=_list_sheets_handler,
    category="hierarchy",
)

register_tool(
    name="select_sheet",
    description="Make a sheet placement active so edit tools target its document.",
    parameters={
        "instance_path": {
            "type": "string",
            "description": "Placement UUID path, e.g. '/<root_uuid>/<sheet_uuid>'.",
        },
    },
    handler=_select_sheet_handler,
    category="hierarchy",
)

register_tool(
    name="add_hierarchical_label",
    description="Add a hierarchical label (child-side port) to the active sheet.",
    parameters={
        "name": {"type": "string", "description": "Port/net name."},
        "shape": {
            "type": "string",
            "description": "input/output/bidirectional/tri_state/passive.",
        },
        "x": {"type": "number", "description": "X position."},
        "y": {"type": "number", "description": "Y position."},
        "angle": {"type": "number", "description": "Rotation degrees. Default 0."},
    },
    handler=_add_hierarchical_label_handler,
    category="hierarchy",
)

register_tool(
    name="add_sheet_pin",
    description="Add a hierarchical pin to an existing (sheet) block.",
    parameters={
        "sheet_uuid": {"type": "string", "description": "Target (sheet) block uuid."},
        "name": {"type": "string", "description": "Pin/net name."},
        "shape": {
            "type": "string",
            "description": "input/output/bidirectional/tri_state/passive.",
        },
        "x": {"type": "number", "description": "X position."},
        "y": {"type": "number", "description": "Y position."},
        "angle": {"type": "number", "description": "Rotation degrees. Default 0."},
    },
    handler=_add_sheet_pin_handler,
    category="hierarchy",
)

register_tool(
    name="add_sheet",
    description="Add a sub-sheet to the active schematic, creating its child file.",
    parameters={
        "name": {"type": "string", "description": "Sheet name."},
        "file": {"type": "string", "description": "Child filename (*.kicad_sch)."},
        "x": {"type": "number", "description": "X position. Default 50."},
        "y": {"type": "number", "description": "Y position. Default 50."},
        "width": {"type": "number", "description": "Box width mm. Default 30."},
        "height": {"type": "number", "description": "Box height mm. Default 20."},
        "pins": {
            "type": "array",
            "description": "Optional [{name, shape}] sheet pins / hierarchical labels.",
        },
    },
    handler=_add_sheet_handler,
    category="hierarchy",
)

register_tool(
    name="remove_sheet",
    description="Remove a (sheet) block from the active schematic.",
    parameters={
        "sheet_uuid": {"type": "string", "description": "(sheet) block uuid."},
        "delete_file": {
            "type": "boolean",
            "description": "Also delete the child file if unreferenced. Default false.",
        },
    },
    handler=_remove_sheet_handler,
    category="hierarchy",
)

register_tool(
    name="save_hierarchy",
    description="Save every loaded sheet document in the hierarchy to disk.",
    parameters={},
    handler=_save_hierarchy_handler,
    category="hierarchy",
)
