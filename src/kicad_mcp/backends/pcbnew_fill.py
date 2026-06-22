"""Headless copper-zone fill via KiCad's pcbnew module.

``kicad-cli`` has no zone-fill command and the IPC API does not expose the
filler, so the only headless way to compute ``filled_polygon`` geometry is
pcbnew's ``ZONE_FILLER``. pcbnew ships only inside KiCad's Python, which is
usually NOT the interpreter running this server (e.g. a ``uv`` venv). So we use
pcbnew in-process when importable, and otherwise shell out to a Python that has
it (auto-detected, or set ``KICAD_PYTHON``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any

# Runs in whichever interpreter has pcbnew. Prints a marker line we can parse,
# keeping it separate from pcbnew's own stdout/stderr chatter.
_FILL_SCRIPT = r"""
import sys, json, pcbnew
path = sys.argv[1]
board = pcbnew.LoadBoard(path)
count = len(list(board.Zones()))
pcbnew.ZONE_FILLER(board).Fill(board.Zones())
pcbnew.SaveBoard(path, board)
print("FILL_RESULT " + json.dumps({"filled": count}))
"""

_MARKER = "FILL_RESULT "


def is_available() -> bool:
    """Whether pcbnew can be imported in THIS interpreter."""
    try:
        import pcbnew  # noqa: F401

        return True
    except ImportError:
        return False


def _candidate_pythons() -> list[str]:
    """Interpreters that might have pcbnew, most-specific first."""
    candidates = []
    env = os.environ.get("KICAD_PYTHON")
    if env:
        candidates.append(env)
    for name in ("python3", "python"):
        resolved = shutil.which(name)
        if resolved and resolved != sys.executable:
            candidates.append(resolved)
    # Common KiCad-bundled locations.
    candidates += [
        "/usr/bin/python3",
        "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3",
        r"C:\Program Files\KiCad\9.0\bin\python.exe",
        r"C:\Program Files\KiCad\10.0\bin\python.exe",
    ]
    # De-dup, preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _python_with_pcbnew() -> str | None:
    for py in _candidate_pythons():
        try:
            proc = subprocess.run(
                [py, "-c", "import pcbnew"],
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return py
    return None


def fill_zones(board_path: str) -> dict[str, Any]:
    """Fill every copper zone on the board file in place, via pcbnew.

    Runs ``ZONE_FILLER`` over all zones and saves. pcbnew rewrites the file in
    KiCad-canonical form (nets bound by name, canonical layer IDs) — the reader
    handles that form.

    Returns ``{"filled": <zone count>}``.

    Raises:
        RuntimeError: if no interpreter with pcbnew is available, or the fill
            subprocess fails.
    """
    if is_available():
        import pcbnew

        board = pcbnew.LoadBoard(board_path)
        count = len(list(board.Zones()))
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(board_path, board)
        return {"filled": count, "backend": "pcbnew"}

    py = _python_with_pcbnew()
    if py is None:
        raise RuntimeError(
            "No zone-fill engine available. The IPC API (kipy) could not fill "
            "headlessly (KiCad 11+ with 'kicad-cli api-server', or a running "
            "KiCad, is required), and pcbnew (KiCad's Python module, removed in "
            "KiCad 11) was not found in this interpreter or any candidate Python. "
            "Set KICAD_PYTHON to a Python that can 'import pcbnew' on KiCad <= 10."
        )
    try:
        proc = subprocess.run(
            [py, "-c", _FILL_SCRIPT, board_path],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Zone fill subprocess failed: {exc}") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError("Zone fill failed:\n" + "\n".join(tail))
    for line in proc.stdout.splitlines():
        if line.startswith(_MARKER):
            result: dict[str, Any] = json.loads(line[len(_MARKER) :])
            result.setdefault("backend", "pcbnew")
            return result
    raise RuntimeError("Zone fill produced no result marker.")
