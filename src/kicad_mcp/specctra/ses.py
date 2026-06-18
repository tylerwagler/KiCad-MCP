"""Parse a Specctra SES (session) file — the routing output of Freerouting.

We reuse the project's own S-expression parser, then walk ``network_out`` for the
routed ``wire``/``via`` records. Coordinates are converted back to KiCad space
(mm, Y un-negated) using the resolution declared in the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..sexp.parser import parse as sexp_parse

if TYPE_CHECKING:
    from ..sexp import SExp

# Specctra base unit → millimetres.
_UNIT_TO_MM = {
    "um": 0.001,
    "mm": 1.0,
    "cm": 10.0,
    "inch": 25.4,
    "mil": 0.0254,
}


class SesParseError(Exception):
    """Raised when a SES file cannot be parsed."""


@dataclass
class SesWire:
    """A routed polyline on a single copper layer."""

    net_name: str
    layer: str
    width: float  # mm
    points: list[tuple[float, float]] = field(default_factory=list)  # (x_mm, y_mm)


@dataclass
class SesVia:
    """A routed via."""

    net_name: str
    padstack: str
    x: float  # mm
    y: float  # mm


@dataclass
class SesRoute:
    """All routed geometry extracted from a session file."""

    wires: list[SesWire] = field(default_factory=list)
    vias: list[SesVia] = field(default_factory=list)

    @property
    def segment_count(self) -> int:
        return sum(max(0, len(w.points) - 1) for w in self.wires)


def _scale_factor(routes_node: SExp | None) -> float:
    """Compute the file-unit → mm factor from a ``(resolution <unit> <value>)``."""
    unit = "um"
    res = 10.0
    node = routes_node.get("resolution") if routes_node is not None else None
    if node is not None:
        vals = node.atom_values
        if len(vals) >= 1:
            unit = vals[0]
        if len(vals) >= 2:
            try:
                res = float(vals[1])
            except ValueError:
                res = 10.0
    unit_mm = _UNIT_TO_MM.get(unit, 0.001)
    if res == 0:
        res = 1.0
    return unit_mm / res


def _parse_root(text: str) -> SExp:
    try:
        return sexp_parse(text)
    except Exception as exc:  # noqa: BLE001 — surface any parser failure uniformly
        raise SesParseError(f"Failed to parse SES: {exc}") from exc


def infer_units_per_mm(text: str, known_positions: dict[str, tuple[float, float]]) -> float | None:
    """Calibrate the SES coordinate scale from its placement echo.

    Freerouting does not always emit coordinates at the resolution it declares,
    so we recover the true scale by comparing the echoed component placements
    against their known board positions (mm). Returns units-per-mm, or None if
    no component could be matched.
    """
    root = _parse_root(text)
    placement = root.get("placement") if root.name == "session" else None
    if placement is None:
        return None

    ratios: list[float] = []
    for comp in placement.find_all("component"):
        place = comp.get("place")
        if place is None:
            continue
        vals = place.atom_values
        if len(vals) < 3:
            continue
        ref = vals[0]
        known = known_positions.get(ref)
        if known is None:
            continue
        try:
            sx, sy = float(vals[1]), float(vals[2])
        except ValueError:
            continue
        kx, ky = known
        # Y is negated in Specctra space; use magnitudes.
        if abs(kx) > 1e-6:
            ratios.append(abs(sx) / abs(kx))
        if abs(ky) > 1e-6:
            ratios.append(abs(sy) / abs(ky))

    if not ratios:
        return None
    ratios.sort()
    return ratios[len(ratios) // 2]  # median


def parse_ses(text: str, units_per_mm: float | None = None) -> SesRoute:
    """Parse SES text into a :class:`SesRoute` of wires and vias (KiCad mm coords).

    If ``units_per_mm`` is given it overrides the file's declared resolution —
    use :func:`infer_units_per_mm` to calibrate against known placements, which
    is more reliable than trusting Freerouting's resolution token.
    """
    root = _parse_root(text)

    if root.name != "session":
        # Some writers omit a top wrapper; tolerate a bare routes block too.
        routes = root if root.name == "routes" else None
    else:
        routes = root.get("routes")

    if routes is None:
        raise SesParseError("SES file has no (routes ...) block")

    scale = (1.0 / units_per_mm) if units_per_mm else _scale_factor(routes)

    def to_mm_x(v: str) -> float:
        return float(v) * scale

    def to_mm_y(v: str) -> float:
        return -float(v) * scale  # un-negate Y back to KiCad space

    network_out = routes.get("network_out")
    if network_out is None:
        return SesRoute()  # nothing routed

    route = SesRoute()
    for net_node in network_out.find_all("net"):
        net_name = net_node.first_value or ""

        for wire_node in net_node.find_all("wire"):
            path = wire_node.get("path")
            if path is None:
                continue
            vals = path.atom_values
            if len(vals) < 4:
                continue
            layer = vals[0]
            try:
                width = float(vals[1]) * scale
            except ValueError:
                continue
            coords = vals[2:]
            points: list[tuple[float, float]] = []
            for i in range(0, len(coords) - 1, 2):
                try:
                    points.append((to_mm_x(coords[i]), to_mm_y(coords[i + 1])))
                except ValueError:
                    continue
            if len(points) >= 2:
                route.wires.append(
                    SesWire(net_name=net_name, layer=layer, width=width, points=points)
                )

        for via_node in net_node.find_all("via"):
            vals = via_node.atom_values
            if len(vals) < 3:
                continue
            try:
                route.vias.append(
                    SesVia(
                        net_name=net_name,
                        padstack=vals[0],
                        x=to_mm_x(vals[1]),
                        y=to_mm_y(vals[2]),
                    )
                )
            except ValueError:
                continue

    return route
