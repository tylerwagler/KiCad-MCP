"""Detect KiCad file-format version stamps from the installed kicad-cli.

KiCad S-expression files carry a ``(version YYYYMMDD)`` format epoch and a
``(generator_version "MAJOR.MINOR")`` tag. When a file's format epoch is older
than the installed KiCad, the GUI warns it will be upgraded on save. To avoid
that, files we create should carry the *current* stamps for whatever KiCad is
installed.

The format epoch is an internal constant that is **not** derivable from the
semantic version — the only reliable way to learn it is to ask KiCad. We do so
by seeding a minimal valid file of each type, running ``kicad-cli <type>
upgrade --force`` on it, and reading back the resulting ``(version …)``.

Detection is cached for the process lifetime and degrades gracefully: if
kicad-cli is missing or any probe fails, the hardcoded fallbacks (current as of
KiCad 10) are used so file creation never depends on KiCad being installed.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Fallback stamps — current as of KiCad 10.0. Used when kicad-cli is absent or
# a probe fails. Keep these reasonably fresh so the offline path stays close.
_FALLBACK_PCB_VERSION = "20260206"
_FALLBACK_SCH_VERSION = "20260306"
_FALLBACK_FP_VERSION = "20260206"
_FALLBACK_SYM_VERSION = "20251024"
_FALLBACK_GENERATOR_VERSION = "10.0"

_VERSION_RE = re.compile(r"\(version\s+(\d+)\)")

# Minimal, structurally-complete seed files. Their embedded version is
# irrelevant — ``upgrade --force`` rewrites it to the installed format epoch.
# (Over-minimal hand-written files crash the loader; these include the nodes
# KiCad requires to parse the document.)
_SEED_PCB = """\
(kicad_pcb (version 20200101) (generator "seed") (generator_version "0.0")
  (general (thickness 1.6))
  (paper "A4")
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (44 "Edge.Cuts" user)
  )
  (setup (pad_to_mask_clearance 0))
  (net 0 "")
)
"""

_SEED_SCH = """\
(kicad_sch (version 20200101) (generator "seed") (generator_version "0.0")
  (uuid "00000000-0000-0000-0000-000000000001")
  (paper "A4")
  (lib_symbols)
  (sheet_instances (path "/" (page "1")))
)
"""

_SEED_SYM = """\
(kicad_symbol_lib (version 20200101) (generator "seed") (generator_version "0.0")
  (symbol "SEED"
    (pin_names (offset 0))
    (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "SEED" (at 0 0 0) (effects (font (size 1.27 1.27))))
  )
)
"""

_SEED_FP = """\
(footprint "SEED" (version 20200101) (generator "seed") (generator_version "0.0")
  (layer "F.Cu")
  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
)
"""


@dataclass(frozen=True)
class FormatStamps:
    """Current KiCad file-format version stamps."""

    pcb_version: str
    sch_version: str
    footprint_version: str
    symbol_version: str
    generator_version: str
    detected: bool  # True if probed from kicad-cli, False if all fallbacks


_FALLBACK_STAMPS = FormatStamps(
    pcb_version=_FALLBACK_PCB_VERSION,
    sch_version=_FALLBACK_SCH_VERSION,
    footprint_version=_FALLBACK_FP_VERSION,
    symbol_version=_FALLBACK_SYM_VERSION,
    generator_version=_FALLBACK_GENERATOR_VERSION,
    detected=False,
)


def _parse_generator_version(version_output: str) -> str | None:
    """Turn ``kicad-cli version`` output (e.g. ``10.0.0``) into ``"10.0"``."""
    match = re.search(r"(\d+)\.(\d+)", version_output)
    return f"{match.group(1)}.{match.group(2)}" if match else None


def _probe_version(cli: object, file_type: str, seed: str, tmp: Path) -> str | None:
    """Seed a file, upgrade it, and read back its format epoch.

    Returns the ``YYYYMMDD`` version string, or None if the probe fails.
    """
    # Footprint upgrades operate on a .pretty directory, not a single file.
    if file_type == "fp":
        lib = tmp / "seed.pretty"
        lib.mkdir(exist_ok=True)
        target = lib / "SEED.kicad_mod"
        target.write_text(seed)
        rel = "./seed.pretty"
        read_from = target
    else:
        ext = {"pcb": "kicad_pcb", "sch": "kicad_sch", "sym": "kicad_sym"}[file_type]
        target = tmp / f"seed.{ext}"
        target.write_text(seed)
        rel = f"./seed.{ext}"
        read_from = target

    try:
        cli.upgrade(file_type, rel, cwd=str(tmp))  # type: ignore[attr-defined]
    except Exception:
        return None

    match = _VERSION_RE.search(read_from.read_text())
    return match.group(1) if match else None


@lru_cache(maxsize=1)
def detect_format_stamps() -> FormatStamps:
    """Detect current KiCad format stamps, falling back per-field on failure.

    Cached for the process lifetime. Call ``detect_format_stamps.cache_clear()``
    to force re-detection (e.g. in tests).
    """
    # Local import to avoid a circular import at module load.
    from .kicad_cli import KiCadCli, KiCadCliNotFound

    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return _FALLBACK_STAMPS

    # generator_version from the semantic version string.
    generator_version = _FALLBACK_GENERATOR_VERSION
    try:
        parsed = _parse_generator_version(cli.version())
        if parsed:
            generator_version = parsed
    except Exception:
        pass

    seeds = {
        "pcb": (_SEED_PCB, _FALLBACK_PCB_VERSION),
        "sch": (_SEED_SCH, _FALLBACK_SCH_VERSION),
        "sym": (_SEED_SYM, _FALLBACK_SYM_VERSION),
        "fp": (_SEED_FP, _FALLBACK_FP_VERSION),
    }
    versions: dict[str, str] = {}
    any_detected = False
    with tempfile.TemporaryDirectory(prefix="kicad-fmt-") as tmpdir:
        tmp = Path(tmpdir)
        for ftype, (seed, fallback) in seeds.items():
            probed = _probe_version(cli, ftype, seed, tmp)
            if probed:
                versions[ftype] = probed
                any_detected = True
            else:
                versions[ftype] = fallback

    return FormatStamps(
        pcb_version=versions["pcb"],
        sch_version=versions["sch"],
        footprint_version=versions["fp"],
        symbol_version=versions["sym"],
        generator_version=generator_version,
        detected=any_detected,
    )
