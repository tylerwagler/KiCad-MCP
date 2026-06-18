"""Specctra DSN/SES support for autorouter interchange (Freerouting).

- :mod:`dsn` generates a Specctra ``.dsn`` design file from a parsed board.
- :mod:`ses` parses a Specctra ``.ses`` session file (router output) back into
  trace/via geometry in KiCad coordinates.

Coordinate convention (matches KiCad's own Specctra exporter):
- Units are ``(resolution um 10)`` → 1 file unit = 0.1 µm. So mm × 10000 = file units.
- The Y axis is negated relative to KiCad (Specctra Y grows upward).
"""

from __future__ import annotations

from .dsn import DsnExportError, DsnOptions, board_to_dsn
from .ses import SesParseError, SesRoute, SesVia, SesWire, infer_units_per_mm, parse_ses

__all__ = [
    "DsnExportError",
    "DsnOptions",
    "SesParseError",
    "SesRoute",
    "SesVia",
    "SesWire",
    "board_to_dsn",
    "infer_units_per_mm",
    "parse_ses",
]
