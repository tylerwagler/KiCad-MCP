"""KiCad IPC API backend — real-time UI sync via kipy (KiCad 9+).

Optional backend that communicates with a running KiCad instance through
its IPC API (protobuf over NNG sockets). Provides live push of changes
to the GUI, selection reading, and component highlighting.

Requires ``kicad-python`` (kipy) >= 0.5, which is an optional dependency.
All operations gracefully degrade when kipy is not installed or KiCad
is not running.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import guard for kipy
_KIPY_AVAILABLE = False
KiCad: Any = None  # Will be set to the real class if kipy is available

try:
    from kipy import KiCad as _KiCadCls  # type: ignore[import-untyped]

    KiCad = _KiCadCls
    _KIPY_AVAILABLE = True
except ImportError:
    pass


class IpcNotAvailable(Exception):
    """Raised when the IPC backend cannot be used."""


class IpcError(Exception):
    """Raised when an IPC operation fails."""


class IpcBackend:
    """Optional backend for real-time KiCad UI sync via IPC API (KiCad 9+).

    Singleton — use ``IpcBackend.get()`` to obtain the shared instance.
    Connection is lazy: call ``connect()`` explicitly, or it will be
    attempted automatically on first operation that needs it.
    """

    _instance: IpcBackend | None = None

    def __init__(self) -> None:
        self._kicad: Any = None  # kipy.KiCad instance
        self._connected: bool = False

    @classmethod
    def get(cls) -> IpcBackend:
        """Return the singleton IpcBackend instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        if cls._instance is not None:
            cls._instance.disconnect()
        cls._instance = None

    def connect(self, socket_path: str | None = None) -> bool:
        """Attempt to connect to KiCad's IPC API.

        Args:
            socket_path: Optional explicit socket/pipe path. If omitted,
                auto-detects from ``KICAD_API_SOCKET`` env var or platform defaults.

        Returns:
            True if connected successfully, False otherwise.
        """
        if self._connected:
            return True

        if not _KIPY_AVAILABLE:
            logger.info("kipy not installed — IPC backend unavailable")
            return False

        if socket_path is None:
            socket_path = self._detect_socket()

        try:
            if socket_path:
                self._kicad = KiCad(socket_path)
            else:
                self._kicad = KiCad()
            self._connected = True
            logger.info("Connected to KiCad IPC API")
            return True
        except Exception as exc:
            logger.info("Failed to connect to KiCad IPC: %s", exc)
            self._kicad = None
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from KiCad's IPC API."""
        self._kicad = None
        self._connected = False

    def is_connected(self) -> bool:
        """Check if currently connected to KiCad."""
        return self._connected and self._kicad is not None

    def require_connection(self) -> None:
        """Raise ``IpcNotAvailable`` if not connected."""
        if not self.is_connected():
            raise IpcNotAvailable(
                "KiCad IPC not available. "
                "Ensure KiCad 9+ is running with IPC enabled, and kipy is installed."
            )

    # ── Socket discovery ────────────────────────────────────────────

    @staticmethod
    def _detect_socket() -> str | None:
        """Auto-detect the KiCad IPC socket path.

        Checks ``KICAD_API_SOCKET`` env var first, then falls back to
        platform-specific default paths.
        """
        env_path = os.environ.get("KICAD_API_SOCKET")
        if env_path:
            return env_path

        if sys.platform == "win32":
            return None  # kipy handles Windows named pipes automatically
        elif sys.platform == "darwin":
            return "/tmp/kicad/api.sock"
        else:
            # Linux
            return "/tmp/kicad/api.sock"

    # ── kipy field helpers ────────────────────────────────────────────

    @staticmethod
    def _fp_ref(fp: Any) -> str:
        """Extract reference designator string from a kipy FootprintInstance."""
        # fp.reference_field.text returns a BoardText; .value is the plain str
        return fp.reference_field.text.value

    @staticmethod
    def _fp_val(fp: Any) -> str:
        """Extract value string from a kipy FootprintInstance."""
        try:
            return fp.value_field.text.value
        except (AttributeError, TypeError):
            return ""

    @staticmethod
    def _nm_to_mm(nm: float) -> float:
        return nm / 1_000_000

    @staticmethod
    def _mm_to_nm(mm: float) -> int:
        return int(mm * 1_000_000)

    # ── Read operations ─────────────────────────────────────────────

    def get_board_state(self) -> dict[str, Any]:
        """Get a board state snapshot from KiCad."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            footprints = board.get_footprints()
            nets = board.get_nets()
            return {
                "footprint_count": len(footprints),
                "net_count": len(nets),
                "footprints": [
                    {
                        "reference": self._fp_ref(fp),
                        "position": {
                            "x": self._nm_to_mm(fp.position.x),
                            "y": self._nm_to_mm(fp.position.y),
                        },
                    }
                    for fp in footprints
                ],
            }
        except Exception as exc:
            raise IpcError(f"Failed to get board state: {exc}") from exc

    def get_footprints(self) -> list[dict[str, Any]]:
        """Get component list from the live KiCad board."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            footprints = board.get_footprints()
            return [
                {
                    "reference": self._fp_ref(fp),
                    "value": self._fp_val(fp),
                    "position": {
                        "x": self._nm_to_mm(fp.position.x),
                        "y": self._nm_to_mm(fp.position.y),
                    },
                    "rotation": fp.orientation if hasattr(fp, "orientation") else 0,
                    "layer": fp.layer if hasattr(fp, "layer") else "",
                }
                for fp in footprints
            ]
        except Exception as exc:
            raise IpcError(f"Failed to get footprints: {exc}") from exc

    def get_selected(self) -> list[dict[str, Any]]:
        """Get items currently selected in KiCad GUI."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            selection = board.get_selection()
            items = []
            for item in selection:
                entry: dict[str, Any] = {"type": type(item).__name__}
                if hasattr(item, "reference_field"):
                    entry["reference"] = self._fp_ref(item)
                if hasattr(item, "position"):
                    entry["position"] = {"x": item.position.x, "y": item.position.y}
                items.append(entry)
            return items
        except Exception as exc:
            raise IpcError(f"Failed to get selection: {exc}") from exc

    # ── Write operations (live push) ────────────────────────────────

    def move_footprint(self, reference: str, x: float, y: float) -> None:
        """Move a footprint to a new position in KiCad GUI."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            fp = self._find_footprint_by_ref(board, reference)
            fp.position.x = self._mm_to_nm(x)
            fp.position.y = self._mm_to_nm(y)
            board.update_footprint(fp)
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to move {reference}: {exc}") from exc

    def rotate_footprint(self, reference: str, angle: float) -> None:
        """Rotate a footprint in KiCad GUI."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            fp = self._find_footprint_by_ref(board, reference)
            fp.orientation = angle
            board.update_footprint(fp)
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to rotate {reference}: {exc}") from exc

    def delete_footprint(self, reference: str) -> None:
        """Delete a footprint from the KiCad board."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            fp = self._find_footprint_by_ref(board, reference)
            board.remove_footprint(fp)
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to delete {reference}: {exc}") from exc

    # ── GUI operations ──────────────────────────────────────────────

    def highlight_items(self, references: list[str]) -> None:
        """Highlight components in KiCad GUI by reference designator."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            items = []
            for ref in references:
                try:
                    fp = self._find_footprint_by_ref(board, ref)
                    items.append(fp)
                except IpcError:
                    logger.warning("Cannot highlight %s: not found", ref)
            if items:
                board.set_selection(items)
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to highlight items: {exc}") from exc

    def clear_selection(self) -> None:
        """Clear the current selection in KiCad GUI."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            board.clear_selection()
        except Exception as exc:
            raise IpcError(f"Failed to clear selection: {exc}") from exc

    def commit_to_undo(self) -> None:
        """Push the current state to KiCad's undo stack."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            board.commit()
        except Exception as exc:
            raise IpcError(f"Failed to commit to undo stack: {exc}") from exc

    # ── Helpers ──────────────────────────────────────────────────────

    @classmethod
    def _find_footprint_by_ref(cls, board: Any, reference: str) -> Any:
        """Find a footprint on the kipy board by reference designator."""
        for fp in board.get_footprints():
            if cls._fp_ref(fp) == reference:
                return fp
        raise IpcError(f"Component {reference!r} not found on the live board")
