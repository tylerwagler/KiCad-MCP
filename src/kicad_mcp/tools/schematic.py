"""Schematic tools — open, inspect, and modify .kicad_sch files."""

from __future__ import annotations

import math
import re
import uuid as _uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..library import _kicad_env_paths, _parse_lib_table, discover_lib_tables
from ..sexp import Document
from ..sexp.parser import SExp, _quote_if_needed
from ..sexp.parser import parse as sexp_parse
from .registry import register_tool

# pin number -> (x, y, angle, length) in the symbol's local frame (mm, +Y up)
PinGeom = dict[str, tuple[float, float, float, float]]


def _validate_net_name(name: str) -> None:
    """Validate a net name."""
    if not name:
        raise ValueError("Net name cannot be empty")
    if len(name) > 255:
        raise ValueError("Net name too long (max 255 chars)")
    # KiCad net names can contain alphanumerics, _, -, /
    if not re.match(r"^[a-zA-Z0-9_\-/]+$", name):
        raise ValueError(f"Invalid net name: {name!r}")


def _validate_layer_name(name: str) -> None:
    """Validate a layer name."""
    if not name:
        raise ValueError("Layer name cannot be empty")
    if len(name) > 64:
        raise ValueError("Layer name too long (max 64 chars)")
    # KiCad layer names use letters, dots, underscores
    if not re.match(r"^[a-zA-Z0-9._-]+$", name):
        raise ValueError(f"Invalid layer name: {name!r}")


def _validate_reference(ref: str) -> None:
    """Validate a reference designator."""
    if not ref:
        raise ValueError("Reference cannot be empty")
    if len(ref) > 32:
        raise ValueError("Reference too long (max 32 chars)")
    # KiCad references contain alphanumerics, _, -, . — and a leading '#' for
    # virtual/power references (e.g. #PWR01, #FLG01) that are excluded from
    # annotation and the BOM.
    if not re.match(r"^#?[a-zA-Z0-9_.\-]+$", ref):
        raise ValueError(f"Invalid reference: {ref!r}")


def _validate_value(value: str) -> None:
    """Validate a component value."""
    if not value:
        raise ValueError("Value cannot be empty")
    if len(value) > 255:
        raise ValueError("Value too long (max 255 chars)")


def _validate_lib_id(lib_id: str) -> None:
    """Validate a library symbol ID."""
    if not lib_id:
        raise ValueError("lib_id cannot be empty")
    if len(lib_id) > 128:
        raise ValueError("lib_id too long (max 128 chars)")
    # KiCad library IDs use letters, numbers, _, -, :
    if not re.match(r"^[a-zA-Z0-9_\-:]+$", lib_id):
        raise ValueError(f"Invalid lib_id: {lib_id!r}")


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

    result: dict[str, Any] = {"found": True, "symbol": matches[0].to_dict()}
    # Include absolute pin coordinates so callers can land wires/labels on pins.
    doc = schematic_state.get_document()
    node = _find_instance_node(doc, reference)
    if node is not None:
        lib_id_node = node.get("lib_id")
        geo = _embedded_pin_geometry(doc, lib_id_node.first_value if lib_id_node else None)
        if geo:
            result["pins"] = _instance_pin_positions(doc, node, geo)
    return result


def _get_pin_position_handler(reference: str, pin: str) -> dict[str, Any]:
    """Compute the absolute schematic coordinate (mm) of a symbol's pin.

    Use this to land a wire or net label exactly on a pin so the net connects.

    Args:
        reference: Reference designator of the placed symbol (e.g., "U1").
        pin: Pin number (e.g., "1", "8").
    """
    from .. import schematic_state

    doc = schematic_state.get_document()
    node = _find_instance_node(doc, reference)
    if node is None:
        return {"error": f"Symbol '{reference}' not found"}

    lib_id_node = node.get("lib_id")
    geo = _embedded_pin_geometry(doc, lib_id_node.first_value if lib_id_node else None)
    pin = str(pin)
    if not geo or pin not in geo:
        return {
            "error": f"Pin {pin!r} not found on {reference}",
            "available_pins": sorted(geo) if geo else [],
        }

    positions = {p["pin"]: p for p in _instance_pin_positions(doc, node, geo)}
    p = positions[pin]
    return {"reference": reference, "pin": pin, "x": p["x"], "y": p["y"]}


def _resolve_symbol_lib_path(lib_name: str, project_dir: Path) -> Path | None:
    """Resolve a symbol-library name to its .kicad_sym path.

    Checks the project sym-lib-table first (so ${KIPRJMOD} libraries like the
    project's own library resolve), then the global/user sym-lib-table.
    """
    proj_table = project_dir / "sym-lib-table"
    if proj_table.exists():
        env = _kicad_env_paths()
        env["KIPRJMOD"] = project_dir
        for entry in _parse_lib_table(proj_table, env):
            if entry.name == lib_name and Path(entry.uri).exists():
                return Path(entry.uri)
    for entry in discover_lib_tables().get("symbol_libraries", []):
        if entry.name == lib_name and Path(entry.uri).exists():
            return Path(entry.uri)
    return None


def _load_lib_symbol_node(lib_path: Path, sym_name: str) -> SExp | None:
    """Return the top-level (symbol "<name>" ...) node from a .kicad_sym, or None."""
    try:
        doc = Document.load(str(lib_path))
    except (OSError, ValueError):
        return None
    for sym in doc.root.find_all("symbol"):
        if sym.first_value == sym_name:
            return sym
    return None


def _symbol_pin_numbers(sym_node: SExp) -> list[str]:
    """Collect pin numbers from a lib symbol's unit sub-symbols, in document order."""
    numbers: list[str] = []
    for unit in sym_node.find_all("symbol"):  # child unit sub-symbols (Name_x_y)
        for pin in unit.find_all("pin"):
            num = pin.get("number")
            if num is not None and num.first_value:
                numbers.append(num.first_value)
    return numbers


def _symbol_pin_geometry(sym_node: SExp) -> PinGeom:
    """Map pin number -> (x, y, angle, length) in the symbol's local frame.

    Coordinates are in mm with the library convention (+Y up). The pin's ``at`` is
    its connection point (where wires/labels attach); ``length`` is the graphic
    line length and is not part of the connection point.
    """
    geo: dict[str, tuple[float, float, float, float]] = {}
    for unit in sym_node.find_all("symbol"):
        for pin in unit.find_all("pin"):
            num = pin.get("number")
            at = pin.get("at")
            if num is None or not num.first_value or at is None:
                continue
            av = at.atom_values
            try:
                px = float(av[0])
                py = float(av[1])
                pa = float(av[2]) if len(av) > 2 else 0.0
            except (ValueError, IndexError):
                continue
            length = pin.get("length")
            ln = 0.0
            if length is not None and length.first_value:
                try:
                    ln = float(length.first_value)
                except ValueError:
                    ln = 0.0
            geo[num.first_value] = (px, py, pa, ln)
    return geo


def _symbol_property_value(sym_node: SExp, name: str) -> str | None:
    """Return a lib symbol's ``(property "<name>" "<value>" ...)`` value, or None."""
    for prop in sym_node.find_all("property"):
        if prop.first_value == name:
            vals = prop.atom_values
            return vals[1] if len(vals) > 1 else ""
    return None


def _symbol_flag(sym_node: SExp, name: str, default: str = "yes") -> str:
    """Read a lib symbol's yes/no flag (e.g. ``(in_bom no)``), defaulting if absent.

    Only the symbol's own direct flags are honored — not the units' — so power
    symbols and other non-BOM parts (mounting holes, fiducials, logos) keep their
    declared attributes instead of being forced into the BOM / onto the board.
    """
    for child in sym_node.children:
        if child.name == name and child.first_value in ("yes", "no"):
            return child.first_value
    return default


def _transform_pin(
    px: float, py: float, ox: float, oy: float, angle: float, mirror: str | None
) -> tuple[float, float]:
    """Map a symbol-local pin (mm, +Y up) to absolute schematic coords (mm, +Y down).

    Applies mirror, then the instance rotation (CCW in library space), then the
    library->schematic Y-flip, then translates by the instance origin. The
    schematic Y axis points down, so library +Y becomes schematic -Y.
    """
    x, y = px, py
    if mirror == "x":  # mirror across the X axis
        y = -y
    elif mirror == "y":  # mirror across the Y axis
        x = -x
    a = round(angle) % 360
    if a == 90:
        x, y = -y, x
    elif a == 180:
        x, y = -x, -y
    elif a == 270:
        x, y = y, -x
    elif a != 0:
        rad = math.radians(angle)
        c, s = math.cos(rad), math.sin(rad)
        x, y = x * c - y * s, x * s + y * c
    return (ox + x, oy - y)


def _resolve_lib_symbol(doc: Document, lib_id: str) -> dict[str, Any] | None:
    """Resolve a lib_id to its real symbol and embed it into the schematic.

    Returns ``{"pins", "geometry", "footprint"}`` (pin numbers in order, per-pin
    local geometry, and the symbol's Footprint property), or None when the symbol
    cannot be resolved (caller falls back to a 2-pin stub for unknown libraries).
    """
    if ":" not in lib_id or doc.path is None:
        return None
    lib_name, sym_name = lib_id.split(":", 1)
    project_dir = Path(doc.path).resolve().parent
    lib_path = _resolve_symbol_lib_path(lib_name, project_dir)
    if lib_path is None:
        return None
    sym_node = _load_lib_symbol_node(lib_path, sym_name)
    if sym_node is None:
        return None

    result = {
        "pins": _symbol_pin_numbers(sym_node),
        "geometry": _symbol_pin_geometry(sym_node),
        "footprint": _symbol_property_value(sym_node, "Footprint") or "",
        "in_bom": _symbol_flag(sym_node, "in_bom"),
        "on_board": _symbol_flag(sym_node, "on_board"),
    }

    lib_symbols = doc.root.find("lib_symbols")
    if lib_symbols is None:
        lib_symbols = sexp_parse("(lib_symbols)")
        # place after the (paper)/(generator) header, before the first symbol
        idx = next(
            (i for i, c in enumerate(doc.root.children) if c.name == "symbol"),
            len(doc.root.children),
        )
        doc.root.children.insert(idx, lib_symbols)

    already = any(c.name == "symbol" and c.first_value == lib_id for c in lib_symbols.children)
    if not already:
        embedded = sym_node.deep_copy()
        # KiCad names the embedded top-level symbol "lib:Name"; units keep bare names.
        if embedded.children and embedded.children[0].is_atom:
            embedded.children[0].value = lib_id
            # deep_copy kept the atom's ORIGINAL quoted text, which to_string()
            # would re-emit verbatim — losing the rename. Force the quoted new value
            # (lib_id is validated to safe chars, so no escaping is needed) to match
            # KiCad's canonical "lib:Name" form.
            embedded.children[0]._original_str = f'"{lib_id}"'
        lib_symbols.children.append(embedded)
    return result


def _find_instance_node(doc: Document, reference: str) -> SExp | None:
    """Find a placed symbol instance node by reference designator, or None."""
    for sym_node in doc.root.find_all("symbol"):
        if sym_node.get("lib_id") is None:
            continue
        for prop in sym_node.find_all("property"):
            if prop.first_value == "Reference":
                vals = prop.atom_values
                if len(vals) > 1 and vals[1] == reference:
                    return sym_node
    return None


def _embedded_pin_geometry(doc: Document, lib_id: str | None) -> PinGeom | None:
    """Pin geometry for a lib_id, preferring the schematic's own embedded symbol.

    Falls back to re-resolving the external library if not embedded.
    """
    if not lib_id:
        return None
    lib_symbols = doc.root.find("lib_symbols")
    if lib_symbols is not None:
        for child in lib_symbols.children:
            if child.name == "symbol" and child.first_value == lib_id:
                return _symbol_pin_geometry(child)
    if ":" in lib_id and doc.path is not None:
        lib_name, sym_name = lib_id.split(":", 1)
        lib_path = _resolve_symbol_lib_path(lib_name, Path(doc.path).resolve().parent)
        if lib_path is not None:
            sym_node = _load_lib_symbol_node(lib_path, sym_name)
            if sym_node is not None:
                return _symbol_pin_geometry(sym_node)
    return None


def _instance_pin_positions(
    doc: Document, sym_node: SExp, geometry: PinGeom
) -> list[dict[str, Any]]:
    """Absolute schematic coords (mm) for every pin of a placed instance."""
    at = sym_node.get("at")
    av = at.atom_values if at else []
    try:
        ox = float(av[0])
        oy = float(av[1])
        angle = float(av[2]) if len(av) > 2 else 0.0
    except (ValueError, IndexError):
        return []
    mirror_node = sym_node.get("mirror")
    mirror = mirror_node.first_value if mirror_node else None
    out: list[dict[str, Any]] = []
    for num, (px, py, _pa, _ln) in geometry.items():
        sx, sy = _transform_pin(px, py, ox, oy, angle, mirror)
        out.append({"pin": num, "x": round(sx, 4), "y": round(sy, 4)})
    return out


def _placement_paths(doc: Document) -> tuple[list[str], str]:
    """Instance paths for each placement of ``doc``'s file + the project name.

    Hierarchy-aware: a reused sheet has one path per placement. Falls back to
    the single root path ``/<root_uuid>`` when no hierarchy is loaded.
    """
    from .. import schematic_state

    if schematic_state.hierarchy_loaded():
        h = schematic_state.get_hierarchy()
        paths = [
            n.instance_path
            for n in h.iter_nodes()
            if n.file == str(doc.path) and not n.is_cycle and not n.missing
        ]
        if paths:
            return paths, Path(h.root.file).stem
    root_uuid_node = doc.root.get("uuid")
    root_uuid = root_uuid_node.first_value if root_uuid_node else str(_uuid.uuid4())
    return [f"/{root_uuid}"], (Path(doc.path).stem if doc.path else "noname")


def _used_references(doc: Document) -> set[str]:
    """Every reference in use — across the whole hierarchy if one is loaded."""
    from .. import schematic_state

    if schematic_state.hierarchy_loaded():
        return {c.reference for c in schematic_state.get_hierarchy().enumerate_components()}
    return {s.reference for s in schematic_state.get_symbols()}


def _build_instances(doc: Document, reference: str, unit: int) -> tuple[str, list[str], str | None]:
    """Build the ``(instances ...)`` block, assigning a distinct reference per
    placement.

    A symbol added to a reused sheet is one physical component per placement, so
    each placement must get its own reference. The given ``reference`` is used
    for the first placement; each additional placement gets the next free number
    with the same prefix (unique across the whole hierarchy). Returns
    ``(instances_text, assigned_refs, error)``.
    """
    from ..schema.hierarchy import next_free_reference, split_reference

    paths, project_name = _placement_paths(doc)
    used = _used_references(doc)
    if reference in used:
        return "", [], f"Symbol with reference '{reference}' already exists"

    prefix, _ = split_reference(reference)
    assigned = [reference]
    used = used | {reference}
    for _ in paths[1:]:
        nref = next_free_reference(prefix, used)
        assigned.append(nref)
        used.add(nref)

    path_text = " ".join(
        f'(path "{p}" (reference {_quote_if_needed(r)}) (unit {unit}))'
        for p, r in zip(paths, assigned, strict=True)
    )
    instances = f"(instances (project {_quote_if_needed(project_name)} {path_text}))"
    return instances, assigned, None


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

    # Validate inputs to prevent S-expression injection
    _validate_lib_id(lib_id)
    _validate_reference(reference)
    _validate_value(value)

    # Build the per-placement instances block (allocates distinct references
    # across a reused sheet) and reject duplicate references hierarchy-wide.
    instances_text, assigned_refs, inst_error = _build_instances(doc, reference, unit)
    if inst_error:
        return {"error": inst_error}

    sym_uuid = str(_uuid.uuid4())

    # Resolve the real library symbol: embed its definition into (lib_symbols),
    # emit one instance pin per actual pin, and carry over its footprint. Previously
    # this was hard-coded to a 2-pin stub with an empty (lib_symbols) and no
    # footprint, which produced broken symbols that did not net out to a PCB.
    resolved = _resolve_lib_symbol(doc, lib_id)
    if resolved and resolved["pins"]:
        pin_numbers = resolved["pins"]
        footprint = resolved["footprint"]
        geometry = resolved["geometry"]
        # Honor the symbol's own BOM/board attributes so power symbols, mounting
        # holes, fiducials, etc. aren't force-added to the BOM / board.
        in_bom = resolved["in_bom"]
        on_board = resolved["on_board"]
    else:
        # Fallback for an unresolvable symbol: keep the legacy 2-pin stub.
        pin_numbers = ["1", "2"]
        footprint = ""
        geometry = {}
        in_bom = "yes"
        on_board = "yes"

    pins_text = " ".join(f'(pin "{n}" (uuid "{_uuid.uuid4()}"))' for n in pin_numbers)

    # quote_if_needed escapes special characters like quotes and backslashes
    quoted_lib_id = _quote_if_needed(lib_id)
    quoted_reference = _quote_if_needed(reference)
    quoted_value = _quote_if_needed(value)
    quoted_footprint = _quote_if_needed(footprint)

    sym_text = (
        f"(symbol (lib_id {quoted_lib_id}) (at {x} {y} {angle}) (unit {unit})"
        f" (in_bom {in_bom}) (on_board {on_board})"
        f' (uuid "{sym_uuid}")'
        f' (property "Reference" {quoted_reference} (at {x} {y - 2.54} 0)'
        f" (effects (font (size 1.27 1.27))))"
        f' (property "Value" {quoted_value} (at {x} {y + 2.54} 0)'
        f" (effects (font (size 1.27 1.27))))"
        f' (property "Footprint" {quoted_footprint} (at {x} {y} 0)'
        f" (effects (font (size 1.27 1.27)) hide))"
        f' (property "Datasheet" "~" (at {x} {y} 0)'
        f" (effects (font (size 1.27 1.27)) hide))"
        f" {pins_text} {instances_text})"
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

    # Absolute schematic coords of each pin (for landing wires/labels).
    pin_positions = _instance_pin_positions(doc, sym_node, geometry)

    result = {
        "status": "added",
        "reference": reference,
        "uuid": sym_uuid,
        "position": {"x": x, "y": y},
        "pin_count": len(pin_numbers),
        "resolved": bool(resolved and resolved["pins"]),
        "footprint": footprint,
        "pins": pin_positions,
    }
    # On a reused sheet the symbol exists once per placement, each with its own
    # reference; surface them so the caller knows what was auto-assigned.
    if len(assigned_refs) > 1:
        result["instance_references"] = assigned_refs
    return result


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
        f" (stroke (width 0) (type default))"
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
    label_text = (
        f'(label "{name}" (at {x} {y} {angle})'
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
    name="get_pin_position",
    description=(
        "Get the absolute schematic coordinate (mm) of a placed symbol's pin, so a "
        "wire or net label can be landed on it for connectivity."
    ),
    parameters={
        "reference": {"type": "string", "description": "Reference designator (e.g., 'U1')."},
        "pin": {"type": "string", "description": "Pin number (e.g., '1')."},
    },
    handler=_get_pin_position_handler,
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


# ── Create / Netlist handlers ───────────────────────────────────────


def _create_schematic_handler(
    path: str,
    paper: str = "A4",
) -> dict[str, Any]:
    """Create a new empty schematic file.

    Args:
        path: Path for the new .kicad_sch file.
        paper: Paper size ('A4', 'A3', 'letter', etc.). Default: 'A4'.
    """
    from pathlib import Path as P

    # Validate paper size - KiCad uses specific paper sizes
    VALID_PAPERS = frozenset(
        {
            "A4",
            "A3",
            "A2",
            "A1",
            "A0",
            "Letter",
            "Legal",
            "Tabloid",
            "Ledger",
        }
    )
    if paper not in VALID_PAPERS:
        return {
            "error": f"Invalid paper size: {paper!r}. "
            f"Valid options: {', '.join(sorted(VALID_PAPERS))}"
        }

    from ..backends.format_version import detect_format_stamps

    stamps = detect_format_stamps()
    sch_uuid = str(_uuid.uuid4())
    sch_text = (
        f'(kicad_sch (version {stamps.sch_version}) (generator "kicad_mcp")'
        f' (generator_version "{stamps.generator_version}")\n'
        f'  (uuid "{sch_uuid}")\n'
        f'  (paper "{paper}")\n'
        f"  (lib_symbols)\n"
        f'  (sheet_instances (path "/" (page "1")))\n'
        f")"
    )
    out = P(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(sch_text, encoding="utf-8")

    return {
        "status": "created",
        "path": str(out),
        "paper": paper,
        "uuid": sch_uuid,
    }


def _generate_netlist_handler(
    output_path: str,
) -> dict[str, Any]:
    """Generate a netlist from the currently loaded schematic.

    Extracts symbols and their pin connections, writes KiCad netlist format.

    Args:
        output_path: Path for the output netlist file.
    """
    from pathlib import Path as P

    from .. import schematic_state

    doc = schematic_state.get_document()
    symbols = schematic_state.get_symbols()

    # Build components list
    components = []
    for sym in symbols:
        lib_name = sym.lib_id.split(":")[0] if ":" in sym.lib_id else sym.lib_id
        part_name = sym.lib_id.split(":")[-1] if ":" in sym.lib_id else sym.lib_id
        components.append(
            f"    (comp (ref {_quote_if_needed(sym.reference)})\n"
            f"      (value {_quote_if_needed(sym.value)})\n"
            f"      (libsource (lib {_quote_if_needed(lib_name)})"
            f" (part {_quote_if_needed(part_name)})))"
        )

    # Build nets from labels
    nets = []
    net_num = 1
    label_names: set[str] = set()
    for child in doc.root.children:
        if child.name == "label":
            name = child.first_value
            if name and name not in label_names:
                label_names.add(name)
                nets.append(f"    (net (code {net_num}) (name {_quote_if_needed(name)}))")
                net_num += 1

    nl_text = (
        f"(export (version D)\n"
        f"  (design\n"
        f'    (source "{doc.path}")\n'
        f'    (tool "kicad_mcp")\n'
        f"  )\n"
        f"  (components\n" + "\n".join(components) + "\n  )\n"
        "  (nets\n" + "\n".join(nets) + "\n  )\n"
        ")"
    )

    out = P(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(nl_text, encoding="utf-8")

    return {
        "status": "generated",
        "path": str(out),
        "component_count": len(symbols),
        "net_count": len(nets),
    }


register_tool(
    name="create_schematic",
    description="Create a new empty KiCad schematic file.",
    parameters={
        "path": {"type": "string", "description": "Path for the .kicad_sch file."},
        "paper": {"type": "string", "description": "Paper size (e.g., 'A4'). Default: 'A4'."},
    },
    handler=_create_schematic_handler,
    category="schematic",
)

register_tool(
    name="generate_netlist",
    description="Generate a netlist from the loaded schematic.",
    parameters={
        "output_path": {"type": "string", "description": "Output netlist file path."},
    },
    handler=_generate_netlist_handler,
    category="schematic",
)


# ── Edit / connectivity / ERC / export ──────────────────────────────


def _replace_at(node: SExp, x: float, y: float, angle: float | None = None) -> None:
    """Replace a node's (at ...) with fresh coordinates (keeps angle if None)."""
    at = node.get("at")
    if at is None:
        return
    if angle is None:
        vals = at.atom_values
        angle = float(vals[2]) if len(vals) > 2 else 0.0
    idx = node.children.index(at)
    node.children[idx] = sexp_parse(f"(at {x} {y} {angle})")


def _move_symbol_handler(reference: str, x: float, y: float) -> dict[str, Any]:
    """Move a placed symbol to a new position (its labels/properties move with it).

    Args:
        reference: Reference designator (e.g., "U1").
        x: New X position (mm).
        y: New Y position (mm).
    """
    from .. import schematic_state

    doc = schematic_state.get_document()
    node = _find_instance_node(doc, reference)
    if node is None:
        return {"error": f"Symbol '{reference}' not found"}
    at = node.get("at")
    vals = at.atom_values if at else []
    try:
        dx = x - float(vals[0])
        dy = y - float(vals[1])
    except (ValueError, IndexError):
        return {"error": f"Symbol '{reference}' has no valid position"}
    _replace_at(node, x, y)
    # Shift each property's own position by the same delta.
    for prop in node.find_all("property"):
        pat = prop.get("at")
        if pat is None:
            continue
        pv = pat.atom_values
        try:
            pa = float(pv[2]) if len(pv) > 2 else 0.0
            _replace_at(prop, float(pv[0]) + dx, float(pv[1]) + dy, pa)
        except (ValueError, IndexError):
            continue
    schematic_state.refresh()
    return {"status": "moved", "reference": reference, "position": {"x": x, "y": y}}


def _rotate_symbol_handler(reference: str, angle: float) -> dict[str, Any]:
    """Rotate a placed symbol to an absolute angle (0/90/180/270 degrees).

    Args:
        reference: Reference designator (e.g., "U1").
        angle: Rotation in degrees.
    """
    from .. import schematic_state

    doc = schematic_state.get_document()
    node = _find_instance_node(doc, reference)
    if node is None:
        return {"error": f"Symbol '{reference}' not found"}
    at = node.get("at")
    vals = at.atom_values if at else []
    try:
        _replace_at(node, float(vals[0]), float(vals[1]), float(angle))
    except (ValueError, IndexError):
        return {"error": f"Symbol '{reference}' has no valid position"}
    schematic_state.refresh()
    return {"status": "rotated", "reference": reference, "angle": angle}


def _edit_sch_symbol_handler(reference: str, properties: dict[str, str]) -> dict[str, Any]:
    """Edit a placed symbol's property values (e.g., Value, Footprint).

    Args:
        reference: Reference designator (e.g., "U1").
        properties: Map of property name -> new value (e.g., {"Value": "22k"}).
    """
    from .. import schematic_state

    doc = schematic_state.get_document()
    node = _find_instance_node(doc, reference)
    if node is None:
        return {"error": f"Symbol '{reference}' not found"}

    updated: list[str] = []
    for prop in node.find_all("property"):
        pname = prop.first_value
        if pname in properties:
            atoms = [c for c in prop.children if c.is_atom]
            if len(atoms) >= 2:
                new_val = str(properties[pname])
                atoms[1].value = new_val
                # KiCad always quotes property field values; force quotes (the value
                # may lack special chars, where _quote_if_needed wouldn't quote).
                escaped = new_val.replace("\\", "\\\\").replace('"', '\\"')
                atoms[1]._original_str = f'"{escaped}"'
                updated.append(pname)
    if not updated:
        return {"error": f"No matching properties on {reference}: {sorted(properties)}"}
    schematic_state.refresh()
    return {"status": "edited", "reference": reference, "updated": updated}


def _add_junction_handler(x: float, y: float) -> dict[str, Any]:
    """Add a wire junction dot at a point where wires cross/meet.

    Args:
        x: X position (mm).
        y: Y position (mm).
    """
    from .. import schematic_state

    doc = schematic_state.get_document()
    node = sexp_parse(
        f'(junction (at {x} {y}) (diameter 0) (color 0 0 0 0) (uuid "{_uuid.uuid4()}"))'
    )
    _insert_before_sheet_instances(doc, node)
    schematic_state.refresh()
    return {"status": "added", "type": "junction", "position": {"x": x, "y": y}}


def _add_no_connect_handler(x: float, y: float) -> dict[str, Any]:
    """Add a no-connect (X) flag on an unused pin to keep ERC clean.

    Args:
        x: X position of the pin (mm).
        y: Y position of the pin (mm).
    """
    from .. import schematic_state

    doc = schematic_state.get_document()
    node = sexp_parse(f'(no_connect (at {x} {y}) (uuid "{_uuid.uuid4()}"))')
    _insert_before_sheet_instances(doc, node)
    schematic_state.refresh()
    return {"status": "added", "type": "no_connect", "position": {"x": x, "y": y}}


def _insert_before_sheet_instances(doc: Document, node: SExp) -> None:
    """Insert a node before (sheet_instances) if present, else append."""
    insert_idx = len(doc.root.children)
    for i, child in enumerate(doc.root.children):
        if child.name == "sheet_instances":
            insert_idx = i
            break
    doc.root.children.insert(insert_idx, node)


# ── Delete handlers for non-symbol items ────────────────────────────
#
# add_label/add_wire/add_junction/add_no_connect previously had no remove
# counterpart (only delete_symbol existed), so a mis-placed label or stray
# no-connect could only be removed by hand-editing the file. These close that
# gap. Coordinates are matched with a small tolerance because the schematic
# stores them to ~4 decimal places.

_COORD_TOL = 0.01  # mm


def _coord_eq(a: float, b: float) -> bool:
    """Compare two schematic coordinates within grid tolerance."""
    return abs(a - b) <= _COORD_TOL


def _at_xy(node: SExp) -> tuple[float, float] | None:
    """Return (x, y) from a node's ``(at ...)``, or None if absent/invalid."""
    at = node.get("at")
    if at is None:
        return None
    av = at.atom_values
    try:
        return float(av[0]), float(av[1])
    except (ValueError, IndexError):
        return None


def _delete_root_matches(doc: Document, predicate: Callable[[SExp], bool]) -> int:
    """Remove every top-level child for which ``predicate(child)`` is true.

    Returns the number removed. Iterates a snapshot so removal is safe.
    """
    removed = 0
    for child in list(doc.root.children):
        if predicate(child):
            doc.root.children.remove(child)
            removed += 1
    return removed


def _delete_label_handler(name: str, x: float, y: float) -> dict[str, Any]:
    """Delete a net label by name at a coordinate.

    Args:
        name: Label name (must match exactly, e.g. "VCC").
        x: X position (mm).
        y: Y position (mm).
    """
    from .. import schematic_state

    doc = schematic_state.get_document()

    def _match(c: SExp) -> bool:
        if c.name != "label" or c.first_value != name:
            return False
        xy = _at_xy(c)
        return xy is not None and _coord_eq(xy[0], x) and _coord_eq(xy[1], y)

    count = _delete_root_matches(doc, _match)
    if count == 0:
        return {"error": f"No label '{name}' at ({x}, {y})"}
    schematic_state.refresh()
    return {
        "status": "deleted",
        "type": "label",
        "name": name,
        "position": {"x": x, "y": y},
        "count": count,
    }


def _delete_wire_handler(
    start_x: float, start_y: float, end_x: float, end_y: float
) -> dict[str, Any]:
    """Delete a wire between two endpoints (matched in either direction).

    Args:
        start_x: Start X (mm).
        start_y: Start Y (mm).
        end_x: End X (mm).
        end_y: End Y (mm).
    """
    from .. import schematic_state

    doc = schematic_state.get_document()
    s = (start_x, start_y)
    e = (end_x, end_y)

    def _endpoints(c: SExp) -> tuple[tuple[float, float], tuple[float, float]] | None:
        pts = c.get("pts")
        if pts is None:
            return None
        xys = [g for g in pts.children if g.name == "xy"]
        if len(xys) < 2:
            return None
        try:
            a = (float(xys[0].atom_values[0]), float(xys[0].atom_values[1]))
            b = (float(xys[1].atom_values[0]), float(xys[1].atom_values[1]))
        except (ValueError, IndexError):
            return None
        return a, b

    def _pt_eq(p: tuple[float, float], q: tuple[float, float]) -> bool:
        return _coord_eq(p[0], q[0]) and _coord_eq(p[1], q[1])

    def _match(c: SExp) -> bool:
        if c.name != "wire":
            return False
        ends = _endpoints(c)
        if ends is None:
            return False
        a, b = ends
        return (_pt_eq(a, s) and _pt_eq(b, e)) or (_pt_eq(a, e) and _pt_eq(b, s))

    count = _delete_root_matches(doc, _match)
    if count == 0:
        return {"error": f"No wire between ({start_x}, {start_y}) and ({end_x}, {end_y})"}
    schematic_state.refresh()
    return {
        "status": "deleted",
        "type": "wire",
        "start": {"x": start_x, "y": start_y},
        "end": {"x": end_x, "y": end_y},
        "count": count,
    }


def _delete_at_point_handler(kind: str, x: float, y: float) -> dict[str, Any]:
    """Delete a junction or no_connect at a coordinate (shared by both tools)."""
    from .. import schematic_state

    doc = schematic_state.get_document()

    def _match(c: SExp) -> bool:
        if c.name != kind:
            return False
        xy = _at_xy(c)
        return xy is not None and _coord_eq(xy[0], x) and _coord_eq(xy[1], y)

    count = _delete_root_matches(doc, _match)
    if count == 0:
        return {"error": f"No {kind} at ({x}, {y})"}
    schematic_state.refresh()
    return {"status": "deleted", "type": kind, "position": {"x": x, "y": y}, "count": count}


def _delete_junction_handler(x: float, y: float) -> dict[str, Any]:
    """Delete a wire junction dot at a coordinate.

    Args:
        x: X position (mm).
        y: Y position (mm).
    """
    return _delete_at_point_handler("junction", x, y)


def _delete_no_connect_handler(x: float, y: float) -> dict[str, Any]:
    """Delete a no-connect (X) flag at a coordinate.

    Args:
        x: X position (mm).
        y: Y position (mm).
    """
    return _delete_at_point_handler("no_connect", x, y)


def _run_erc_handler() -> dict[str, Any]:
    """Run the Electrical Rules Check (ERC) on the current schematic via kicad-cli.

    Reflects in-memory edits (writes a temp copy first). Returns violations.
    """
    import tempfile
    from pathlib import Path as _P

    from .. import schematic_state
    from ..backends.kicad_cli import KiCadCli, KiCadCliError, KiCadCliNotFound

    doc = schematic_state.get_document()
    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found. Install KiCad 8+."}

    fd, tmp = tempfile.mkstemp(suffix=".kicad_sch", prefix="erc_")
    import os as _os

    _os.close(fd)
    try:
        doc.save(tmp)
        result = cli.run_sch_erc(tmp)
    except KiCadCliError as exc:
        return {"error": f"ERC failed: {exc}"}
    finally:
        _P(tmp).unlink(missing_ok=True)
    return result.to_dict()


def _export_schematic_handler(output_path: str, fmt: str) -> dict[str, Any]:
    """Export the schematic to PDF or SVG (reflects in-memory edits)."""
    import tempfile
    from pathlib import Path as _P

    from .. import schematic_state
    from ..backends.kicad_cli import KiCadCli, KiCadCliError, KiCadCliNotFound
    from ..security import SecurityError, get_validator

    try:
        get_validator().validate_output(output_path)
    except SecurityError as exc:
        return {"error": f"Security error: {exc}"}

    doc = schematic_state.get_document()
    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found. Install KiCad 8+."}

    fd, tmp = tempfile.mkstemp(suffix=".kicad_sch", prefix="schexp_")
    import os as _os

    _os.close(fd)
    try:
        doc.save(tmp)
        result = cli.export_sch(tmp, output_path, fmt=fmt)
    except KiCadCliError as exc:
        return {"error": f"{fmt.upper()} export failed: {exc}"}
    finally:
        _P(tmp).unlink(missing_ok=True)
    return result.to_dict()


def _export_schematic_pdf_handler(output_path: str) -> dict[str, Any]:
    """Export the current schematic to PDF.

    Args:
        output_path: Output .pdf path.
    """
    return _export_schematic_handler(output_path, "pdf")


def _export_schematic_svg_handler(output_path: str) -> dict[str, Any]:
    """Export the current schematic to SVG.

    Args:
        output_path: Output .svg path.
    """
    return _export_schematic_handler(output_path, "svg")


register_tool(
    name="move_symbol",
    description="Move a placed schematic symbol to a new position (properties move with it).",
    parameters={
        "reference": {"type": "string", "description": "Reference designator (e.g., 'U1')."},
        "x": {"type": "number", "description": "New X (mm)."},
        "y": {"type": "number", "description": "New Y (mm)."},
    },
    handler=_move_symbol_handler,
    category="schematic",
)

register_tool(
    name="rotate_symbol",
    description="Rotate a placed schematic symbol to an absolute angle (0/90/180/270).",
    parameters={
        "reference": {"type": "string", "description": "Reference designator (e.g., 'U1')."},
        "angle": {"type": "number", "description": "Rotation in degrees."},
    },
    handler=_rotate_symbol_handler,
    category="schematic",
)

register_tool(
    name="edit_sch_symbol",
    description="Edit a placed symbol's property values (Value, Footprint, etc.).",
    parameters={
        "reference": {"type": "string", "description": "Reference designator (e.g., 'U1')."},
        "properties": {
            "type": "object",
            "description": "Property name -> new value, e.g. {'Value': '22k'}.",
        },
    },
    handler=_edit_sch_symbol_handler,
    category="schematic",
)

register_tool(
    name="add_junction",
    description="Add a wire junction dot where wires meet/cross.",
    parameters={
        "x": {"type": "number", "description": "X position (mm)."},
        "y": {"type": "number", "description": "Y position (mm)."},
    },
    handler=_add_junction_handler,
    category="schematic",
)

register_tool(
    name="add_no_connect",
    description="Add a no-connect (X) flag on an unused pin to keep ERC clean.",
    parameters={
        "x": {"type": "number", "description": "Pin X position (mm)."},
        "y": {"type": "number", "description": "Pin Y position (mm)."},
    },
    handler=_add_no_connect_handler,
    category="schematic",
)

register_tool(
    name="delete_label",
    description="Delete a net label by name at a coordinate (mm).",
    parameters={
        "name": {"type": "string", "description": "Label name (e.g., 'VCC')."},
        "x": {"type": "number", "description": "X position (mm)."},
        "y": {"type": "number", "description": "Y position (mm)."},
    },
    handler=_delete_label_handler,
    category="schematic",
)

register_tool(
    name="delete_wire",
    description="Delete a wire between two endpoints (matched in either direction).",
    parameters={
        "start_x": {"type": "number", "description": "Start X (mm)."},
        "start_y": {"type": "number", "description": "Start Y (mm)."},
        "end_x": {"type": "number", "description": "End X (mm)."},
        "end_y": {"type": "number", "description": "End Y (mm)."},
    },
    handler=_delete_wire_handler,
    category="schematic",
)

register_tool(
    name="delete_junction",
    description="Delete a wire junction dot at a coordinate (mm).",
    parameters={
        "x": {"type": "number", "description": "X position (mm)."},
        "y": {"type": "number", "description": "Y position (mm)."},
    },
    handler=_delete_junction_handler,
    category="schematic",
)

register_tool(
    name="delete_no_connect",
    description="Delete a no-connect (X) flag at a coordinate (mm).",
    parameters={
        "x": {"type": "number", "description": "X position (mm)."},
        "y": {"type": "number", "description": "Y position (mm)."},
    },
    handler=_delete_no_connect_handler,
    category="schematic",
)

register_tool(
    name="run_erc",
    description="Run the Electrical Rules Check (ERC) on the schematic via kicad-cli.",
    parameters={},
    handler=_run_erc_handler,
    category="schematic",
)

register_tool(
    name="export_schematic_pdf",
    description="Export the current schematic to PDF.",
    parameters={"output_path": {"type": "string", "description": "Output .pdf path."}},
    handler=_export_schematic_pdf_handler,
    category="schematic",
)

register_tool(
    name="export_schematic_svg",
    description="Export the current schematic to SVG.",
    parameters={"output_path": {"type": "string", "description": "Output .svg path."}},
    handler=_export_schematic_svg_handler,
    category="schematic",
)
