"""Placement operations: move, rotate, flip, delete, place components."""

from __future__ import annotations

import uuid
from typing import Any

from ..security import SecurityError
from ..sexp import SExp
from ..sexp.parser import _quote_if_needed, parse as sexp_parse
from ..exceptions import ResourceNotFoundError
from .helpers import find_footprint
from .types import (
    _LAYER_FLIP,
    ChangeRecord,
    Session,
    _make_atom,
    _make_node,
    _make_quoted,
    require_active,
)


def query_move(session: Session, reference: str, x: float, y: float) -> dict[str, Any]:
    """Preview moving a component without applying the change."""
    require_active(session)
    assert session._working_doc is not None

    fp_node = find_footprint(session._working_doc, reference)
    if fp_node is None:
        raise ResourceNotFoundError(
            f"Component {reference!r} not found", resource_type="component", reference=reference
        )

    at_node = fp_node.get("at")
    current_x = float(at_node.atom_values[0]) if at_node and len(at_node.atom_values) > 0 else 0
    current_y = float(at_node.atom_values[1]) if at_node and len(at_node.atom_values) > 1 else 0

    return {
        "operation": "move_component",
        "target": reference,
        "current_position": {"x": current_x, "y": current_y},
        "new_position": {"x": x, "y": y},
        "preview": True,
    }


def apply_move(session: Session, reference: str, x: float, y: float) -> ChangeRecord:
    """Apply a component move and record the change."""
    require_active(session)
    assert session._working_doc is not None

    fp_node = find_footprint(session._working_doc, reference)
    if fp_node is None:
        raise ValueError(f"Component {reference!r} not found")

    at_node = fp_node.get("at")
    before = at_node.to_string() if at_node else "(at 0 0)"

    if at_node is not None and len(at_node.children) >= 2:
        at_node.children[0] = _make_atom(str(x))
        at_node.children[1] = _make_atom(str(y))

    after = at_node.to_string() if at_node else f"(at {x} {y})"

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="move_component",
        description=f"Move {reference} to ({x}, {y})",
        target=reference,
        before_snapshot=before,
        after_snapshot=after,
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_rotate(session: Session, reference: str, angle: float) -> ChangeRecord:
    """Rotate a component to a given angle (degrees)."""
    require_active(session)
    assert session._working_doc is not None

    fp_node = find_footprint(session._working_doc, reference)
    if fp_node is None:
        raise ValueError(f"Component {reference!r} not found")

    at_node = fp_node.get("at")
    before = at_node.to_string() if at_node else "(at 0 0)"

    if at_node is not None:
        vals = at_node.atom_values
        if len(vals) >= 3:
            at_node.children[2] = _make_atom(str(angle))
        elif len(vals) >= 2:
            at_node.children.append(_make_atom(str(angle)))

    after = at_node.to_string() if at_node else f"(at 0 0 {angle})"

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="rotate_component",
        description=f"Rotate {reference} to {angle} degrees",
        target=reference,
        before_snapshot=before,
        after_snapshot=after,
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_flip(session: Session, reference: str) -> ChangeRecord:
    """Flip a component to the opposite side of the board."""
    require_active(session)
    assert session._working_doc is not None

    fp_node = find_footprint(session._working_doc, reference)
    if fp_node is None:
        raise ValueError(f"Component {reference!r} not found")

    before = fp_node.to_string()

    # Flip the footprint layer
    layer_node = fp_node.get("layer")
    if layer_node and layer_node.children:
        old_layer = layer_node.children[0].value or ""
        new_layer = _LAYER_FLIP.get(old_layer, old_layer)
        layer_node.children[0] = _make_quoted(new_layer)

    # Flip layers in all pads
    for pad_node in fp_node.find_all("pad"):
        layers_node = pad_node.get("layers")
        if layers_node:
            for i, child in enumerate(layers_node.children):
                if child.is_atom and child.value:
                    flipped = _LAYER_FLIP.get(child.value, child.value)
                    if flipped != child.value:
                        layers_node.children[i] = _make_quoted(flipped)

    # Flip layers on graphic items
    for gfx_name in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_text"):
        for gfx in fp_node.find_all(gfx_name):
            gfx_layer = gfx.get("layer")
            if gfx_layer and gfx_layer.children:
                old_val = gfx_layer.children[0].value or ""
                new_val = _LAYER_FLIP.get(old_val, old_val)
                if new_val != old_val:
                    gfx_layer.children[0] = _make_quoted(new_val)

    # Flip layers on properties
    for prop in fp_node.find_all("property"):
        prop_layer = prop.get("layer")
        if prop_layer and prop_layer.children:
            old_val = prop_layer.children[0].value or ""
            new_val = _LAYER_FLIP.get(old_val, old_val)
            if new_val != old_val:
                prop_layer.children[0] = _make_quoted(new_val)

    after = fp_node.to_string()

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="flip_component",
        description=f"Flip {reference} to opposite side",
        target=reference,
        before_snapshot=before,
        after_snapshot=after,
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_delete(session: Session, reference: str) -> ChangeRecord:
    """Delete a component from the board."""
    require_active(session)
    assert session._working_doc is not None

    fp_node = find_footprint(session._working_doc, reference)
    if fp_node is None:
        raise ValueError(f"Component {reference!r} not found")

    before = fp_node.to_string()
    session._working_doc.root.children.remove(fp_node)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="delete_component",
        description=f"Delete component {reference}",
        target=reference,
        before_snapshot=before,
        after_snapshot="",
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_place(
    session: Session,
    footprint_library: str,
    reference: str,
    value: str,
    x: float,
    y: float,
    layer: str = "F.Cu",
) -> ChangeRecord:
    """Place a new component on the board."""
    require_active(session)
    assert session._working_doc is not None

    existing = find_footprint(session._working_doc, reference)
    if existing is not None:
        raise ValueError(f"Component {reference!r} already exists on the board")

    mod_path = _resolve_kicad_mod_path(footprint_library)
    if mod_path is not None:
        return place_from_kicad_mod(session, mod_path, reference, value, x, y, layer)

    fp_node = _build_footprint_node(footprint_library, reference, value, x, y, layer)
    session._working_doc.root.children.append(fp_node)

    after = fp_node.to_string()

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="place_component",
        description=f"Place {reference} ({footprint_library}) at ({x}, {y}) on {layer}",
        target=reference,
        before_snapshot="",
        after_snapshot=after,
        applied=True,
    )
    session.changes.append(record)
    return record


def place_from_kicad_mod(
    session: Session,
    kicad_mod_path: str,
    reference: str,
    value: str,
    x: float,
    y: float,
    layer: str = "F.Cu",
) -> ChangeRecord:
    """Place a component by reading its footprint from a .kicad_mod file."""
    require_active(session)
    assert session._working_doc is not None

    existing = find_footprint(session._working_doc, reference)
    if existing is not None:
        raise ValueError(f"Component {reference!r} already exists on the board")

    from pathlib import Path

    mod_path = Path(kicad_mod_path)
    if not mod_path.exists():
        raise FileNotFoundError(f"Footprint file not found: {kicad_mod_path}")

    raw = mod_path.read_text(encoding="utf-8")
    fp_node = sexp_parse(raw)

    at_node = fp_node.get("at")
    if at_node is None:
        at_node = _make_node("at", [_make_atom(str(x)), _make_atom(str(y))])
        insert_idx = 0
        for i, child in enumerate(fp_node.children):
            if child.is_atom:
                insert_idx = i + 1
            else:
                break
        fp_node.children.insert(insert_idx, at_node)
    else:
        at_node.children = [_make_atom(str(x)), _make_atom(str(y))]

    layer_node = fp_node.get("layer")
    if layer_node and layer_node.children:
        layer_node.children[0] = _make_quoted(layer)

    for prop in fp_node.find_all("property"):
        if prop.first_value == "Reference":
            vals = prop.atom_values
            if len(vals) > 1:
                atom_idx = 0
                for i, child in enumerate(prop.children):
                    if child.is_atom:
                        atom_idx += 1
                        if atom_idx == 2:
                            prop.children[i] = _make_quoted(reference)
                            break
        elif prop.first_value == "Value":
            vals = prop.atom_values
            if len(vals) > 1:
                atom_idx = 0
                for i, child in enumerate(prop.children):
                    if child.is_atom:
                        atom_idx += 1
                        if atom_idx == 2:
                            prop.children[i] = _make_quoted(value)
                            break

    uuid_node = fp_node.get("uuid")
    new_uuid = str(uuid.uuid4())
    if uuid_node and uuid_node.children:
        uuid_node.children[0] = _make_quoted(new_uuid)

    session._working_doc.root.children.append(fp_node)

    after = fp_node.to_string()
    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="place_component",
        description=f"Place {reference} from {mod_path.name} at ({x}, {y}) on {layer}",
        target=reference,
        before_snapshot="",
        after_snapshot=after,
        applied=True,
    )
    session.changes.append(record)
    return record


def _resolve_kicad_mod_path(footprint_library: str) -> str | None:
    """Try to resolve a library:footprint identifier to a .kicad_mod path."""
    if ":" not in footprint_library:
        return None

    lib_name, fp_name = footprint_library.split(":", 1)

    try:
        from ..library import discover_lib_tables
    except Exception:
        return None

    try:
        tables = discover_lib_tables()
    except Exception:
        return None

    from pathlib import Path

    for entry in tables.get("footprint_libraries", []):
        if entry.name == lib_name:
            lib_dir = Path(entry.uri)
            mod_path = lib_dir / f"{fp_name}.kicad_mod"
            if mod_path.exists():
                return str(mod_path)
    return None


def _build_footprint_node(
    library: str,
    reference: str,
    value: str,
    x: float,
    y: float,
    layer: str,
) -> SExp:
    """Build a minimal footprint S-expression node (skeleton fallback)."""
    # Validate inputs to prevent S-expression injection
    if not library:
        raise SecurityError("Library name cannot be empty")
    if not reference:
        raise SecurityError("Reference cannot be empty")
    if not value:
        raise SecurityError("Value cannot be empty")
    if not layer:
        raise SecurityError("Layer cannot be empty")

    new_uuid = str(uuid.uuid4())
    # Use _quote_if_needed to escape special characters in strings
    sexp_text = (
        f"(footprint {_quote_if_needed(library)}"
        f" (layer {_quote_if_needed(layer)})"
        f' (uuid "{new_uuid}")'
        f" (at {x} {y})"
        f' (property "Reference" {_quote_if_needed(reference)}'
        f' (at 0 -1.5 0) (layer {_quote_if_needed(layer)}) (uuid "{uuid.uuid4()}")'
        f" (effects (font (size 1 1) (thickness 0.15))))"
        f' (property "Value" {_quote_if_needed(value)}'
        f' (at 0 1.5 0) (layer "F.Fab") (uuid "{uuid.uuid4()}")'
        f" (effects (font (size 1 1) (thickness 0.15))))"
        f" (attr smd) (embedded_fonts no))"
    )
    return sexp_parse(sexp_text)
