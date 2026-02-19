"""Board setup operations: size, outline, mounting holes, text, design rules, etc."""

from __future__ import annotations

import uuid

from ..sexp.parser import parse as sexp_parse
from .helpers import find_footprint
from .types import (
    ChangeRecord,
    Session,
    _make_atom,
    _make_node,
    _make_quoted,
    _normalize_layer,
    require_active,
)

# Valid KiCad 9 setup keys that accept numeric design-rule values.
_VALID_SETUP_RULES: frozenset[str] = frozenset(
    {
        "pad_to_mask_clearance",
        "solder_mask_min_width",
        "pad_to_paste_clearance",
        "pad_to_paste_clearance_ratio",
    }
)

# Friendly aliases for the valid setup keys.
_RULE_ALIASES: dict[str, str] = {
    "min_clearance": "pad_to_mask_clearance",
    "mask_clearance": "pad_to_mask_clearance",
    "mask_min_width": "solder_mask_min_width",
    "paste_clearance": "pad_to_paste_clearance",
    "paste_clearance_ratio": "pad_to_paste_clearance_ratio",
}

# Rules that callers commonly attempt but belong in .kicad_dru.
_DRU_ONLY_RULES: frozenset[str] = frozenset(
    {
        "min_track_width",
        "min_via_diameter",
        "min_via_drill",
        "min_microvia_diameter",
        "min_microvia_drill",
        "min_through_hole_diameter",
        "clearance",
    }
)


def apply_set_board_size(session: Session, width: float, height: float) -> ChangeRecord:
    """Set the board size by creating/replacing Edge.Cuts outline as a rectangle."""
    require_active(session)
    assert session._working_doc is not None

    before_lines = []
    to_remove = []
    for child in session._working_doc.root.children:
        if child.name in ("gr_line", "gr_rect"):
            layer_node = child.get("layer")
            if layer_node and layer_node.first_value == "Edge.Cuts":
                before_lines.append(child.to_string())
                to_remove.append(child)
    for node in to_remove:
        session._working_doc.root.children.remove(node)

    lines = [
        (0, 0, width, 0),
        (width, 0, width, height),
        (width, height, 0, height),
        (0, height, 0, 0),
    ]
    after_lines = []
    for x1, y1, x2, y2 in lines:
        line_uuid = str(uuid.uuid4())
        line_text = (
            f"(gr_line (start {x1} {y1}) (end {x2} {y2})"
            f" (stroke (width 0.05) (type default))"
            f' (layer "Edge.Cuts") (uuid "{line_uuid}"))'
        )
        line_node = sexp_parse(line_text)
        session._working_doc.root.children.append(line_node)
        after_lines.append(line_node.to_string())

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="set_board_size",
        description=f"Set board size to {width}x{height}mm",
        target="Edge.Cuts",
        before_snapshot="\n".join(before_lines),
        after_snapshot="\n".join(after_lines),
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_add_board_outline(session: Session, points: list[tuple[float, float]]) -> ChangeRecord:
    """Replace board outline with segments on Edge.Cuts layer."""
    require_active(session)
    assert session._working_doc is not None

    if len(points) < 3:
        raise ValueError("Board outline requires at least 3 points")

    before_lines: list[str] = []
    to_remove = []
    for child in session._working_doc.root.children:
        if child.name in ("gr_line", "gr_rect"):
            layer_node = child.get("layer")
            if layer_node and layer_node.first_value == "Edge.Cuts":
                before_lines.append(child.to_string())
                to_remove.append(child)
    for node in to_remove:
        session._working_doc.root.children.remove(node)

    after_lines = []
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        line_uuid = str(uuid.uuid4())
        line_text = (
            f"(gr_line (start {x1} {y1}) (end {x2} {y2})"
            f" (stroke (width 0.05) (type default))"
            f' (layer "Edge.Cuts") (uuid "{line_uuid}"))'
        )
        line_node = sexp_parse(line_text)
        session._working_doc.root.children.append(line_node)
        after_lines.append(line_node.to_string())

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="add_board_outline",
        description=f"Set board outline with {len(points)} points",
        target="Edge.Cuts",
        before_snapshot="\n".join(before_lines),
        after_snapshot="\n".join(after_lines),
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_add_mounting_hole(
    session: Session,
    x: float,
    y: float,
    drill: float = 3.2,
    pad_dia: float = 6.0,
) -> ChangeRecord:
    """Insert a mounting hole footprint at the given position."""
    require_active(session)
    assert session._working_doc is not None

    hole_uuid = str(uuid.uuid4())
    ref_uuid = str(uuid.uuid4())
    val_uuid = str(uuid.uuid4())
    fp_text = (
        f'(footprint "MountingHole:MountingHole_{drill}mm"'
        f' (layer "F.Cu") (uuid "{hole_uuid}") (at {x} {y})'
        f' (property "Reference" "H1"'
        f' (at 0 -{pad_dia / 2 + 1} 0) (layer "F.SilkS") (uuid "{ref_uuid}")'
        f" (effects (font (size 1 1) (thickness 0.15))))"
        f' (property "Value" "MountingHole"'
        f' (at 0 {pad_dia / 2 + 1} 0) (layer "F.Fab") (uuid "{val_uuid}")'
        f" (effects (font (size 1 1) (thickness 0.15))))"
        f' (pad "" np_thru_hole circle (at 0 0)'
        f" (size {pad_dia} {pad_dia}) (drill {drill})"
        f' (layers "*.Cu" "*.Mask")))'
    )
    fp_node = sexp_parse(fp_text)
    session._working_doc.root.children.append(fp_node)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="add_mounting_hole",
        description=f"Add mounting hole at ({x}, {y}) drill={drill}mm",
        target=f"mounting_hole:{hole_uuid[:8]}",
        before_snapshot="",
        after_snapshot=fp_node.to_string(),
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_add_board_text(
    session: Session,
    text: str,
    x: float,
    y: float,
    layer: str = "F.SilkS",
    size: float = 1.0,
    angle: float = 0,
) -> ChangeRecord:
    """Add a text element to the board."""
    require_active(session)
    assert session._working_doc is not None

    layer = _normalize_layer(layer)

    text_uuid = str(uuid.uuid4())
    angle_str = f" {angle}" if angle != 0 else ""
    thickness = size * 0.15
    text_sexp = (
        f'(gr_text "{text}" (at {x} {y}{angle_str})'
        f' (layer "{layer}") (uuid "{text_uuid}")'
        f" (effects (font (size {size} {size}) (thickness {thickness}))))"
    )
    text_node = sexp_parse(text_sexp)
    session._working_doc.root.children.append(text_node)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="add_board_text",
        description=f"Add text '{text}' at ({x}, {y}) on {layer}",
        target=f"text:{text_uuid[:8]}",
        before_snapshot="",
        after_snapshot=text_node.to_string(),
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_set_design_rules(session: Session, rules: dict[str, float]) -> ChangeRecord:
    """Modify design rules in the board setup section."""
    require_active(session)
    assert session._working_doc is not None

    setup_node = session._working_doc.root.get("setup")
    if setup_node is None:
        raise ValueError("Board has no setup section")

    resolved: list[tuple[str, float]] = []
    for rule_name, value in rules.items():
        sexp_name = _RULE_ALIASES.get(rule_name, rule_name)
        if sexp_name in _DRU_ONLY_RULES:
            raise ValueError(
                f"'{rule_name}' cannot be set in the board setup section. "
                f"In KiCad 9 this rule belongs in the .kicad_dru "
                f"(design rules) file. Valid setup keys: "
                f"{sorted(_VALID_SETUP_RULES)}"
            )
        if sexp_name not in _VALID_SETUP_RULES:
            raise ValueError(
                f"Unknown design rule '{rule_name}'. "
                f"Valid setup keys: {sorted(_VALID_SETUP_RULES)}. "
                f"Aliases: {sorted(_RULE_ALIASES.keys())}"
            )
        resolved.append((sexp_name, value))

    before = setup_node.to_string()

    for sexp_name, value in resolved:
        existing = setup_node.get(sexp_name)
        if existing is not None and existing.children:
            existing.children[0] = _make_atom(str(value))
        else:
            new_node = sexp_parse(f"({sexp_name} {value})")
            setup_node.children.append(new_node)

    after = setup_node.to_string()

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="set_design_rules",
        description=f"Set design rules: {list(rules.keys())}",
        target="setup",
        before_snapshot=before,
        after_snapshot=after,
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_edit_component(
    session: Session, reference: str, properties: dict[str, str]
) -> ChangeRecord:
    """Update property values on an existing footprint."""
    require_active(session)
    assert session._working_doc is not None

    fp_node = find_footprint(session._working_doc, reference)
    if fp_node is None:
        raise ValueError(f"Component {reference!r} not found")

    before = fp_node.to_string()

    for prop_name, prop_value in properties.items():
        found = False
        for prop in fp_node.find_all("property"):
            if prop.first_value == prop_name:
                atom_idx = 0
                for i, child in enumerate(prop.children):
                    if child.is_atom:
                        atom_idx += 1
                        if atom_idx == 2:
                            prop.children[i] = _make_quoted(prop_value)
                            found = True
                            break
                break
        if not found:
            prop_uuid = str(uuid.uuid4())
            prop_text = (
                f'(property "{prop_name}" "{prop_value}"'
                f' (at 0 0 0) (layer "F.Fab") (uuid "{prop_uuid}")'
                f" (effects (font (size 1 1) (thickness 0.15)) hide))"
            )
            fp_node.children.append(sexp_parse(prop_text))

    after = fp_node.to_string()

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="edit_component",
        description=f"Edit {reference} properties: {list(properties.keys())}",
        target=reference,
        before_snapshot=before,
        after_snapshot=after,
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_replace_component(
    session: Session, reference: str, new_library: str, new_value: str
) -> ChangeRecord:
    """Replace a component with a different footprint, keeping position."""
    require_active(session)
    assert session._working_doc is not None

    fp_node = find_footprint(session._working_doc, reference)
    if fp_node is None:
        raise ValueError(f"Component {reference!r} not found")

    at_node = fp_node.get("at")
    x = float(at_node.atom_values[0]) if at_node and at_node.atom_values else 0
    y = float(at_node.atom_values[1]) if at_node and len(at_node.atom_values) > 1 else 0
    layer_node = fp_node.get("layer")
    layer = layer_node.first_value if layer_node else "F.Cu"

    before = fp_node.to_string()
    session._working_doc.root.children.remove(fp_node)

    from .placement_ops import _build_footprint_node, _resolve_kicad_mod_path

    mod_path = _resolve_kicad_mod_path(new_library)
    if mod_path is not None:
        from pathlib import Path

        raw = Path(mod_path).read_text(encoding="utf-8")
        new_fp = sexp_parse(raw)

        new_at = new_fp.get("at")
        if new_at is None:
            new_at = _make_node("at", [_make_atom(str(x)), _make_atom(str(y))])
            new_fp.children.insert(0, new_at)
        else:
            new_at.children = [_make_atom(str(x)), _make_atom(str(y))]

        layer_nd = new_fp.get("layer")
        if layer_nd and layer_nd.children:
            layer_nd.children[0] = _make_quoted(layer)

        for prop in new_fp.find_all("property"):
            if prop.first_value == "Reference":
                atom_idx = 0
                for i, child in enumerate(prop.children):
                    if child.is_atom:
                        atom_idx += 1
                        if atom_idx == 2:
                            prop.children[i] = _make_quoted(reference)
                            break
            elif prop.first_value == "Value":
                atom_idx = 0
                for i, child in enumerate(prop.children):
                    if child.is_atom:
                        atom_idx += 1
                        if atom_idx == 2:
                            prop.children[i] = _make_quoted(new_value)
                            break

        uuid_node = new_fp.get("uuid")
        new_uuid = str(uuid.uuid4())
        if uuid_node and uuid_node.children:
            uuid_node.children[0] = _make_quoted(new_uuid)
    else:
        new_fp = _build_footprint_node(new_library, reference, new_value, x, y, layer)

    session._working_doc.root.children.append(new_fp)

    after = new_fp.to_string()

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="replace_component",
        description=f"Replace {reference} with {new_library} ({new_value})",
        target=reference,
        before_snapshot=before,
        after_snapshot=after,
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_add_net_class(
    session: Session,
    name: str,
    clearance: float = 0.2,
    trace_width: float = 0.25,
    via_dia: float = 0.8,
    via_drill: float = 0.4,
    nets: list[str] | None = None,
) -> ChangeRecord:
    """Add a net class definition to the board."""
    require_active(session)
    assert session._working_doc is not None

    nets_str = ""
    if nets:
        nets_str = " ".join(f'(add_net "{n}")' for n in nets)
        nets_str = " " + nets_str

    nc_uuid = str(uuid.uuid4())
    nc_text = (
        f'(net_class "{name}" ""'
        f" (clearance {clearance}) (trace_width {trace_width})"
        f" (via_dia {via_dia}) (via_drill {via_drill})"
        f' (uuid "{nc_uuid}"){nets_str})'
    )
    nc_node = sexp_parse(nc_text)

    setup_node = session._working_doc.root.get("setup")
    if setup_node is not None:
        setup_node.children.append(nc_node)
    else:
        session._working_doc.root.children.append(nc_node)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="add_net_class",
        description=f"Add net class '{name}'",
        target=f"net_class:{name}",
        before_snapshot="",
        after_snapshot=nc_node.to_string(),
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_set_layer_constraints(
    session: Session,
    layer: str,
    min_width: float | None = None,
    min_clearance: float | None = None,
) -> ChangeRecord:
    """Set per-layer constraints in the board setup."""
    require_active(session)
    assert session._working_doc is not None

    setup_node = session._working_doc.root.get("setup")
    if setup_node is None:
        raise ValueError("Board has no setup section")

    before = setup_node.to_string()

    constraint_node = None
    for child in setup_node.children:
        if child.name == "layer_constraints":
            layer_child = child.get("layer")
            if layer_child and layer_child.first_value == layer:
                constraint_node = child
                break

    if constraint_node is None:
        parts = [f'(layer "{layer}")']
        if min_width is not None:
            parts.append(f"(min_width {min_width})")
        if min_clearance is not None:
            parts.append(f"(min_clearance {min_clearance})")
        constraint_text = f"(layer_constraints {' '.join(parts)})"
        constraint_node = sexp_parse(constraint_text)
        setup_node.children.append(constraint_node)
    else:
        if min_width is not None:
            existing = constraint_node.get("min_width")
            if existing and existing.children:
                existing.children[0] = _make_atom(str(min_width))
            else:
                constraint_node.children.append(sexp_parse(f"(min_width {min_width})"))
        if min_clearance is not None:
            existing = constraint_node.get("min_clearance")
            if existing and existing.children:
                existing.children[0] = _make_atom(str(min_clearance))
            else:
                constraint_node.children.append(sexp_parse(f"(min_clearance {min_clearance})"))

    after = setup_node.to_string()

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="set_layer_constraints",
        description=f"Set constraints for {layer}",
        target=f"layer:{layer}",
        before_snapshot=before,
        after_snapshot=after,
        applied=True,
    )
    session.changes.append(record)
    return record
