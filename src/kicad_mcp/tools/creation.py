"""Footprint and symbol creation — generate .kicad_mod / .kicad_sym from scratch.

Pure-Python S-expression generation (no KiCad needed). Footprints can be placed
via ``place_from_library``; symbols can be added with ``add_symbol`` against the
library they're written into.
"""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path
from typing import Any

from ..sexp.parser import _quote_if_needed
from ..sexp.parser import parse as sexp_parse
from .registry import register_tool

# ── Footprints ─────────────────────────────────────────────────────

_PAD_SHAPES = frozenset({"rect", "circle", "roundrect", "oval", "trapezoid"})
_PAD_TYPES = frozenset({"smd", "thru_hole", "np_thru_hole"})

_SMD_LAYERS = ("F.Cu", "F.Paste", "F.Mask")
_THT_LAYERS = ("*.Cu", "*.Mask")


def _pad_sexp(pad: dict[str, Any]) -> str:
    """Render one (pad ...) from a pad dict. Raises ValueError on bad input."""
    number = str(pad.get("number", ""))
    if not number:
        raise ValueError("each pad needs a 'number'")
    ptype = pad.get("type", "smd")
    if ptype not in _PAD_TYPES:
        raise ValueError(f"pad {number}: type must be one of {sorted(_PAD_TYPES)}")
    shape = pad.get("shape", "roundrect")
    if shape not in _PAD_SHAPES:
        raise ValueError(f"pad {number}: shape must be one of {sorted(_PAD_SHAPES)}")
    try:
        x = float(pad["x"])
        y = float(pad["y"])
        w = float(pad.get("width", pad.get("size", 1.0)))
        h = float(pad.get("height", pad.get("size", w)))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"pad {number}: x/y/width/height must be numbers ({exc})") from exc

    parts = [f'(pad "{_esc(number)}" {ptype} {shape}', f"(at {x} {y})", f"(size {w} {h})"]
    if ptype in ("thru_hole", "np_thru_hole"):
        drill = float(pad.get("drill", min(w, h) * 0.6))
        parts.append(f"(drill {drill})")
        layers = pad.get("layers") or _THT_LAYERS
    else:
        layers = pad.get("layers") or _SMD_LAYERS
    parts.append("(layers " + " ".join(_quote_if_needed(str(lyr)) for lyr in layers) + ")")
    if shape == "roundrect":
        parts.append(f"(roundrect_rratio {float(pad.get('roundrect_rratio', 0.25))})")
    parts.append(f'(uuid "{_uuid.uuid4()}")')
    return "    " + " ".join(parts) + ")"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _create_footprint_handler(
    output_path: str,
    name: str,
    pads: list[dict[str, Any]],
    description: str = "",
    tags: str = "",
) -> dict[str, Any]:
    """Create a .kicad_mod footprint file from a pad list.

    Args:
        output_path: Path for the .kicad_mod file.
        name: Footprint name.
        pads: List of pad dicts: {number, x, y, width, height, shape, type, drill?, layers?}.
            shape ∈ rect/circle/roundrect/oval; type ∈ smd/thru_hole/np_thru_hole (mm).
        description: Optional description.
        tags: Optional space-separated tags.
    """
    from ..security import SecurityError, get_validator

    try:
        get_validator().validate_output(output_path)
    except SecurityError as exc:
        return {"error": f"Security error: {exc}"}
    if not name:
        return {"error": "name is required"}
    if not pads:
        return {"error": "at least one pad is required"}

    try:
        pad_lines = [_pad_sexp(p) for p in pads]
    except ValueError as exc:
        return {"error": str(exc)}

    # through_hole if any pad needs a drill, else smd.
    attr = "through_hole" if any(p.get("type") in ("thru_hole",) for p in pads) else "smd"

    text = (
        f"(footprint {_quote_if_needed(name)}\n"
        f"  (version 20240108)\n"
        f'  (generator "kicad_mcp")\n'
        f'  (layer "F.Cu")\n'
        f"  (descr {_quote_if_needed(description)})\n"
        f"  (tags {_quote_if_needed(tags)})\n"
        f'  (property "Reference" "REF**" (at 0 -2 0) (layer "F.SilkS")'
        f" (effects (font (size 1 1) (thickness 0.15))))\n"
        f'  (property "Value" {_quote_if_needed(name)} (at 0 2 0) (layer "F.Fab")'
        f" (effects (font (size 1 1) (thickness 0.15))))\n"
        f"  (attr {attr})\n" + "\n".join(pad_lines) + "\n"
        "  (embedded_fonts no)\n"
        ")\n"
    )

    # Round-trip check: must parse and re-expose the pads we wrote.
    try:
        node = sexp_parse(text)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"generated footprint failed to parse: {exc}"}
    n_pads = len(node.find_all("pad"))
    if n_pads != len(pads):
        return {"error": f"pad round-trip mismatch ({n_pads} != {len(pads)})"}

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return {"status": "created", "path": str(out), "name": name, "pad_count": n_pads}


# ── Symbols ────────────────────────────────────────────────────────

_PIN_TYPES = frozenset(
    {
        "input",
        "output",
        "bidirectional",
        "tri_state",
        "passive",
        "power_in",
        "power_out",
        "open_collector",
        "open_emitter",
        "unspecified",
        "no_connect",
    }
)
_PIN_SIDES = frozenset({"left", "right", "top", "bottom"})

_SIDE_ANGLE = {"left": 0, "right": 180, "top": 270, "bottom": 90}


def _symbol_pins_block(pins: list[dict[str, Any]], unit_name: str) -> tuple[str, int]:
    """Auto-lay-out pins by side on a 2.54mm grid; return the unit sub-symbol + width."""
    by_side: dict[str, list[dict[str, Any]]] = {s: [] for s in _PIN_SIDES}
    for p in pins:
        side = p.get("side", "left")
        if side not in _PIN_SIDES:
            raise ValueError(f"pin {p.get('number')}: side must be one of {sorted(_PIN_SIDES)}")
        by_side[side].append(p)

    pitch = 2.54
    n_rows = max(len(by_side["left"]), len(by_side["right"]), 1)
    half_h = (n_rows - 1) * pitch / 2
    # Body half-width grows with the longest side count; min 2 columns.
    half_w = max(2, len(by_side["top"]), len(by_side["bottom"])) * pitch

    lines: list[str] = []
    for side in ("left", "right", "top", "bottom"):
        group = by_side[side]
        for i, p in enumerate(group):
            num = str(p.get("number", ""))
            if not num:
                raise ValueError("each pin needs a 'number'")
            ptype = p.get("type", "passive")
            if ptype not in _PIN_TYPES:
                raise ValueError(f"pin {num}: type must be one of {sorted(_PIN_TYPES)}")
            pname = str(p.get("name", "~")) or "~"
            ang = _SIDE_ANGLE[side]
            if side in ("left", "right"):
                py = half_h - i * pitch
                px = -half_w if side == "left" else half_w
            else:
                cnt = len(group)
                px = -((cnt - 1) * pitch) / 2 + i * pitch
                py = half_h + pitch if side == "top" else -half_h - pitch
            lines.append(
                f"      (pin {ptype} line (at {px} {py} {ang}) (length 2.54)\n"
                f"        (name {_quote_if_needed(pname)} (effects (font (size 1.27 1.27))))\n"
                f'        (number "{_esc(num)}" (effects (font (size 1.27 1.27))))\n'
                f"      )"
            )
    body = (
        f"    (symbol {_quote_if_needed(unit_name)}\n"
        f"      (rectangle (start {-half_w} {half_h + pitch}) (end {half_w} {-half_h - pitch})\n"
        f"        (stroke (width 0.254) (type default)) (fill (type background)))\n"
        + "\n".join(lines)
        + "\n    )"
    )
    return body, len(pins)


def _create_symbol_handler(
    output_path: str,
    name: str,
    pins: list[dict[str, Any]],
    reference_prefix: str = "U",
    footprint: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Create or append a symbol in a .kicad_sym library.

    Args:
        output_path: Path to the .kicad_sym library (created if missing).
        name: Symbol name.
        pins: List of pin dicts: {number, name, type, side}. type ∈ input/output/
            bidirectional/passive/power_in/...; side ∈ left/right/top/bottom.
        reference_prefix: Reference designator prefix (e.g., "U", "R").
        footprint: Optional default footprint (e.g., "lib:FP").
        description: Optional description.
    """
    from ..security import SecurityError, get_validator

    try:
        get_validator().validate_output(output_path)
    except SecurityError as exc:
        return {"error": f"Security error: {exc}"}
    if not name:
        return {"error": "name is required"}
    if not pins:
        return {"error": "at least one pin is required"}

    try:
        unit_block, n_pins = _symbol_pins_block(pins, f"{name}_1_1")
    except ValueError as exc:
        return {"error": str(exc)}

    sym_text = (
        f"  (symbol {_quote_if_needed(name)}\n"
        f"    (exclude_from_sim no) (in_bom yes) (on_board yes)\n"
        f'    (property "Reference" {_quote_if_needed(reference_prefix)} (at 0 0 0)'
        f" (effects (font (size 1.27 1.27))))\n"
        f'    (property "Value" {_quote_if_needed(name)} (at 0 -2.54 0)'
        f" (effects (font (size 1.27 1.27))))\n"
        f'    (property "Footprint" {_quote_if_needed(footprint)} (at 0 0 0)'
        f" (effects (font (size 1.27 1.27)) (hide yes)))\n"
        f'    (property "Datasheet" "~" (at 0 0 0)'
        f" (effects (font (size 1.27 1.27)) (hide yes)))\n"
        f'    (property "Description" {_quote_if_needed(description)} (at 0 0 0)'
        f" (effects (font (size 1.27 1.27)) (hide yes)))\n"
        f"{unit_block}\n"
        f"  )"
    )

    out = Path(output_path)
    if out.exists():
        existing = out.read_text(encoding="utf-8")
        try:
            root = sexp_parse(existing)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"existing library failed to parse: {exc}"}
        if any(s.first_value == name for s in root.find_all("symbol")):
            return {"error": f"symbol {name!r} already exists in {out.name}"}
        # Insert before the final closing paren.
        idx = existing.rstrip().rfind(")")
        new_text = existing.rstrip()[:idx] + sym_text + "\n)\n"
    else:
        new_text = (
            f"(kicad_symbol_lib\n"
            f"  (version 20231120)\n"
            f'  (generator "kicad_mcp")\n'
            f'  (generator_version "9.0")\n'
            f"{sym_text}\n"
            f")\n"
        )

    # Round-trip check.
    try:
        check = sexp_parse(new_text)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"generated library failed to parse: {exc}"}
    if not any(s.first_value == name for s in check.find_all("symbol")):
        return {"error": "symbol round-trip failed"}

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(new_text, encoding="utf-8")
    return {"status": "created", "path": str(out), "name": name, "pin_count": n_pins}


# ── Registration ───────────────────────────────────────────────────

register_tool(
    name="create_footprint",
    description="Create a .kicad_mod footprint file from a pad list (no KiCad required).",
    parameters={
        "output_path": {"type": "string", "description": "Output .kicad_mod path."},
        "name": {"type": "string", "description": "Footprint name."},
        "pads": {
            "type": "array",
            "description": (
                "Pads: [{number, x, y, width, height, shape, type, drill?, layers?}] in mm. "
                "shape: rect/circle/roundrect/oval; type: smd/thru_hole/np_thru_hole."
            ),
        },
        "description": {"type": "string", "description": "Optional description."},
        "tags": {"type": "string", "description": "Optional space-separated tags."},
    },
    handler=_create_footprint_handler,
    category="creation",
)

register_tool(
    name="create_symbol",
    description="Create or append a symbol in a .kicad_sym library with auto-laid-out pins.",
    parameters={
        "output_path": {"type": "string", "description": "Output .kicad_sym library path."},
        "name": {"type": "string", "description": "Symbol name."},
        "pins": {
            "type": "array",
            "description": (
                "Pins: [{number, name, type, side}]. type: input/output/bidirectional/"
                "passive/power_in/...; side: left/right/top/bottom."
            ),
        },
        "reference_prefix": {
            "type": "string",
            "description": "Refdes prefix (e.g., 'U'). Default 'U'.",
        },
        "footprint": {"type": "string", "description": "Optional default footprint (lib:FP)."},
        "description": {"type": "string", "description": "Optional description."},
    },
    handler=_create_symbol_handler,
    category="creation",
)
