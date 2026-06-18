#!/usr/bin/env python
"""Live verification harness for the kipy (IPC) backend.

Run this on a machine with KiCad open and the IPC API server enabled
(Preferences → Plugins → Enable IPC API Server), with a PCB loaded::

    uv run python scripts/verify_kipy.py            # read-only checks
    uv run python scripts/verify_kipy.py --write    # also test an atomic move (auto-reverted)

It exercises the parts of the kipy integration that the unit tests can only mock —
the actual transport to a running KiCad: connection + version, live-preferred reads
(footprints/nets via the board provider), live geometry reads, and (with --write) an
atomic move committed as one undo step and then reverted.

Nothing is left changed: the --write test moves one footprint by a small delta inside
an atomic commit, verifies it, then moves it back.
"""

from __future__ import annotations

import argparse
import sys

from kicad_mcp import board_provider, state
from kicad_mcp.backends.ipc_api import IpcBackend, IpcError


def _ok(label: str, detail: str = "") -> None:
    print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify the kipy IPC backend against live KiCad")
    ap.add_argument("--write", action="store_true", help="also run an atomic move test (reverted)")
    args = ap.parse_args()

    failures = 0

    print("== 1. Connection ==")
    ipc = IpcBackend.get()
    if not ipc.connect():
        _fail("connect", "KiCad not running, IPC server disabled, or kipy missing")
        print("\nEnable: KiCad → Preferences → Plugins → Enable IPC API Server, then retry.")
        return 1
    _ok("connect")
    info = ipc.version_info()
    _ok("version", f"KiCad {info['kicad_version']} (compatible={info['version_compatible']})")
    if info["version_compatible"] is False:
        _fail("version_compatible", "kipy/KiCad protobuf mismatch — behavior may be unreliable")
        failures += 1

    print("\n== 2. Live-preferred reads (board provider) ==")
    print(f"  active source: {board_provider.active_source()}  (expect 'ipc')")
    # Probe the live path directly so the real IPC error surfaces (the provider
    # otherwise falls back to the parser and hides it).
    try:
        ipc.get_board_state()
    except Exception as exc:  # noqa: BLE001
        _fail("live board access", str(exc))
        print("        Hint: open a .kicad_pcb in the PCB Editor (pcbnew). 'ping'/'version'")
        print("        are served by the API core, but board/document commands need pcbnew open.")
        failures += 1
    try:
        fps = state.get_footprints()
        _ok("get_footprints", f"{len(fps)} components")
        for fp in fps[:5]:
            print(
                f"        {fp.reference:6} {fp.value:12} @({fp.position.x:.3f},"
                f"{fp.position.y:.3f}) {fp.layer}"
            )
        summary = state.get_summary()
        _ok(
            "get_summary",
            f"{summary.footprint_count} fps, {summary.net_count} nets, "
            f"{summary.segment_count} tracks, layers={summary.copper_layers}",
        )
    except Exception as exc:  # noqa: BLE001 — harness reports rather than crashes
        _fail("live reads", str(exc))
        failures += 1
        fps = []

    print("\n== 3. Live geometry reads ==")
    for label, fn in (("tracks", ipc.get_tracks), ("vias", ipc.get_vias), ("zones", ipc.get_zones)):
        try:
            _ok(f"get_{label}", f"{len(fn())} items")
        except IpcError as exc:
            _fail(f"get_{label}", str(exc))
            failures += 1

    if args.write:
        print("\n== 4. Atomic move + revert (write test) ==")
        if not fps:
            _fail("move test", "no footprints to move")
            failures += 1
        else:
            ref = fps[0].reference
            try:
                before = ipc.live_board()
                orig = next(f for f in before.get_footprints() if ipc._fp_ref(f) == ref)
                ox, oy = ipc._nm_to_mm(orig.position.x), ipc._nm_to_mm(orig.position.y)
                ipc.move_footprint(ref, ox + 0.1, oy + 0.1)  # one atomic commit
                moved = next(f for f in ipc.live_board().get_footprints() if ipc._fp_ref(f) == ref)
                mx = ipc._nm_to_mm(moved.position.x)
                if abs(mx - (ox + 0.1)) < 1e-3:
                    _ok("atomic move", f"{ref} moved +0.1mm (one undo step)")
                else:
                    _fail("atomic move", f"{ref} expected {ox + 0.1}, got {mx}")
                    failures += 1
                ipc.move_footprint(ref, ox, oy)  # revert
                _ok("revert move", f"{ref} restored to ({ox:.3f},{oy:.3f})")
            except Exception as exc:  # noqa: BLE001
                _fail("move test", str(exc))
                failures += 1

    print("\n== Summary ==")
    if failures:
        print(f"  {failures} check(s) FAILED — see above.")
        return 1
    print("  All checks passed. The live kipy path works against this KiCad.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
