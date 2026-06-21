"""Board setup operations: size, outline, mounting holes, text, design rules, etc."""

from __future__ import annotations

import re
import uuid

from ..constants import BOARD_OUTLINE_STROKE_WIDTH
from ..sexp.parser import parse as sexp_parse
from .helpers import find_footprint, footprint_field
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
            f" (stroke (width {BOARD_OUTLINE_STROKE_WIDTH}) (type default))"
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
            f" (stroke (width {BOARD_OUTLINE_STROKE_WIDTH}) (type default))"
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


def _next_reference(session: Session, prefix: str) -> str:
    """Next free ``<prefix><n>`` designator given the board's existing refs."""
    assert session._working_doc is not None
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    max_n = 0
    for fp_node in session._working_doc.root.find_all("footprint"):
        ref = footprint_field(fp_node, "Reference")
        match = pattern.match(ref) if ref else None
        if match:
            max_n = max(max_n, int(match.group(1)))
    return f"{prefix}{max_n + 1}"


def apply_add_mounting_hole(
    session: Session,
    x: float,
    y: float,
    drill: float = 3.2,
    pad_dia: float = 6.0,
    reference: str | None = None,
) -> ChangeRecord:
    """Insert a mounting hole footprint at the given position.

    Auto-assigns the next free ``H<n>`` reference unless ``reference`` is given,
    so placing several holes does not collide on a single ``H1``.
    """
    require_active(session)
    assert session._working_doc is not None

    ref = reference or _next_reference(session, "H")
    if find_footprint(session._working_doc, ref) is not None:
        raise ValueError(f"Component {ref!r} already exists on the board")

    hole_uuid = str(uuid.uuid4())
    ref_uuid = str(uuid.uuid4())
    val_uuid = str(uuid.uuid4())
    fp_text = (
        f'(footprint "MountingHole:MountingHole_{drill}mm"'
        f' (layer "F.Cu") (uuid "{hole_uuid}") (at {x} {y})'
        f' (property "Reference" "{ref}"'
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
        description=f"Add mounting hole {ref} at ({x}, {y}) drill={drill}mm",
        target=hole_uuid,  # Use full UUID for reliable identification
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
        target=text_uuid,  # Use full UUID for reliable identification
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


_COPPER_THICKNESS_DEFAULT = 0.035  # 1 oz copper, mm
_MASK_THICKNESS = 0.01  # mm
_DIELECTRIC_DEFAULTS = {"material": "FR4", "epsilon_r": 4.5, "loss_tangent": 0.02}


def _default_dielectrics(copper_layers: int) -> list[dict[str, float | str]]:
    """A symmetric FR-4 dielectric stack for ``copper_layers`` coppers.

    There is one dielectric between each adjacent copper pair (N-1 total). The
    outer gaps are 0.2 mm prepreg and the inner gaps share 1.0 mm of core, which
    for a 4-layer board yields the conventional 0.2/1.0/0.2 stack (~1.6 mm).
    """
    gaps = copper_layers - 1
    if gaps <= 1:
        return [{"type": "core", "thickness": 1.51}]
    core_count = gaps - 2
    core_th = round(1.0 / core_count, 4) if core_count else 0.0
    diels: list[dict[str, float | str]] = []
    for i in range(gaps):
        if i == 0 or i == gaps - 1:
            diels.append({"type": "prepreg", "thickness": 0.2})
        else:
            diels.append({"type": "core", "thickness": core_th})
    return diels


def _stackup_layer(name: str, kind: str, thickness: float | None = None) -> str:
    parts = [f'(layer "{name}" (type "{kind}")']
    if thickness is not None:
        parts.append(f"(thickness {thickness})")
    return " ".join(parts) + ")"


def _stackup_dielectric(index: int, spec: dict[str, float | str]) -> str:
    kind = spec.get("type", "prepreg")
    thickness = spec.get("thickness", 0.2)
    material = spec.get("material", _DIELECTRIC_DEFAULTS["material"])
    epsilon_r = spec.get("epsilon_r", _DIELECTRIC_DEFAULTS["epsilon_r"])
    loss = spec.get("loss_tangent", _DIELECTRIC_DEFAULTS["loss_tangent"])
    return (
        f'(layer "dielectric {index}" (type "{kind}") (thickness {thickness})'
        f' (material "{material}") (epsilon_r {epsilon_r}) (loss_tangent {loss}))'
    )


def apply_set_layer_stack(
    session: Session,
    copper_layers: int = 4,
    dielectrics: list[dict[str, float | str]] | None = None,
    copper_thickness: float = _COPPER_THICKNESS_DEFAULT,
) -> ChangeRecord:
    """Set the board copper-layer count and dielectric stackup.

    Rewrites the ``(layers …)`` table to ``copper_layers`` coppers with KiCad's
    numbering (F.Cu=0, In1.Cu=1, …, B.Cu=31) and writes a ``(setup (stackup …))``
    with one dielectric between each adjacent copper pair. Non-copper layers are
    preserved unchanged. ``dielectrics`` (if given) must hold exactly
    ``copper_layers - 1`` entries, each a dict with optional keys
    ``type``/``thickness``/``material``/``epsilon_r``/``loss_tangent``.
    """
    require_active(session)
    assert session._working_doc is not None
    doc = session._working_doc

    if copper_layers < 2 or copper_layers > 32 or copper_layers % 2 != 0:
        raise ValueError("copper_layers must be an even number between 2 and 32")

    gaps = copper_layers - 1
    diels = dielectrics if dielectrics is not None else _default_dielectrics(copper_layers)
    if len(diels) != gaps:
        raise ValueError(
            f"{copper_layers}-layer board needs {gaps} dielectric layer(s), got {len(diels)}"
        )

    layers_node = doc.root.get("layers")
    if layers_node is None:
        raise ValueError("Board has no layers section")
    setup_node = doc.root.get("setup")
    if setup_node is None:
        raise ValueError("Board has no setup section")

    before = layers_node.to_string() + "\n" + setup_node.to_string()

    # 1. Rewrite the copper rows of the layer table, preserving everything else.
    copper_types: dict[str, str] = {}
    other_rows: list[str] = []
    for child in layers_node.children:
        vals = child.atom_values
        lname = vals[0] if vals else ""
        if lname.endswith(".Cu"):
            copper_types[lname] = vals[1] if len(vals) > 1 else "signal"
        else:
            other_rows.append(child.to_string())

    inner = copper_layers - 2
    copper_rows = [f'(0 "F.Cu" {copper_types.get("F.Cu", "signal")})']
    copper_rows += [f'({i} "In{i}.Cu" signal)' for i in range(1, inner + 1)]
    copper_rows.append(f'(31 "B.Cu" {copper_types.get("B.Cu", "signal")})')

    new_layers = sexp_parse("(layers " + " ".join(copper_rows + other_rows) + ")")
    layers_idx = doc.root.children.index(layers_node)
    doc.root.children[layers_idx] = new_layers

    # 2. Build the stackup, copper interleaved with dielectrics, top to bottom.
    copper_names = ["F.Cu"] + [f"In{i}.Cu" for i in range(1, inner + 1)] + ["B.Cu"]
    rows = [
        _stackup_layer("F.SilkS", "Top Silk Screen"),
        _stackup_layer("F.Paste", "Top Solder Paste"),
        _stackup_layer("F.Mask", "Top Solder Mask", _MASK_THICKNESS),
    ]
    for ci, cu in enumerate(copper_names):
        rows.append(_stackup_layer(cu, "copper", copper_thickness))
        if ci < len(copper_names) - 1:
            rows.append(_stackup_dielectric(ci + 1, diels[ci]))
    rows += [
        _stackup_layer("B.Mask", "Bottom Solder Mask", _MASK_THICKNESS),
        _stackup_layer("B.Paste", "Bottom Solder Paste"),
        _stackup_layer("B.SilkS", "Bottom Silk Screen"),
        '(copper_finish "None")',
        "(dielectric_constraints no)",
    ]
    stackup_node = sexp_parse("(stackup " + " ".join(rows) + ")")

    existing_stackup = setup_node.get("stackup")
    if existing_stackup is not None:
        setup_node.children[setup_node.children.index(existing_stackup)] = stackup_node
    else:
        setup_node.children.insert(0, stackup_node)

    # 3. Keep the overall board thickness in sync with the stack.
    total = (
        copper_thickness * copper_layers
        + sum(float(d.get("thickness", 0.0)) for d in diels)
        + 2 * _MASK_THICKNESS
    )
    general_node = doc.root.get("general")
    if general_node is not None:
        thick_node = general_node.get("thickness")
        if thick_node is not None and thick_node.children:
            thick_node.children[0] = _make_atom(str(round(total, 4)))

    after = new_layers.to_string() + "\n" + setup_node.to_string()
    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="set_layer_stack",
        description=f"Set {copper_layers}-layer stackup ({round(total, 3)}mm)",
        target="layers",
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
            layer_nd.children[0] = _make_quoted(str(layer or "F.Cu"))

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
        new_fp = _build_footprint_node(
            new_library, reference, new_value, x, y, str(layer or "F.Cu")
        )

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
