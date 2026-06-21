"""Net and zone management operations."""

from __future__ import annotations

import contextlib
import uuid
from typing import Any

from ..sexp.parser import parse as sexp_parse
from .helpers import find_footprint, footprint_field
from .types import ChangeRecord, Session, _normalize_layer, require_active


def apply_create_net(session: Session, net_name: str) -> ChangeRecord:
    """Add a new net to the board."""
    require_active(session)
    assert session._working_doc is not None

    for net_node in session._working_doc.root.find_all("net"):
        vals = net_node.atom_values
        if len(vals) >= 2 and vals[1] == net_name:
            raise ValueError(f"Net {net_name!r} already exists")

    max_num = 0
    for net_node in session._working_doc.root.find_all("net"):
        vals = net_node.atom_values
        if vals:
            with contextlib.suppress(ValueError):
                max_num = max(max_num, int(vals[0]))

    new_num = max_num + 1
    net_sexp = sexp_parse(f'(net {new_num} "{net_name}")')

    insert_idx = 0
    for i, child in enumerate(session._working_doc.root.children):
        if child.name == "net":
            insert_idx = i + 1
    if insert_idx == 0:
        for i, child in enumerate(session._working_doc.root.children):
            if child.name == "layers":
                insert_idx = i + 1
                break

    session._working_doc.root.children.insert(insert_idx, net_sexp)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="create_net",
        description=f"Create net {new_num} '{net_name}'",
        target=net_name,
        before_snapshot="",
        after_snapshot=net_sexp.to_string(),
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_delete_net(session: Session, net_name: str) -> ChangeRecord:
    """Remove a net declaration from the board."""
    require_active(session)
    assert session._working_doc is not None

    target_node = None
    for net_node in session._working_doc.root.find_all("net"):
        vals = net_node.atom_values
        if len(vals) >= 2 and vals[1] == net_name:
            target_node = net_node
            break

    if target_node is None:
        raise ValueError(f"Net {net_name!r} not found")

    before = target_node.to_string()
    session._working_doc.root.children.remove(target_node)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="delete_net",
        description=f"Delete net '{net_name}'",
        target=net_name,
        before_snapshot=before,
        after_snapshot="",
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_assign_net(
    session: Session, reference: str, pad_number: str, net_name: str
) -> ChangeRecord:
    """Assign a net to a specific pad on a component."""
    require_active(session)
    assert session._working_doc is not None

    net_num = None
    for net_node in session._working_doc.root.find_all("net"):
        vals = net_node.atom_values
        if len(vals) >= 2 and vals[1] == net_name:
            net_num = int(vals[0])
            break
    if net_num is None:
        raise ValueError(f"Net {net_name!r} not found on the board")

    fp_node = find_footprint(session._working_doc, reference)
    if fp_node is None:
        raise ValueError(f"Component {reference!r} not found")

    target_pad = None
    for pad_node in fp_node.find_all("pad"):
        vals = pad_node.atom_values
        if vals and vals[0] == pad_number:
            target_pad = pad_node
            break
    if target_pad is None:
        raise ValueError(f"Pad {pad_number!r} not found on {reference}")

    before = target_pad.to_string()

    existing_net = target_pad.get("net")
    if existing_net is not None:
        target_pad.children.remove(existing_net)

    net_child = sexp_parse(f'(net {net_num} "{net_name}")')
    target_pad.children.append(net_child)

    after = target_pad.to_string()

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="assign_net",
        description=f"Assign net '{net_name}' to {reference} pad {pad_number}",
        target=f"{reference}:{pad_number}",
        before_snapshot=before,
        after_snapshot=after,
        applied=True,
    )
    session.changes.append(record)
    return record


def _board_footprints(doc: Any) -> dict[str, str | None]:
    """Map reference -> current Value for every footprint on the board."""
    out: dict[str, str | None] = {}
    for fp in doc.root.find_all("footprint"):
        ref = footprint_field(fp, "Reference")
        if ref:
            out[ref] = footprint_field(fp, "Value")
    return out


def apply_update_from_schematic(
    session: Session,
    components: list[dict[str, str]],
    nets: list[dict[str, Any]],
    *,
    place_new: bool = True,
    remove_extra: bool = False,
    spacing: float = 12.0,
    origin: tuple[float, float] = (25.0, 25.0),
) -> dict[str, Any]:
    """Reconcile a board against a schematic netlist (the "Update PCB" flow).

    Instantiates missing footprints from their libraries, updates values on
    existing ones, creates net declarations, and assigns nets to pads — all on
    the session's working document, recorded as ordinary undoable changes.
    """
    import math
    from pathlib import Path

    from . import board_setup_ops, placement_ops

    require_active(session)
    assert session._working_doc is not None
    doc = session._working_doc
    project_dir = Path(session.board_path).parent if session.board_path else None

    existing = _board_footprints(doc)
    existing_refs = set(existing)
    summary: dict[str, Any] = {
        "added": [],
        "updated": [],
        "unresolved": [],
        "nets_created": 0,
        "pads_assigned": 0,
        "skipped": [],
        "removed": [],
    }

    # 1. Place missing footprints from their libraries (real geometry only —
    #    a footprint that can't be resolved to a .kicad_mod is reported, not
    #    placed as a padless stub).
    placed: set[str] = set()
    to_place = [c for c in components if c["ref"] and c["ref"] not in existing_refs]
    if place_new and to_place:
        cols = max(1, math.ceil(math.sqrt(len(to_place))))
        for i, comp in enumerate(to_place):
            mod = placement_ops._resolve_kicad_mod_path(comp["footprint"], project_dir)
            if mod is None:
                summary["unresolved"].append({"ref": comp["ref"], "footprint": comp["footprint"]})
                continue
            x = origin[0] + (i % cols) * spacing
            y = origin[1] + (i // cols) * spacing
            placement_ops.place_from_kicad_mod(session, mod, comp["ref"], comp["value"], x, y)
            summary["added"].append(comp["ref"])
            placed.add(comp["ref"])
    on_board = existing_refs | placed

    # 2. Reconcile values on footprints that were already on the board.
    value_by_ref = {c["ref"]: c["value"] for c in components}
    for ref in sorted(existing_refs):
        new_val = value_by_ref.get(ref)
        if new_val and existing.get(ref) != new_val:
            try:
                board_setup_ops.apply_edit_component(session, ref, {"Value": new_val})
                summary["updated"].append(ref)
            except (ValueError, KeyError):
                pass

    # 3. Create any net declarations the board is missing.
    board_nets = set()
    for nn in doc.root.find_all("net"):
        v = nn.atom_values
        if len(v) >= 2:
            board_nets.add(v[1])
    for net in nets:
        name = net["name"]
        if name and name not in board_nets:
            apply_create_net(session, name)
            board_nets.add(name)
            summary["nets_created"] += 1

    # 4. Assign nets to pads from the netlist.
    for net in nets:
        name = net["name"]
        if not name:
            continue
        for ref, pin in net["nodes"]:
            if ref not in on_board:
                continue
            try:
                apply_assign_net(session, ref, pin, name)
                summary["pads_assigned"] += 1
            except ValueError:
                summary["skipped"].append({"ref": ref, "pin": pin, "net": name})

    # 5. Optionally remove footprints that are no longer in the schematic.
    if remove_extra:
        netlist_refs = {c["ref"] for c in components}
        for ref in sorted(existing_refs):
            if ref not in netlist_refs:
                try:
                    placement_ops.apply_delete(session, ref)
                    summary["removed"].append(ref)
                except ValueError:
                    pass

    return summary


def apply_create_zone(
    session: Session,
    net_name: str,
    layer: str,
    points: list[tuple[float, float]],
    min_thickness: float = 0.25,
    priority: int = 0,
) -> ChangeRecord:
    """Create a copper zone (pour) on the board."""
    require_active(session)
    assert session._working_doc is not None

    if len(points) < 3:
        raise ValueError("Zone polygon requires at least 3 points")

    layer = _normalize_layer(layer)

    net_num = None
    for net_node in session._working_doc.root.find_all("net"):
        vals = net_node.atom_values
        if len(vals) >= 2 and vals[1] == net_name:
            net_num = int(vals[0])
            break
    if net_num is None:
        raise ValueError(f"Net {net_name!r} not found on the board")

    zone_uuid = str(uuid.uuid4())
    pts_strs = " ".join(f"(xy {x} {y})" for x, y in points)

    zone_sexp_text = (
        f'(zone (net {net_num}) (net_name "{net_name}") (layer "{layer}")'
        f' (uuid "{zone_uuid}")'
        f" (hatch edge 0.5)"
        f" (priority {priority})"
        f" (connect_pads (clearance 0.5))"
        f" (min_thickness {min_thickness})"
        f" (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))"
        f" (polygon (pts {pts_strs})))"
    )
    zone_node = sexp_parse(zone_sexp_text)

    session._working_doc.root.children.append(zone_node)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="create_zone",
        description=f"Create {net_name} zone on {layer} ({len(points)} points)",
        target=f"zone:{zone_uuid[:8]}",
        before_snapshot="",
        after_snapshot=zone_node.to_string(),
        applied=True,
    )
    session.changes.append(record)
    return record
