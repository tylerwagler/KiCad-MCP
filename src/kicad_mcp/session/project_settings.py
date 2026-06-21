"""Net classes and DRC constraints stored in the KiCad project file (.kicad_pro).

In KiCad 7 these moved out of the .kicad_pcb into the JSON project file under
``net_settings`` (net classes + assignments) and ``board.design_settings.rules``
(board-level minimums). ``kicad-cli pcb drc`` reads them from there, so writing
them here is what makes ``run_drc`` check real design intent instead of defaults.

These edits write the .kicad_pro directly — they are independent of the board
document and are not part of the session's undo stack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Numeric minimums under board.design_settings.rules (mm, except spoke counts).
_CONSTRAINT_KEYS: frozenset[str] = frozenset(
    {
        "min_clearance",
        "min_track_width",
        "min_via_diameter",
        "min_through_hole_diameter",
        "min_via_annular_width",
        "min_hole_to_hole",
        "min_hole_clearance",
        "min_microvia_diameter",
        "min_microvia_drill",
        "min_copper_edge_clearance",
        "min_silk_clearance",
        "min_text_height",
        "min_text_thickness",
    }
)

# Friendly aliases for the constraint keys.
_CONSTRAINT_ALIASES: dict[str, str] = {
    "clearance": "min_clearance",
    "min_space": "min_clearance",
    "track_width": "min_track_width",
    "min_track": "min_track_width",
    "via_diameter": "min_via_diameter",
    "min_via": "min_via_diameter",
    "min_via_drill": "min_through_hole_diameter",
    "min_drill": "min_through_hole_diameter",
    "min_hole": "min_through_hole_diameter",
    "annular_width": "min_via_annular_width",
    "min_annular_width": "min_via_annular_width",
}

# A net class entry mirrors KiCad's "Default" shape so the GUI/DRC accept it.
_NET_CLASS_DEFAULTS: dict[str, Any] = {
    "bus_width": 12,
    "clearance": 0.2,
    "diff_pair_gap": 0.25,
    "diff_pair_via_gap": 0.25,
    "diff_pair_width": 0.2,
    "line_style": 0,
    "microvia_diameter": 0.3,
    "microvia_drill": 0.1,
    "pcb_color": "rgba(0, 0, 0, 0.000)",
    "priority": 0,
    "schematic_color": "rgba(0, 0, 0, 0.000)",
    "track_width": 0.25,
    "tuning_profile": "",
    "via_diameter": 0.6,
    "via_drill": 0.3,
    "wire_width": 6,
}

# Net class numeric fields a caller may set (project-file key -> stays same).
_NET_CLASS_FIELDS: frozenset[str] = frozenset(
    {
        "clearance",
        "track_width",
        "via_diameter",
        "via_drill",
        "diff_pair_width",
        "diff_pair_gap",
        "microvia_diameter",
        "microvia_drill",
    }
)


def project_path_for(board_path: str) -> Path:
    """The sibling .kicad_pro for a given .kicad_pcb path."""
    return Path(board_path).with_suffix(".kicad_pro")


def _load(pro: Path) -> dict[str, Any]:
    if not pro.exists():
        raise FileNotFoundError(f"Project file not found: {pro}")
    data: dict[str, Any] = json.loads(pro.read_text(encoding="utf-8"))
    return data


def _save(pro: Path, data: dict[str, Any]) -> None:
    pro.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def set_board_constraints(board_path: str, rules: dict[str, float]) -> dict[str, Any]:
    """Write board-level minimum constraints to the project's design rules.

    Args:
        board_path: Path to the .kicad_pcb (the .kicad_pro sibling is edited).
        rules: Constraint name -> value in mm. Aliases are accepted, e.g.
            ``min_track``/``min_space``/``min_annular_width``/``min_via_drill``.

    Returns:
        A dict describing the resolved constraints and the project file written.
    """
    resolved: dict[str, float] = {}
    for key, value in rules.items():
        canonical = _CONSTRAINT_ALIASES.get(key, key)
        if canonical not in _CONSTRAINT_KEYS:
            raise ValueError(
                f"Unknown constraint {key!r}. Valid keys: {sorted(_CONSTRAINT_KEYS)}. "
                f"Aliases: {sorted(_CONSTRAINT_ALIASES)}"
            )
        resolved[canonical] = float(value)

    pro = project_path_for(board_path)
    data = _load(pro)
    design_settings = data.setdefault("board", {}).setdefault("design_settings", {})
    rules_obj = design_settings.setdefault("rules", {})
    rules_obj.update(resolved)
    _save(pro, data)
    return {"project": pro.name, "rules": resolved}


def set_net_class(
    board_path: str,
    name: str,
    fields: dict[str, float | None],
    nets: list[str] | None = None,
    patterns: list[str] | None = None,
) -> dict[str, Any]:
    """Create or update a net class in the project file, and assign nets to it.

    Args:
        board_path: Path to the .kicad_pcb (the .kicad_pro sibling is edited).
        name: Net class name (created if absent, updated in place if present).
        fields: Numeric net-class fields to set (clearance, track_width,
            via_diameter, via_drill, diff_pair_width/gap, microvia_*). Only
            non-None entries are applied.
        nets: Exact net names to assign to this class (each becomes a pattern).
        patterns: Wildcard net patterns (e.g. ``/ISO_*``) to assign to this class.

    Returns:
        A dict with the resulting class and the assigned patterns.
    """
    bad = {k for k in fields if k not in _NET_CLASS_FIELDS}
    if bad:
        raise ValueError(
            f"Unknown net-class field(s) {sorted(bad)}. Valid: {sorted(_NET_CLASS_FIELDS)}"
        )

    pro = project_path_for(board_path)
    data = _load(pro)
    net_settings = data.setdefault("net_settings", {})
    classes: list[dict[str, Any]] = net_settings.setdefault("classes", [])

    cls = next((c for c in classes if c.get("name") == name), None)
    if cls is None:
        cls = dict(_NET_CLASS_DEFAULTS)
        cls["name"] = name
        # Distinct, ascending priority for each user class (lower = higher
        # priority; KiCad keeps "Default" at INT_MAX as the catch-all).
        cls["priority"] = sum(1 for c in classes if c.get("name") != "Default")
        classes.append(cls)
    cls.update({k: v for k, v in fields.items() if v is not None})

    assigned: list[str] = list(nets or []) + list(patterns or [])
    if assigned:
        pats: list[dict[str, str]] = net_settings.setdefault("netclass_patterns", [])
        wanted = set(assigned)
        # Drop any prior assignment for these patterns, then (re)point them here.
        pats[:] = [p for p in pats if p.get("pattern") not in wanted]
        pats.extend({"netclass": name, "pattern": p} for p in assigned)

    _save(pro, data)
    return {"project": pro.name, "class": cls, "assigned": assigned}
