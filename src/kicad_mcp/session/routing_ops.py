"""Routing operations: trace, via, delete trace/via, ratsnest."""

from __future__ import annotations

import uuid
from typing import Any

from ..sexp.parser import parse as sexp_parse
from .types import ChangeRecord, Session, _normalize_layer, require_active


def apply_route_trace(
    session: Session,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    width: float,
    layer: str,
    net_number: int,
) -> ChangeRecord:
    """Add a trace segment between two points."""
    require_active(session)
    assert session._working_doc is not None

    layer = _normalize_layer(layer)

    seg_uuid = str(uuid.uuid4())
    seg_text = (
        f"(segment (start {start_x} {start_y}) (end {end_x} {end_y})"
        f' (width {width}) (layer "{layer}") (net {net_number})'
        f' (uuid "{seg_uuid}"))'
    )
    seg_node = sexp_parse(seg_text)
    session._working_doc.root.children.append(seg_node)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="route_trace",
        description=(
            f"Route trace ({start_x},{start_y})->({end_x},{end_y})"
            f" w={width} on {layer} net {net_number}"
        ),
        target=f"segment:{seg_uuid}",
        before_snapshot="",
        after_snapshot=seg_node.to_string(),
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_add_via(
    session: Session,
    x: float,
    y: float,
    net_number: int,
    size: float = 0.8,
    drill: float = 0.4,
    layers: tuple[str, str] = ("F.Cu", "B.Cu"),
) -> ChangeRecord:
    """Add a via at a specific point."""
    require_active(session)
    assert session._working_doc is not None

    layers = (_normalize_layer(layers[0]), _normalize_layer(layers[1]))

    via_uuid = str(uuid.uuid4())
    via_text = (
        f"(via (at {x} {y}) (size {size}) (drill {drill})"
        f' (layers "{layers[0]}" "{layers[1]}") (net {net_number})'
        f' (uuid "{via_uuid}"))'
    )
    via_node = sexp_parse(via_text)
    session._working_doc.root.children.append(via_node)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="add_via",
        description=f"Add via at ({x},{y}) net {net_number} {layers[0]}->{layers[1]}",
        target=f"via:{via_uuid}",
        before_snapshot="",
        after_snapshot=via_node.to_string(),
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_delete_trace(session: Session, segment_uuid: str) -> ChangeRecord:
    """Delete a trace segment by UUID."""
    require_active(session)
    assert session._working_doc is not None

    target = None
    for child in session._working_doc.root.children:
        if child.name == "segment":
            uuid_node = child.get("uuid")
            if uuid_node and uuid_node.first_value == segment_uuid:
                target = child
                break

    if target is None:
        raise ValueError(f"Segment with UUID {segment_uuid!r} not found")

    before = target.to_string()
    session._working_doc.root.children.remove(target)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="delete_trace",
        description=f"Delete segment {segment_uuid[:8]}",
        target=f"segment:{segment_uuid}",
        before_snapshot=before,
        after_snapshot="",
        applied=True,
    )
    session.changes.append(record)
    return record


def apply_delete_via(session: Session, via_uuid: str) -> ChangeRecord:
    """Delete a via by UUID."""
    require_active(session)
    assert session._working_doc is not None

    target = None
    for child in session._working_doc.root.children:
        if child.name == "via":
            uuid_node = child.get("uuid")
            if uuid_node and uuid_node.first_value == via_uuid:
                target = child
                break

    if target is None:
        raise ValueError(f"Via with UUID {via_uuid!r} not found")

    before = target.to_string()
    session._working_doc.root.children.remove(target)

    record = ChangeRecord(
        change_id=str(uuid.uuid4())[:8],
        operation="delete_via",
        description=f"Delete via {via_uuid[:8]}",
        target=f"via:{via_uuid}",
        before_snapshot=before,
        after_snapshot="",
        applied=True,
    )
    session.changes.append(record)
    return record


def get_ratsnest(session: Session) -> list[dict[str, Any]]:
    """Get unrouted connections (ratsnest) for the board."""
    require_active(session)
    assert session._working_doc is not None
    doc = session._working_doc

    net_pads: dict[int, list[dict[str, Any]]] = {}
    for fp_node in doc.root.find_all("footprint"):
        ref = ""
        for prop in fp_node.find_all("property"):
            if prop.first_value == "Reference":
                vals = prop.atom_values
                if len(vals) > 1:
                    ref = vals[1]

        fp_at = fp_node.get("at")
        fp_x = float(fp_at.atom_values[0]) if fp_at and fp_at.atom_values else 0
        fp_y = float(fp_at.atom_values[1]) if fp_at and len(fp_at.atom_values) > 1 else 0

        for pad_node in fp_node.find_all("pad"):
            net_node = pad_node.get("net")
            if net_node:
                net_vals = net_node.atom_values
                if net_vals:
                    net_num = int(net_vals[0])
                    if net_num == 0:
                        continue
                    pad_at = pad_node.get("at")
                    pad_x = float(pad_at.atom_values[0]) if pad_at else 0
                    pad_y = (
                        float(pad_at.atom_values[1])
                        if pad_at and len(pad_at.atom_values) > 1
                        else 0
                    )
                    pad_vals = pad_node.atom_values
                    net_pads.setdefault(net_num, []).append(
                        {
                            "reference": ref,
                            "pad": pad_vals[0] if pad_vals else "",
                            "x": fp_x + pad_x,
                            "y": fp_y + pad_y,
                        }
                    )

    routed_nets: set[int] = set()
    for seg in doc.root.find_all("segment"):
        net_node = seg.get("net")
        if net_node and net_node.first_value:
            routed_nets.add(int(net_node.first_value))

    unrouted: list[dict[str, Any]] = []
    for net_num, pads in sorted(net_pads.items()):
        if net_num not in routed_nets and len(pads) >= 2:
            net_name = ""
            for net_node in doc.root.find_all("net"):
                vals = net_node.atom_values
                if vals and int(vals[0]) == net_num:
                    net_name = vals[1] if len(vals) > 1 else ""
                    break
            unrouted.append(
                {
                    "net_number": net_num,
                    "net_name": net_name,
                    "pad_count": len(pads),
                    "pads": pads,
                }
            )

    return unrouted
