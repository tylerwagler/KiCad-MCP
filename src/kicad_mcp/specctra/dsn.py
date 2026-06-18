"""Generate a Specctra DSN design file from a parsed KiCad board.

The DSN is the input format for the Freerouting autorouter. We build it directly
from our pure-Python board model (no KiCad install required), following the same
conventions KiCad's own ``specctra_export.cpp`` uses:

- ``(resolution um 10)`` — 1 file unit = 0.1 µm, so ``mm × 10000`` → file units.
- Y is negated (Specctra Y grows upward; KiCad Y grows downward).
- Footprint rotation is baked into absolute pin coordinates and every component is
  placed at rotation 0. This keeps pad *centres* (what the router connects to)
  geometrically exact regardless of Specctra's rotation-sign convention; only pad
  *shape* orientation is approximated (axis-aligned), which affects clearance only.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..schema.extract import (
    extract_board_outline,
    extract_footprints,
    extract_nets,
)

if TYPE_CHECKING:
    from ..schema.board import Footprint, Pad
    from ..schema.common import BoundingBox
    from ..sexp import Document

# mm → Specctra file units (0.1 µm). 1 mm = 1000 µm = 10000 units.
_UNITS_PER_MM = 10000

_SIMPLE_TOKEN = re.compile(r"^[A-Za-z0-9_.+\-]+$")

_VIA_PADSTACK = "Via_default"


class DsnExportError(Exception):
    """Raised when a board cannot be exported to DSN."""


@dataclass
class DsnOptions:
    """Routing rule defaults written into the DSN (all in mm)."""

    trace_width: float = 0.25
    clearance: float = 0.2
    via_diameter: float = 0.8
    via_drill: float = 0.4


@dataclass
class _Padstack:
    """A unique pad geometry shared across pins."""

    name: str
    shapes: list[str] = field(default_factory=list)  # rendered (shape ...) bodies


def _u(mm: float) -> int:
    """Convert a millimetre length to integer Specctra file units."""
    return round(mm * _UNITS_PER_MM)


def _coord(x_mm: float, y_mm: float) -> tuple[int, int]:
    """Convert an (x, y) board point in mm to DSN units with Y negated."""
    return _u(x_mm), _u(-y_mm)


def _tok(value: str) -> str:
    """Quote a token if it isn't a simple Specctra identifier."""
    if value and _SIMPLE_TOKEN.match(value):
        return value
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


def _is_copper(layer: str) -> bool:
    return layer.endswith(".Cu") or layer in ("*.Cu",)


def _pad_copper_layers(pad: Pad, copper_layers: list[str]) -> list[str]:
    """Resolve which copper layers a pad occupies."""
    out: list[str] = []
    for lyr in pad.layers:
        if lyr == "*.Cu":
            return list(copper_layers)
        if lyr.endswith(".Cu"):
            out.append(lyr)
    # Through-hole pads without explicit copper still span the full stack.
    if not out and pad.pad_type in ("thru_hole", "np_thru_hole"):
        return list(copper_layers)
    return out


def _rotate(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    """Rotate a footprint-local point by the footprint angle (matches A* extractor)."""
    if abs(angle_deg) < 1e-9:
        return x, y
    a = math.radians(angle_deg)
    cos_a, sin_a = math.cos(a), math.sin(a)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a


def _pad_shape_body(pad: Pad, layer: str, angle_deg: float) -> str:
    """Render a single ``(shape ...)`` body for a pad on a given copper layer."""
    w, h = pad.size
    # Swap width/height for quarter-turn footprint rotations so the axis-aligned
    # approximation still covers the pad.
    norm = round((angle_deg % 180) / 90) * 90 if angle_deg else 0
    if norm == 90:
        w, h = h, w

    if pad.shape == "circle" or (pad.shape in ("oval",) and abs(w - h) < 1e-6):
        return f"(shape (circle {layer} {_u(w)}))"
    if pad.shape in ("rect", "roundrect", "oval", "trapezoid", "custom", ""):
        return f"(shape (rect {layer} {_u(-w / 2)} {_u(-h / 2)} {_u(w / 2)} {_u(h / 2)}))"
    # Fallback: bounding rectangle.
    return f"(shape (rect {layer} {_u(-w / 2)} {_u(-h / 2)} {_u(w / 2)} {_u(h / 2)}))"


def board_to_dsn(doc: Document, options: DsnOptions | None = None, name: str = "board") -> str:
    """Build a Specctra DSN string from a parsed board document.

    Raises :class:`DsnExportError` if the board lacks an outline or copper layers.
    """
    opts = options or DsnOptions()

    footprints = extract_footprints(doc)
    nets = extract_nets(doc)
    bbox = extract_board_outline(doc)
    if bbox is None:
        raise DsnExportError("No board outline (Edge.Cuts) found; cannot define routing boundary")

    # Copper layers, in stack order (F.Cu first, B.Cu last).
    copper_layers = _board_copper_layers(doc)
    if len(copper_layers) < 2:
        copper_layers = ["F.Cu", "B.Cu"]

    net_names = {n.number: n.name for n in nets}

    padstacks: dict[str, _Padstack] = {}
    images: list[str] = []
    placements: list[str] = []
    # net_number -> list of "ref-pinid" pin references
    net_pins: dict[int, list[str]] = {}

    for fp in footprints:
        image_id = _tok(fp.reference or fp.uuid or "anon")
        pins, fp_net_pins = _build_image_pins(fp, copper_layers, padstacks)
        images.append(f"    (image {image_id}\n{pins}    )")

        side = "back" if fp.layer.startswith("B.") else "front"
        px, py = _coord(fp.position.x, fp.position.y)
        place = f"(place {_tok(fp.reference)} {px} {py} {side} 0)"
        placements.append(f"    (component {image_id}\n      {place}\n    )")

        for net_no, pin_ref in fp_net_pins:
            net_pins.setdefault(net_no, []).append(pin_ref)

    # Via padstack (spans the full copper stack).
    via_shapes = "".join(
        f"\n      (shape (circle {lyr} {_u(opts.via_diameter)}))" for lyr in copper_layers
    )
    padstack_via = f"    (padstack {_tok(_VIA_PADSTACK)}{via_shapes}\n      (attach off)\n    )"

    dsn = _assemble(
        name=name,
        copper_layers=copper_layers,
        bbox=bbox,
        opts=opts,
        placements=placements,
        images=images,
        padstacks=padstacks,
        padstack_via=padstack_via,
        net_pins=net_pins,
        net_names=net_names,
    )
    return dsn


def _board_copper_layers(doc: Document) -> list[str]:
    """Return copper layer names in stack order from the board's (layers ...)."""
    from ..schema.extract import extract_layers

    layers = extract_layers(doc)
    copper = [lyr.name for lyr in layers if _is_copper(lyr.name) and lyr.layer_type == "signal"]
    # KiCad lists F.Cu at index 0 and B.Cu at 31; keep file order which is stack order.
    return copper


def _build_image_pins(
    fp: Footprint,
    copper_layers: list[str],
    padstacks: dict[str, _Padstack],
) -> tuple[str, list[tuple[int, str]]]:
    """Render an image's pin lines and collect (net_number, "ref-pinid") refs."""
    lines: list[str] = []
    net_pins: list[tuple[int, str]] = []
    seen_ids: dict[str, int] = {}

    for pad in fp.pads:
        pad_layers = _pad_copper_layers(pad, copper_layers)
        if not pad_layers:
            continue  # not a copper pad (e.g. paste/mask only)

        padstack_name = _intern_padstack(pad, pad_layers, fp.position.angle, padstacks)

        # Unique pin id within the image.
        base_id = pad.number or "0"
        seen_ids[base_id] = seen_ids.get(base_id, 0) + 1
        pin_id = base_id if seen_ids[base_id] == 1 else f"{base_id}_{seen_ids[base_id]}"

        # Bake footprint rotation into the pin coordinate (place ROT is 0).
        rx, ry = _rotate(pad.position.x, pad.position.y, fp.position.angle)
        gx, gy = _coord(fp.position.x + rx, fp.position.y + ry)
        # Pin coordinates are relative to the component origin.
        ox, oy = _coord(fp.position.x, fp.position.y)
        lines.append(f"      (pin {_tok(padstack_name)} {_tok(pin_id)} {gx - ox} {gy - oy})\n")

        if pad.net_number:  # net 0 == unconnected
            net_pins.append((pad.net_number, f"{fp.reference}-{pin_id}"))

    return "".join(lines), net_pins


def _intern_padstack(
    pad: Pad,
    pad_layers: list[str],
    angle_deg: float,
    padstacks: dict[str, _Padstack],
) -> str:
    """Register (deduplicated) a padstack for this pad and return its name."""
    w, h = pad.size
    norm = round((angle_deg % 180) / 90) * 90 if angle_deg else 0
    shape_kind = (
        "circle" if (pad.shape == "circle" or abs(w - h) < 1e-6 and pad.shape == "oval") else "rect"
    )
    key_w, key_h = (h, w) if norm == 90 else (w, h)
    layer_key = "ALL" if len(pad_layers) > 1 else (pad_layers[0] if pad_layers else "F.Cu")
    name = f"PS_{shape_kind}_{_u(key_w)}x{_u(key_h)}_{layer_key}".replace(".", "")

    if name not in padstacks:
        bodies = [_pad_shape_body(pad, lyr, angle_deg) for lyr in pad_layers]
        padstacks[name] = _Padstack(name=name, shapes=bodies)
    return name


def _assemble(
    *,
    name: str,
    copper_layers: list[str],
    bbox: BoundingBox,
    opts: DsnOptions,
    placements: list[str],
    images: list[str],
    padstacks: dict[str, _Padstack],
    padstack_via: str,
    net_pins: dict[int, list[str]],
    net_names: dict[int, str],
) -> str:
    """Render the full DSN document from its parts."""
    layer_lines = "\n".join(
        f"    (layer {lyr} (type signal) (property (index {i})))"
        for i, lyr in enumerate(copper_layers)
    )

    # Rectangular boundary from the board bounding box (closed polyline).
    x0, y0 = _coord(bbox.min_x, bbox.min_y)
    x1, y1 = _coord(bbox.max_x, bbox.max_y)
    pts = f"{x0} {y0}  {x1} {y0}  {x1} {y1}  {x0} {y1}  {x0} {y0}"
    boundary = f"    (boundary (path pcb 0  {pts}))"

    rule = f"    (rule (width {_u(opts.trace_width)}) (clearance {_u(opts.clearance)}))"

    structure = (
        f"  (structure\n{layer_lines}\n{boundary}\n    (via {_tok(_VIA_PADSTACK)})\n{rule}\n  )"
    )

    placement_block = "  (placement\n" + "\n".join(placements) + "\n  )"

    padstack_blocks = []
    for ps in padstacks.values():
        shape_lines = "".join(f"\n      {body}" for body in ps.shapes)
        padstack_blocks.append(
            f"    (padstack {_tok(ps.name)}{shape_lines}\n      (attach off)\n    )"
        )
    library_block = (
        "  (library\n"
        + "\n".join(images)
        + "\n"
        + "\n".join(padstack_blocks)
        + "\n"
        + padstack_via
        + "\n  )"
    )

    net_blocks = []
    class_nets = []
    for net_no in sorted(net_pins):
        nm = net_names.get(net_no, "") or f"Net-{net_no}"
        pins = " ".join(net_pins[net_no])
        net_blocks.append(f"    (net {_tok(nm)}\n      (pins {pins})\n    )")
        class_nets.append(_tok(nm))

    class_net_tokens = " ".join(class_nets)
    klass = (
        "    (class kicad_default "
        + class_net_tokens
        + "\n      (circuit (use_via "
        + _tok(_VIA_PADSTACK)
        + "))\n"
        + f"      (rule (width {_u(opts.trace_width)}) (clearance {_u(opts.clearance)}))\n"
        + "    )"
    )
    network_block = "  (network\n" + "\n".join(net_blocks) + "\n" + klass + "\n  )"

    return (
        f"(pcb {_tok(name)}\n"
        "  (parser\n"
        '    (string_quote ")\n'
        "    (space_in_quoted_tokens on)\n"
        '    (host_cad "KiCad-MCP")\n'
        '    (host_version "1.0")\n'
        "  )\n"
        "  (resolution um 10)\n"
        "  (unit um)\n"
        f"{structure}\n"
        f"{placement_block}\n"
        f"{library_block}\n"
        f"{network_block}\n"
        "  (wiring)\n"
        ")\n"
    )
