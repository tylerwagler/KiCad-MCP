"""Placement operations: move, rotate, flip, delete, place components."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from ..exceptions import ResourceNotFoundError
from ..security import SecurityError
from ..sexp import SExp
from ..sexp.parser import _quote_if_needed
from ..sexp.parser import parse as sexp_parse
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

    project_dir = Path(session.board_path).parent if session.board_path else None
    mod_path = _resolve_kicad_mod_path(footprint_library, project_dir)
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


def _normalize_legacy_fp_text(fp_node: SExp) -> None:
    """Rewrite legacy ``(fp_text reference|value …)`` as modern ``(property …)``.

    KiCad 6-and-older ``.kicad_mod`` files declare the reference and value with
    ``fp_text``; KiCad migrates these on load, but our parser does not. Without
    this, the reference/value never get stamped and ``find_footprint`` cannot
    locate the placed footprint — so a later net assignment silently skips every
    pad. Converting in place keeps the board in the modern property form.
    """
    legacy_names = {"reference": "Reference", "value": "Value"}
    for node in fp_node.find_all("fp_text"):
        vals = node.atom_values
        if not vals:
            continue
        prop_name = legacy_names.get(vals[0])
        if prop_name is None:
            continue
        # Skip if a modern property of the same kind already exists.
        if any(p.first_value == prop_name for p in fp_node.find_all("property")):
            continue
        node.name = "property"
        # Replace the leading keyword atom ("reference"/"value") with the
        # quoted property name ("Reference"/"Value").
        for i, child in enumerate(node.children):
            if child.is_atom:
                node.children[i] = _make_quoted(prop_name)
                break
        # Modern properties carry a uuid; add one if the legacy node lacked it.
        if node.get("uuid") is None:
            node.children.append(_make_node("uuid", [_make_quoted(str(uuid.uuid4()))]))


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
    _normalize_legacy_fp_text(fp_node)

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


def read_position(session: Session, reference: str) -> dict[str, float]:
    """Read a component's current position and rotation.

    Returns a dict with keys ``x``, ``y``, ``angle``. Raises if not found.
    """
    require_active(session)
    assert session._working_doc is not None

    fp_node = find_footprint(session._working_doc, reference)
    if fp_node is None:
        raise ValueError(f"Component {reference!r} not found")

    at_node = fp_node.get("at")
    vals = at_node.atom_values if at_node else []
    return {
        "x": float(vals[0]) if len(vals) > 0 else 0.0,
        "y": float(vals[1]) if len(vals) > 1 else 0.0,
        "angle": float(vals[2]) if len(vals) > 2 else 0.0,
    }


def apply_duplicate(
    session: Session,
    reference: str,
    new_reference: str,
    x: float,
    y: float,
) -> ChangeRecord:
    """Duplicate an existing component to a new reference at a new position.

    Clones the full footprint (pads, graphics, etc.), assigns a fresh reference
    and regenerated UUIDs, and places it at ``(x, y)``.
    """
    require_active(session)
    assert session._working_doc is not None

    source = find_footprint(session._working_doc, reference)
    if source is None:
        raise ValueError(f"Component {reference!r} not found")

    if find_footprint(session._working_doc, new_reference) is not None:
        raise ValueError(f"Component {new_reference!r} already exists on the board")

    # Deep-copy the source footprint by re-parsing its serialized form.
    fp_node = sexp_parse(source.to_string())

    # Move it to the requested position (preserve rotation if present).
    at_node = fp_node.get("at")
    if at_node is not None and len(at_node.children) >= 2:
        at_node.children[0] = _make_atom(str(x))
        at_node.children[1] = _make_atom(str(y))

    # Regenerate every UUID in the cloned subtree to avoid collisions.
    for uuid_node in fp_node.find_all("uuid"):
        if uuid_node.children:
            uuid_node.children[0] = _make_quoted(str(uuid.uuid4()))

    # Rename the Reference property.
    for prop in fp_node.find_all("property"):
        if prop.first_value == "Reference":
            atom_idx = 0
            for i, child in enumerate(prop.children):
                if child.is_atom:
                    atom_idx += 1
                    if atom_idx == 2:
                        prop.children[i] = _make_quoted(new_reference)
                        break
            break

    session._working_doc.root.children.append(fp_node)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="place_component",
        description=f"Duplicate {reference} as {new_reference} at ({x}, {y})",
        target=new_reference,
        before_snapshot="",
        after_snapshot=fp_node.to_string(),
        applied=True,
    )
    session.changes.append(record)
    return record


def _resolve_kicad_mod_path(footprint_library: str, project_dir: Path | None = None) -> str | None:
    """Resolve a ``library:footprint`` id to a .kicad_mod path.

    Checks the project fp-lib-table first (so ``${KIPRJMOD}`` libraries — the
    project's own footprints — resolve against ``project_dir``), then the
    global/user fp-lib-table. Mirrors the schematic-side symbol resolution.
    """
    if ":" not in footprint_library:
        return None

    lib_name, fp_name = footprint_library.split(":", 1)

    try:
        from ..library import _kicad_env_paths, _parse_lib_table, discover_lib_tables
    except Exception:
        return None

    def _mod_in(entry_uri: str) -> str | None:
        mod_path = Path(entry_uri) / f"{fp_name}.kicad_mod"
        return str(mod_path) if mod_path.exists() else None

    # 1. Project fp-lib-table — expands ${KIPRJMOD} (the project's own libs).
    if project_dir is not None:
        proj_table = project_dir / "fp-lib-table"
        if proj_table.exists():
            try:
                env = _kicad_env_paths()
                env["KIPRJMOD"] = project_dir
                for entry in _parse_lib_table(proj_table, env):
                    if entry.name == lib_name:
                        hit = _mod_in(entry.uri)
                        if hit:
                            return hit
            except Exception:
                pass

    # 2. Global / user fp-lib-table.
    try:
        for entry in discover_lib_tables().get("footprint_libraries", []):
            if entry.name == lib_name:
                hit = _mod_in(entry.uri)
                if hit:
                    return hit
    except Exception:
        return None
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
