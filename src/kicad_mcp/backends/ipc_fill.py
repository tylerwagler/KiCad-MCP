"""Headless copper-zone fill via the KiCad IPC API (kipy).

KiCad 11 removes the SWIG ``pcbnew`` module; the IPC API is its replacement.
``Board.refill_zones()`` recomputes the filled polygons and ``Board.save()``
persists them — both present since kipy 0.7. The only wrinkle is *headless*
operation (no GUI), which needs a server for kipy to talk to. Two transports,
newest first:

1. kipy's own ``KiCad(headless=True, file_path=...)``, which auto-spawns
   ``kicad-cli api-server`` (kipy > 0.7.1 / ``main`` branch).
2. We spawn ``kicad-cli api-server --socket <sock> <board>`` ourselves and
   connect kipy to that socket (KiCad 11 + kipy 0.7.1, which lacks the ctor).

Both target a specific board file, so we never touch an ambient GUI session and
never risk saving over someone's unsaved live edits. ``fill_zones`` returns
``None`` when no IPC transport exists (kipy missing, or KiCad <= 10 with no
``api-server``), so the caller can fall back to pcbnew.
"""

from __future__ import annotations

import contextlib
import inspect
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any


def _kipy_kicad() -> Any | None:
    """Return the kipy ``KiCad`` class, or None if kipy is not installed."""
    try:
        from kipy import KiCad

        return KiCad
    except ImportError:
        return None


def _ctor_supports_headless(kicad_cls: Any) -> bool:
    """Whether ``KiCad.__init__`` accepts a ``headless`` parameter (kipy > 0.7.1)."""
    try:
        return "headless" in inspect.signature(kicad_cls.__init__).parameters
    except (TypeError, ValueError):
        return False


def _kicad_cli_has_api_server() -> bool:
    """Whether the installed ``kicad-cli`` exposes ``api-server`` (KiCad 11+)."""
    cli = shutil.which("kicad-cli")
    if not cli:
        return False
    try:
        proc = subprocess.run(
            [cli, "api-server", "--help"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def is_available() -> bool:
    """Whether any headless IPC fill transport exists on this install."""
    if _kipy_kicad() is None:
        return False
    return _ctor_supports_headless(_kipy_kicad()) or _kicad_cli_has_api_server()


def _refill_and_save(kc: Any) -> dict[str, Any]:
    """Refill all zones on the connected board and save to disk."""
    board = kc.get_board()
    count = len(list(board.get_zones()))
    board.refill_zones(block=True)
    board.save()
    return {"filled": count, "backend": "ipc"}


def _close(kc: Any) -> None:
    """Best-effort close of a kipy connection (it also closes on GC)."""
    with contextlib.suppress(Exception):
        close = getattr(kc, "close", None)
        if callable(close):
            close()


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """Stop a spawned api-server, escalating to kill if it ignores terminate."""
    with contextlib.suppress(Exception):
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _connect_with_retry(
    kicad_cls: Any,
    socket_uri: str,
    proc: subprocess.Popen[bytes],
    timeout: float = 30.0,
) -> Any | None:
    """Poll until the spawned api-server answers, or the server dies / times out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None  # server exited before becoming ready
        try:
            kc = kicad_cls(socket_uri)
            kc.get_version()
            kc.get_board()
            return kc
        except Exception:
            time.sleep(0.5)
    return None


def _fill_via_spawned_server(board_path: str, kicad_cls: Any) -> dict[str, Any]:
    """Spawn our own ``kicad-cli api-server``, fill, save, and tear it down."""
    cli = shutil.which("kicad-cli")
    if cli is None:  # pragma: no cover — guarded by _kicad_cli_has_api_server
        raise RuntimeError("kicad-cli not found")

    sock_dir = tempfile.mkdtemp(prefix="kicad-mcp-fill-")
    sock = os.path.join(sock_dir, "api.sock")
    proc = subprocess.Popen(
        [cli, "api-server", "--socket", sock, board_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        kc = _connect_with_retry(kicad_cls, f"ipc://{sock}", proc)
        if kc is None:
            tail = ""
            if proc.stderr is not None:
                with contextlib.suppress(Exception):
                    tail = proc.stderr.read().decode(errors="replace").strip()[-300:]
            raise RuntimeError(
                "kicad-cli api-server did not become ready" + (f":\n{tail}" if tail else "")
            )
        try:
            return _refill_and_save(kc)
        finally:
            _close(kc)
    finally:
        _terminate(proc)
        shutil.rmtree(sock_dir, ignore_errors=True)


def fill_zones(board_path: str) -> dict[str, Any] | None:
    """Fill every copper zone on the board file via the IPC API (kipy), headless.

    Returns ``{"filled": <count>, "backend": "ipc"}`` on success, or ``None`` if
    no headless IPC transport is available on this install (the caller should
    then fall back to pcbnew). Raises ``RuntimeError`` only when a transport is
    present but the fill itself fails.
    """
    kicad_cls = _kipy_kicad()
    if kicad_cls is None:
        return None  # kipy not installed

    # Transport 1: kipy auto-spawns the server for us (future kipy).
    if _ctor_supports_headless(kicad_cls):
        kc = kicad_cls(headless=True, file_path=board_path)
        try:
            return _refill_and_save(kc)
        finally:
            _close(kc)

    # Transport 2: we own the api-server (KiCad 11 + kipy 0.7.1).
    if _kicad_cli_has_api_server():
        return _fill_via_spawned_server(board_path, kicad_cls)

    return None  # no headless IPC path (e.g. KiCad <= 10)
