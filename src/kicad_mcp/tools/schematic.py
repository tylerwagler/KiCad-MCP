"""Schematic tools — open, inspect, and modify .kicad_sch files."""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from ..sexp.parser import parse as sexp_parse
from .registry import register_tool

# ── Handlers ────────────────────────────────────────────────────────


def _open_schematic_handler(schematic_path: str) -> dict[str, Any]:
    """Open a KiCad schematic file (.kicad_sch) for analysis.

    Args:
        schematic_path: Path to a .kicad_sch file.
    """
    from .. import schematic_state

    summary = schematic_state.load_schematic(schematic_path)
    return {
        "status": "ok",
        "message": f"Loaded schematic ({summary.symbol_count} symbols)",
        "summary": summary.to_dict(),
    }


def _get_schematic_info_handler() -> dict[str, Any]:
    """Get summary information about the currently loaded schematic."""
    from .. import schematic_state

    summary = schematic_state.get_summary()
    return summary.to_dict()


def _list_symbols_handler() -> dict[str, Any]:
    """List all symbol instances placed in the schematic."""
    from .. import schematic_state

    symbols = schematic_state.get_symbols()
    return {
        "count": len(symbols),
        "symbols": [
            {
                "reference": s.reference,
                "value": s.value,
                "lib_id": s.lib_id,
                "position": s.position.to_dict(),
                "uuid": s.uuid,
            }
            for s in symbols
        ],
    }


def _find_symbol_handler(reference: str) -> dict[str, Any]:
    """Find a symbol by its reference designator.

    Args:
        reference: Reference designator (e.g., "R1", "U1").
    """
    from .. import schematic_state

    symbols = schematic_state.get_symbols()
    matches = [s for s in symbols if s.reference == reference]
    if not matches:
        return {"found": False, "message": f"No symbol with reference '{reference}'"}
    return {"found": True, "symbol": matches[0].to_dict()}


def _add_symbol_handler(
    lib_id: str,
    reference: str,
    value: str,
    x: float,
    y: float,
    angle: float = 0,
    unit: int = 1,
) -> dict[str, Any]:
    """Add a new symbol instance to the schematic.

    Args:
        lib_id: Library symbol ID (e.g., "Device:R", "Device:C").
        reference: Reference designator (e.g., "R1").
        value: Component value (e.g., "10k").
        x: X position.
        y: Y position.
        angle: Rotation angle in degrees. Default: 0.
        unit: Symbol unit number. Default: 1.
    """
    from .. import schematic_state

    doc = schematic_state.get_document()

    # Check for duplicate reference
    symbols = schematic_state.get_symbols()
    if any(s.reference == reference for s in symbols):
        return {"error": f"Symbol with reference '{reference}' already exists"}

    sym_uuid = str(_uuid.uuid4())
    pin1_uuid = str(_uuid.uuid4())
    pin2_uuid = str(_uuid.uuid4())

    angle_str = f" {angle}" if angle != 0 else ""
    sym_text = (
        f'(symbol (lib_id "{lib_id}") (at {x} {y}{angle_str}) (unit {unit})'
        f" (in_bom yes) (on_board yes)"
        f' (uuid "{sym_uuid}")'
        f' (property "Reference" "{reference}" (at {x} {y - 2.54} 0)'
        f" (effects (font (size 1.27 1.27))))"
        f' (property "Value" "{value}" (at {x} {y + 2.54} 0)'
        f" (effects (font (size 1.27 1.27))))"
        f' (property "Footprint" "" (at {x} {y} 0)'
        f" (effects (font (size 1.27 1.27)) hide))"
        f' (property "Datasheet" "~" (at {x} {y} 0)'
        f" (effects (font (size 1.27 1.27)) hide))"
        f' (pin "1" (uuid "{pin1_uuid}"))'
        f' (pin "2" (uuid "{pin2_uuid}")))'
    )
    sym_node = sexp_parse(sym_text)

    # Insert before sheet_instances if present, else append
    insert_idx = len(doc.root.children)
    for i, child in enumerate(doc.root.children):
        if child.name == "sheet_instances":
            insert_idx = i
            break
    doc.root.children.insert(insert_idx, sym_node)

    # Refresh state
    schematic_state.refresh()

    return {
        "status": "added",
        "reference": reference,
        "uuid": sym_uuid,
        "position": {"x": x, "y": y},
    }


def _add_wire_handler(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> dict[str, Any]:
    """Add a wire connecting two points on the schematic.

    Args:
        start_x: Start X coordinate.
        start_y: Start Y coordinate.
        end_x: End X coordinate.
        end_y: End Y coordinate.
    """
    from .. import schematic_state

    doc = schematic_state.get_document()

    wire_uuid = str(_uuid.uuid4())
    wire_text = (
        f"(wire (pts (xy {start_x} {start_y}) (xy {end_x} {end_y}))"
        f' (stroke (width 0) (type default))'
        f' (uuid "{wire_uuid}"))'
    )
    wire_node = sexp_parse(wire_text)

    insert_idx = len(doc.root.children)
    for i, child in enumerate(doc.root.children):
        if child.name == "sheet_instances":
            insert_idx = i
            break
    doc.root.children.insert(insert_idx, wire_node)

    schematic_state.refresh()

    return {
        "status": "added",
        "uuid": wire_uuid,
        "start": {"x": start_x, "y": start_y},
        "end": {"x": end_x, "y": end_y},
    }


def _add_label_handler(
    name: str,
    x: float,
    y: float,
    angle: float = 0,
) -> dict[str, Any]:
    """Add a net label to the schematic.

    Args:
        name: Net label name (e.g., "VCC", "GND", "SDA").
        x: X position.
        y: Y position.
        angle: Rotation angle in degrees. Default: 0.
    """
    from .. import schematic_state

    doc = schematic_state.get_document()

    label_uuid = str(_uuid.uuid4())
    angle_str = f" {angle}" if angle != 0 else ""
    label_text = (
        f'(label "{name}" (at {x} {y}{angle_str})'
        f" (effects (font (size 1.27 1.27)) (justify left))"
        f' (uuid "{label_uuid}"))'
    )
    label_node = sexp_parse(label_text)

    insert_idx = len(doc.root.children)
    for i, child in enumerate(doc.root.children):
        if child.name == "sheet_instances":
            insert_idx = i
            break
    doc.root.children.insert(insert_idx, label_node)

    schematic_state.refresh()

    return {
        "status": "added",
        "name": name,
        "uuid": label_uuid,
        "position": {"x": x, "y": y},
    }


def _delete_symbol_handler(reference: str) -> dict[str, Any]:
    """Delete a symbol from the schematic by reference.

    Args:
        reference: Reference designator (e.g., "R1").
    """
    from .. import schematic_state

    doc = schematic_state.get_document()

    # Find the symbol node
    target = None
    for sym_node in doc.root.find_all("symbol"):
        lib_id_node = sym_node.get("lib_id")
        if lib_id_node is None:
            continue
        for prop in sym_node.find_all("property"):
            if prop.first_value == "Reference":
                vals = prop.atom_values
                if len(vals) > 1 and vals[1] == reference:
                    target = sym_node
                    break
        if target:
            break

    if target is None:
        return {"error": f"Symbol with reference '{reference}' not found"}

    doc.root.children.remove(target)
    schematic_state.refresh()

    return {"status": "deleted", "reference": reference}


def _save_schematic_handler(output_path: str | None = None) -> dict[str, Any]:
    """Save the schematic to disk.

    Args:
        output_path: Optional output path. If not provided, overwrites the original.
    """
    from .. import schematic_state

    doc = schematic_state.get_document()
    saved_path = doc.save(output_path)
    return {"status": "saved", "path": str(saved_path)}


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="open_schematic",
    description="Open a KiCad schematic file (.kicad_sch) for analysis and editing.",
    parameters={
        "schematic_path": {
            "type": "string",
            "description": "Path to .kicad_sch file.",
        },
    },
    handler=_open_schematic_handler,
    category="schematic",
    direct=True,
)

register_tool(
    name="get_schematic_info",
    description="Get summary of the loaded schematic (symbols, wires, labels).",
    parameters={},
    handler=_get_schematic_info_handler,
    category="schematic",
)

register_tool(
    name="list_sch_symbols",
    description="List all symbol instances in the schematic.",
    parameters={},
    handler=_list_symbols_handler,
    category="schematic",
)

register_tool(
    name="find_sch_symbol",
    description="Find a schematic symbol by reference designator.",
    parameters={
        "reference": {
            "type": "string",
            "description": "Reference designator (e.g., 'R1').",
        },
    },
    handler=_find_symbol_handler,
    category="schematic",
)

register_tool(
    name="add_symbol",
    description="Add a new symbol to the schematic.",
    parameters={
        "lib_id": {
            "type": "string",
            "description": "Library:Symbol ID (e.g., 'Device:R').",
        },
        "reference": {"type": "string", "description": "Reference designator."},
        "value": {"type": "string", "description": "Component value."},
        "x": {"type": "number", "description": "X position."},
        "y": {"type": "number", "description": "Y position."},
        "angle": {"type": "number", "description": "Rotation degrees. Default: 0."},
        "unit": {"type": "integer", "description": "Symbol unit. Default: 1."},
    },
    handler=_add_symbol_handler,
    category="schematic",
)

register_tool(
    name="add_wire",
    description="Add a wire connecting two points on the schematic.",
    parameters={
        "start_x": {"type": "number", "description": "Start X."},
        "start_y": {"type": "number", "description": "Start Y."},
        "end_x": {"type": "number", "description": "End X."},
        "end_y": {"type": "number", "description": "End Y."},
    },
    handler=_add_wire_handler,
    category="schematic",
)

register_tool(
    name="add_label",
    description="Add a net label to the schematic.",
    parameters={
        "name": {"type": "string", "description": "Label name (e.g., 'VCC')."},
        "x": {"type": "number", "description": "X position."},
        "y": {"type": "number", "description": "Y position."},
        "angle": {"type": "number", "description": "Rotation degrees. Default: 0."},
    },
    handler=_add_label_handler,
    category="schematic",
)

register_tool(
    name="delete_symbol",
    description="Delete a symbol from the schematic by reference designator.",
    parameters={
        "reference": {"type": "string", "description": "Reference designator."},
    },
    handler=_delete_symbol_handler,
    category="schematic",
)

register_tool(
    name="save_schematic",
    description="Save the current schematic to disk.",
    parameters={
        "output_path": {
            "type": "string",
            "description": "Optional output path. Overwrites original if not provided.",
        },
    },
    handler=_save_schematic_handler,
    category="schematic",
)
