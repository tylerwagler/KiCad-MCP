"""KiCad IPC API backend — real-time UI sync via kipy (KiCad 9+).

Optional backend that communicates with a running KiCad instance through
its IPC API (protobuf over NNG sockets). Provides live push of changes
to the GUI, selection reading, and component highlighting.

Requires ``kicad-python`` (kipy) >= 0.5, which is an optional dependency.
All operations gracefully degrade when kipy is not installed or KiCad
is not running.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import guard for kipy
_KIPY_AVAILABLE: bool = False
KiCad: Any = None  # Will be set to the real class if kipy is available
_Angle: Any = None  # Will be set to the real class if kipy is available
_Vector2: Any = None  # Will be set to the real class if kipy is available

try:
    from kipy import KiCad as _KiCadCls
    from kipy.geometry import Angle as _AngleCls
    from kipy.geometry import Vector2 as _Vector2Cls

    KiCad = _KiCadCls
    _Angle = _AngleCls
    _Vector2 = _Vector2Cls
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
        self._version: str | None = None  # KiCad version string, set on connect
        self._version_ok: bool | None = None  # result of kipy check_version()

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

        candidates = [socket_path] if socket_path else self._candidate_sockets()
        board_serving = None  # a live socket that can serve PCB commands
        alive_only = None  # a live socket that answers ping/version but has no board

        for cand in candidates:
            try:
                kc = KiCad(cand) if cand else KiCad()
                # kipy connects lazily — force a round-trip so a dead socket is
                # rejected instead of failing on every later call.
                kc.get_version()
            except Exception:
                continue
            # Prefer a socket that actually serves the PCB. A standalone pcbnew
            # owns its own api-<pid>.sock; the default api.sock is often the
            # project manager, which answers ping/version but has no board handler.
            try:
                kc.get_board()
                board_serving = (kc, cand)
                break
            except Exception:
                if alive_only is None:
                    alive_only = (kc, cand)

        chosen = board_serving or alive_only
        if chosen is None:
            logger.info("Failed to connect to KiCad IPC (no live socket)")
            self._kicad = None
            self._connected = False
            self._version = None
            self._version_ok = None
            return False

        self._kicad, sock = chosen
        self._connected = True
        self._record_version()
        logger.info(
            "Connected to KiCad IPC API (version %s, socket %s, board=%s)",
            self._version or "?",
            sock or "default",
            board_serving is not None,
        )
        return True

    @staticmethod
    def _candidate_sockets() -> list[str | None]:
        """Sockets to try, most board-likely first.

        Honors ``KICAD_API_SOCKET`` if set. Otherwise prefers per-process
        ``api-<pid>.sock`` endpoints (a standalone PCB editor) over the generic
        ``api.sock`` (often the project manager), then kipy's own default.
        """
        env = os.environ.get("KICAD_API_SOCKET")
        if env:
            return [env]
        import glob

        socks = sorted(glob.glob("/tmp/kicad/api-*.sock"), reverse=True)
        candidates: list[str | None] = [f"ipc://{s}" for s in socks]
        candidates.append(None)  # kipy default (/tmp/kicad/api.sock or platform default)
        return candidates

    def _record_version(self) -> None:
        """Capture the KiCad version and kipy compatibility (best-effort)."""
        try:
            self._version = str(self._kicad.get_version())
        except Exception:  # noqa: BLE001 — version reporting is best-effort
            self._version = None
        try:
            # kipy verifies its protobuf is compatible with the running KiCad.
            self._version_ok = bool(self._kicad.check_version())
        except Exception:  # noqa: BLE001 — older kipy/KiCad may lack check_version
            self._version_ok = None
        if self._version_ok is False:
            logger.warning(
                "kipy/KiCad version mismatch (KiCad %s) — IPC behavior may be unreliable",
                self._version or "?",
            )

    def version_info(self) -> dict[str, Any]:
        """Report connection + version/compatibility status for diagnostics."""
        return {
            "connected": self.is_connected(),
            "kicad_version": self._version,
            "version_compatible": self._version_ok,
            "kipy_available": _KIPY_AVAILABLE,
        }

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

    def live_board(self) -> Any:
        """Return the live kipy Board object (raises if not connected)."""
        self.require_connection()
        return self._kicad.get_board()

    # ── Socket discovery ────────────────────────────────────────────

    @staticmethod
    def _detect_socket() -> str | None:
        """Auto-detect the KiCad IPC socket path.

        Checks ``KICAD_API_SOCKET`` env var first. If unset, returns None
        to let kipy use its own platform-specific default (which includes
        the required ``ipc://`` URI prefix).
        """
        return os.environ.get("KICAD_API_SOCKET")

    # ── kipy field helpers ────────────────────────────────────────────

    @staticmethod
    def _fp_ref(fp: Any) -> str:
        """Extract reference designator string from a kipy FootprintInstance."""
        # fp.reference_field.text returns a BoardText; .value is the plain str
        ref_field = getattr(fp, "reference_field", None)
        if ref_field is not None and hasattr(ref_field, "text"):
            text_val = getattr(ref_field.text, "value", None)
            if text_val is not None:
                return str(text_val)
        return ""

    @staticmethod
    def _fp_val(fp: Any) -> str:
        """Extract value string from a kipy FootprintInstance."""
        val_field = getattr(fp, "value_field", None)
        if val_field is not None and hasattr(val_field, "text"):
            text_val = getattr(val_field.text, "value", None)
            if text_val is not None:
                return str(text_val)
        return ""

    @staticmethod
    def _nm_to_mm(nm: float) -> float:
        """Convert nanometers to millimeters.

        Uses kipy.util.units if available, falls back to manual conversion.
        """
        try:
            from kipy.util.units import to_mm

            # kipy.to_mm expects int; for float nm, divide directly to preserve precision.
            result = nm / 1_000_000 if isinstance(nm, float) else to_mm(int(nm))
            return float(result)
        except ImportError:
            return nm / 1_000_000

    @staticmethod
    def _mm_to_nm(mm: float) -> int:
        """Convert millimeters to nanometers.

        Uses kipy.util.units if available, falls back to manual conversion.
        """
        try:
            from kipy.util.units import from_mm

            return from_mm(mm)
        except ImportError:
            return int(mm * 1_000_000)

    @staticmethod
    def _layer_name(layer_int: int) -> str:
        """Convert layer int enum to canonical layer name.

        Uses kipy.util.board_layer if available, falls back to string conversion.
        """
        try:
            from kipy.util.board_layer import canonical_name

            return canonical_name(layer_int)  # type: ignore[arg-type]
        except ImportError:
            return str(layer_int)

    @staticmethod
    def _layer_enum(layer: str) -> int:
        """Convert a canonical layer name (e.g. 'F.Cu') to a kipy BoardLayer enum int."""
        from kipy.util.board_layer import layer_from_canonical_name

        return layer_from_canonical_name(layer)

    @staticmethod
    def _resolve_net(board: Any, net_code: int = 0, net_name: str | None = None) -> Any:
        """Return the live Net object matching a name (preferred) or code.

        A net must be taken from the live board (``Net.code`` is read-only and
        ``Net`` assignment copies the proto). **Net codes are deprecated and slated
        for removal in KiCad 10**, so name matching is preferred; code matching is a
        best-effort fallback for callers that only have a number.
        """
        if not net_name and not net_code:
            return None
        try:
            nets = list(board.get_nets())
        except Exception:  # noqa: BLE001 — net lookup is best-effort
            return None
        if net_name:
            for net in nets:
                if getattr(net, "name", None) == net_name:
                    return net
        if net_code:
            for net in nets:
                with contextlib.suppress(Exception):
                    if int(net.code) == net_code:
                        return net
        return None

    @staticmethod
    def _item_id(created: Any, fallback: Any) -> str:
        """Extract the UUID/KIID string of a newly created item."""
        item = created[0] if isinstance(created, list) and created else fallback
        return str(getattr(item, "id", "") or "")

    @staticmethod
    def _net_of(item: Any) -> tuple[int, str]:
        """Return (code, name) for an item's net.

        Net codes are deprecated in KiCad 10 (reading ``net.code`` emits a warning
        and the value is going away), so we report 0 and treat the **name** as the
        net identity.
        """
        net = getattr(item, "net", None)
        if net is None:
            return 0, ""
        return 0, getattr(net, "name", "") or ""

    # ── Atomic transaction ──────────────────────────────────────────

    @contextlib.contextmanager
    def commit(self, message: str) -> Iterator[Any]:
        """Run edits as one atomic KiCad commit (a single undo-stack entry).

        Yields the live board; ``create_items``/``update_items``/``remove_items``
        called inside the block are pushed together on success, or dropped on error::

            with ipc.commit("MCP: move U1") as board:
                board.update_items(fp)

        This is the correct kipy transaction shape — edits must happen *between*
        ``begin_commit`` and ``push_commit``.
        """
        self.require_connection()
        board = self._kicad.get_board()
        commit_obj = board.begin_commit()
        try:
            yield board
        except Exception:
            with contextlib.suppress(Exception):
                board.drop_commit(commit_obj)
            raise
        else:
            board.push_commit(commit_obj, message)

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
                    "rotation": fp.orientation.degrees if hasattr(fp, "orientation") else 0,
                    "layer": self._layer_name(fp.layer) if hasattr(fp, "layer") else "",
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
                    entry["position"] = {
                        "x": self._nm_to_mm(item.position.x),
                        "y": self._nm_to_mm(item.position.y),
                    }
                items.append(entry)
            return items
        except Exception as exc:
            raise IpcError(f"Failed to get selection: {exc}") from exc

    def get_tracks(self) -> list[dict[str, Any]]:
        """Get all track segments from live board.

        Returns:
            List of dicts with: start, end, width, layer, net_code, net_name, uuid
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            tracks = board.get_tracks()
            result = []
            for track in tracks:
                entry = {
                    "start": {
                        "x": self._nm_to_mm(track.start.x),
                        "y": self._nm_to_mm(track.start.y),
                    },
                    "end": {
                        "x": self._nm_to_mm(track.end.x),
                        "y": self._nm_to_mm(track.end.y),
                    },
                    "width": self._nm_to_mm(track.width),
                    "layer": self._layer_name(track.layer) if hasattr(track, "layer") else "",
                }
                net_code, net_name = self._net_of(track)
                entry["net_code"] = net_code
                entry["net_name"] = net_name
                entry["uuid"] = str(getattr(track, "id", "") or "")
                result.append(entry)
            return result
        except Exception as exc:
            raise IpcError(f"Failed to get tracks: {exc}") from exc

    def get_vias(self) -> list[dict[str, Any]]:
        """Get all vias from live board.

        Returns:
            List of dicts with: position, size, drill, layers (start/end), net_code, net_name, uuid
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            vias = board.get_vias()
            result = []
            for via in vias:
                entry = {
                    "position": {
                        "x": self._nm_to_mm(via.position.x),
                        "y": self._nm_to_mm(via.position.y),
                    },
                    "size": self._nm_to_mm(via.diameter) if hasattr(via, "diameter") else 0.0,
                    "drill": (
                        self._nm_to_mm(via.drill_diameter)
                        if hasattr(via, "drill_diameter")
                        else 0.0
                    ),
                }
                # Layer span derives from the padstack's layer enums (best-effort).
                entry["layers"] = {"start": "", "end": ""}
                with contextlib.suppress(Exception):
                    layers = list(via.padstack.layers)
                    if layers:
                        entry["layers"] = {
                            "start": self._layer_name(layers[0]),
                            "end": self._layer_name(layers[-1]),
                        }
                net_code, net_name = self._net_of(via)
                entry["net_code"] = net_code
                entry["net_name"] = net_name
                entry["uuid"] = str(getattr(via, "id", "") or "")
                result.append(entry)
            return result
        except Exception as exc:
            raise IpcError(f"Failed to get vias: {exc}") from exc

    def get_zones(self) -> list[dict[str, Any]]:
        """Get all copper zones from live board.

        Returns:
            List of dicts with: net_code, net_name, layer, filled, priority, outline_points
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            zones = board.get_zones()
            result = []
            for zone in zones:
                layer_name = ""
                with contextlib.suppress(Exception):
                    zlayers = list(zone.layers)
                    if zlayers:
                        layer_name = self._layer_name(zlayers[0])

                net_code, net_name = self._net_of(zone)
                entry = {
                    "net_code": net_code,
                    "net_name": net_name,
                    "layer": layer_name,
                    "filled": bool(getattr(zone, "filled", False)),
                    "priority": getattr(zone, "priority", 0),
                    "uuid": str(getattr(zone, "id", "") or ""),
                }
                # Outline points from the polygon's PolyLine nodes (best-effort).
                entry["outline_points"] = []
                with contextlib.suppress(Exception):
                    nodes = zone.outline.outline.nodes
                    entry["outline_points"] = [
                        {"x": self._nm_to_mm(n.point.x), "y": self._nm_to_mm(n.point.y)}
                        for n in nodes
                        if getattr(n, "has_point", True)
                    ]
                result.append(entry)
            return result
        except Exception as exc:
            raise IpcError(f"Failed to get zones: {exc}") from exc

    def ping(self) -> bool:
        """Verify active connection to KiCad (not just flag check).

        Returns:
            True if connection is alive, False otherwise.
        """
        if not self._connected or not self._kicad:
            return False
        try:
            # Try to ping the connection
            if hasattr(self._kicad, "ping"):
                result = self._kicad.ping()
                return bool(result)
            # Fallback: try to get board as a health check
            self._kicad.get_board()
            return True
        except Exception:
            return False

    def get_kicad_version(self) -> dict[str, Any]:
        """Get KiCad version info.

        Returns:
            Dict with: version, full_version, major, minor, patch
        """
        self.require_connection()
        try:
            version_str = ""
            if hasattr(self._kicad, "get_version"):
                version_str = self._kicad.get_version()
            elif hasattr(self._kicad, "version"):
                version_str = self._kicad.version

            # Parse version string like "9.0.1" or "9.0.1-rc1"
            parts = version_str.split(".")
            major = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
            minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            patch_str = parts[2].split("-")[0] if len(parts) > 2 else "0"
            patch = int(patch_str) if patch_str.isdigit() else 0

            return {
                "version": version_str,
                "full_version": version_str,
                "major": major,
                "minor": minor,
                "patch": patch,
            }
        except Exception as exc:
            raise IpcError(f"Failed to get KiCad version: {exc}") from exc

    # ── Write operations (live push) ────────────────────────────────

    def create_track_segment(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        width: float,
        layer: str,
        net_code: int,
    ) -> str:
        """Create a track segment and add to board.

        Args:
            start_x: Start X coordinate in mm
            start_y: Start Y coordinate in mm
            end_x: End X coordinate in mm
            end_y: End Y coordinate in mm
            width: Track width in mm
            layer: Layer name (e.g., "F.Cu", "B.Cu")
            net_code: Net code (0 for no net)

        Returns:
            UUID of created segment as string.

        Raises:
            IpcError: If parameters are invalid.
        """
        self.require_connection()

        # Validate coordinates - reasonable board bounds
        for coord_name, coord_val in [
            ("start_x", start_x),
            ("start_y", start_y),
            ("end_x", end_x),
            ("end_y", end_y),
        ]:
            if not isinstance(coord_val, (int, float)):
                raise IpcError(f"{coord_name} must be a number")
            if abs(coord_val) > 10000:
                raise IpcError(f"{coord_name} value {coord_val} outside reasonable bounds")

        # Validate width
        if not isinstance(width, (int, float)):
            raise IpcError("width must be a number")
        if width <= 0:
            raise IpcError(f"width must be positive, got {width}")
        if width > 100:
            raise IpcError(f"width too large: {width}mm (max 100mm)")

        # Validate layer
        if not isinstance(layer, str) or not layer:
            raise IpcError("layer must be a non-empty string")
        if len(layer) > 64:
            raise IpcError(f"layer name too long: {layer}")

        # Validate net_code
        if not isinstance(net_code, int):
            raise IpcError("net_code must be an integer")
        try:
            with self.commit("MCP: add track") as board:
                return self._stage_track(
                    board, start_x, start_y, end_x, end_y, width, layer, net_code
                )
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to create track segment: {exc}") from exc

    def _stage_track(
        self,
        board: Any,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        width: float,
        layer: str,
        net_code: int,
        net_name: str | None = None,
    ) -> str:
        """Create a Track on ``board`` (no commit) — returns the new item id."""
        from kipy.board_types import Track

        seg = Track()
        seg.start = _Vector2.from_xy(self._mm_to_nm(start_x), self._mm_to_nm(start_y))
        seg.end = _Vector2.from_xy(self._mm_to_nm(end_x), self._mm_to_nm(end_y))
        seg.width = self._mm_to_nm(width)
        seg.layer = self._layer_enum(layer)  # type: ignore[assignment]  # enum is int at runtime
        net = self._resolve_net(board, net_code, net_name)
        if net is not None:
            seg.net = net
        created = board.create_items(seg)
        return self._item_id(created, seg)

    def create_via(
        self,
        x: float,
        y: float,
        size: float,
        drill: float,
        layers: tuple[str, str],
        net_code: int,
    ) -> str:
        """Create a via and add to board.

        Args:
            x: X coordinate in mm
            y: Y coordinate in mm
            size: Via size (diameter) in mm
            drill: Drill diameter in mm
            layers: Tuple of (start_layer, end_layer), e.g., ("F.Cu", "B.Cu")
            net_code: Net code (0 for no net)

        Returns:
            UUID of created via as string.

        Raises:
            IpcError: If parameters are invalid.
        """
        self.require_connection()

        # Validate coordinates
        for coord_name, coord_val in [("x", x), ("y", y)]:
            if not isinstance(coord_val, (int, float)):
                raise IpcError(f"{coord_name} must be a number")
            if abs(coord_val) > 10000:
                raise IpcError(f"{coord_name} value {coord_val} outside reasonable bounds")

        # Validate size and drill
        for dim_name, dim_val in [("size", size), ("drill", drill)]:
            if not isinstance(dim_val, (int, float)):
                raise IpcError(f"{dim_name} must be a number")
            if dim_val <= 0:
                raise IpcError(f"{dim_name} must be positive, got {dim_val}")
            if dim_val > 50:
                raise IpcError(f"{dim_name} too large: {dim_val}mm (max 50mm)")

        # Validate layers
        if not isinstance(layers, (tuple, list)) or len(layers) != 2:
            raise IpcError("layers must be a tuple of (start_layer, end_layer)")
        for i, layer in enumerate(layers):
            if not isinstance(layer, str) or not layer:
                raise IpcError(f"layers[{i}] must be a non-empty string")
            if len(layer) > 64:
                raise IpcError(f"layer name too long: {layer}")

        # Validate net_code
        if not isinstance(net_code, int):
            raise IpcError("net_code must be an integer")
        try:
            with self.commit("MCP: add via") as board:
                return self._stage_via(board, x, y, size, drill, net_code)
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to create via: {exc}") from exc

    def _stage_via(
        self,
        board: Any,
        x: float,
        y: float,
        size: float,
        drill: float,
        net_code: int,
        net_name: str | None = None,
    ) -> str:
        """Create a (through) Via on ``board`` (no commit) — returns the new item id.

        Layer span is left at the padstack default (a standard through via). Blind/
        buried spans would require building a custom PadStack and are not handled here.
        """
        from kipy.board_types import Via

        via = Via()
        via.position = _Vector2.from_xy(self._mm_to_nm(x), self._mm_to_nm(y))
        via.diameter = self._mm_to_nm(size)
        via.drill_diameter = self._mm_to_nm(drill)
        net = self._resolve_net(board, net_code, net_name)
        if net is not None:
            via.net = net
        created = board.create_items(via)
        return self._item_id(created, via)

    def create_zone(
        self,
        net_code: int,
        layer: str,
        outline_points: list[tuple[float, float]],
        priority: int = 0,
        min_thickness: float = 0.25,
    ) -> str:
        """Create a copper zone and add to board.

        Args:
            net_code: Net code for the zone
            layer: Layer name (e.g., "F.Cu", "B.Cu")
            outline_points: List of (x, y) coordinate tuples in mm defining the zone boundary
            priority: Zone priority (higher fills first)
            min_thickness: Minimum copper thickness in mm

        Returns:
             UUID of created zone as string.

        Raises:
            IpcError: If parameters are invalid.
        """
        self.require_connection()

        # Validate net_code
        if not isinstance(net_code, int):
            raise IpcError("net_code must be an integer")

        # Validate layer
        if not isinstance(layer, str) or not layer:
            raise IpcError("layer must be a non-empty string")
        if len(layer) > 64:
            raise IpcError(f"layer name too long: {layer}")

        # Validate outline_points
        if not isinstance(outline_points, (list, tuple)):
            raise IpcError("outline_points must be a list or tuple")
        if len(outline_points) < 3:
            raise IpcError("outline_points must have at least 3 points")
        if len(outline_points) > 1000:
            raise IpcError("outline_points too large: max 1000 points")

        for i, point in enumerate(outline_points):
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise IpcError(f"outline_points[{i}] must be a tuple of (x, y)")
            x, y = point
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                raise IpcError(f"outline_points[{i}] coordinates must be numbers")
            if abs(x) > 10000 or abs(y) > 10000:
                raise IpcError(f"outline_points[{i}] coordinates outside reasonable bounds")

        # Validate priority
        if not isinstance(priority, int):
            raise IpcError("priority must be an integer")
        if priority < 0:
            raise IpcError(f"priority must be non-negative, got {priority}")

        # Validate min_thickness
        if not isinstance(min_thickness, (int, float)):
            raise IpcError("min_thickness must be a number")
        if min_thickness <= 0:
            raise IpcError(f"min_thickness must be positive, got {min_thickness}")
        if min_thickness > 10:
            raise IpcError(f"min_thickness too large: {min_thickness}mm (max 10mm)")
        try:
            with self.commit("MCP: add zone") as board:
                return self._stage_zone(
                    board, net_code, layer, outline_points, priority, min_thickness
                )
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to create zone: {exc}") from exc

    def _stage_zone(
        self,
        board: Any,
        net_code: int,
        layer: str,
        outline_points: list[tuple[float, float]],
        priority: int,
        min_thickness: float,
    ) -> str:
        """Create a copper Zone on ``board`` (no commit) — returns the new item id."""
        from kipy.board_types import Zone
        from kipy.geometry import PolygonWithHoles, PolyLineNode

        zone = Zone()
        net = self._resolve_net(board, net_code)
        if net is not None:
            zone.net = net
        # Zone.layers is a repeated enum container.
        zone.layers.append(self._layer_enum(layer))  # type: ignore[attr-defined]  # repeated container
        zone.priority = priority
        zone.min_thickness = self._mm_to_nm(min_thickness)

        poly = PolygonWithHoles()
        for x, y in outline_points:
            poly.outline.append(PolyLineNode.from_xy(self._mm_to_nm(x), self._mm_to_nm(y)))
        poly.outline.closed = True
        zone.outline = poly

        created = board.create_items(zone)
        return self._item_id(created, zone)

    def refill_zones(self) -> None:
        """Trigger zone refill (updates copper pours after routing changes).

        This should be called after adding/modifying tracks or vias to ensure
        zone fills are up-to-date for DRC checks.
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            if hasattr(board, "refill_zones"):
                board.refill_zones()
            elif hasattr(board, "rebuild_zones"):
                board.rebuild_zones()
        except Exception as exc:
            raise IpcError(f"Failed to refill zones: {exc}") from exc

    # ── Metadata operations ─────────────────────────────────────────

    def get_board_stackup(self) -> dict[str, Any]:
        """Get layer stackup information.

        Returns:
            Dict with ``layer_count`` (copper count), ``copper_layers`` (canonical
            names, e.g. ['F.Cu', 'B.Cu']), and ``layers`` (full per-layer dicts).
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()

            copper_layers: list[str] = []
            layers: list[dict[str, Any]] = []
            with contextlib.suppress(Exception):
                for lyr in board.get_stackup().layers:
                    name = self._layer_name(lyr.layer)
                    is_copper = getattr(lyr, "material_name", "") == "copper"
                    layers.append(
                        {
                            "name": name,
                            "user_name": getattr(lyr, "user_name", ""),
                            "thickness": getattr(lyr, "thickness", 0),
                            "copper": is_copper,
                        }
                    )
                    if is_copper and name not in copper_layers:
                        copper_layers.append(name)

            layer_count = len(copper_layers)
            if not layer_count:
                with contextlib.suppress(Exception):
                    layer_count = int(board.get_copper_layer_count())
            return {
                "layer_count": layer_count or 2,
                "copper_layers": copper_layers,
                "layers": layers,
            }
        except Exception as exc:
            raise IpcError(f"Failed to get board stackup: {exc}") from exc

    def get_copper_layer_count(self) -> int:
        """Get number of copper layers (2, 4, 6, etc.).

        Returns:
            Number of copper layers.
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            if hasattr(board, "get_copper_layer_count"):
                result = board.get_copper_layer_count()
                return int(result)
            if hasattr(board, "copper_layer_count"):
                return int(board.copper_layer_count)
            return 2  # Default fallback
        except Exception as exc:
            raise IpcError(f"Failed to get copper layer count: {exc}") from exc

    def get_net_classes(self) -> list[dict[str, Any]]:
        """Get net class definitions.

        Returns:
            List of net class dicts with: name, clearance, width, via_size, via_drill, nets
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            net_classes = []

            if hasattr(board, "get_net_classes"):
                for nc in board.get_net_classes():
                    entry: dict[str, Any] = {"name": str(nc.name) if hasattr(nc, "name") else ""}
                    if hasattr(nc, "clearance"):
                        entry["clearance"] = self._nm_to_mm(nc.clearance)
                    if hasattr(nc, "track_width"):
                        entry["width"] = self._nm_to_mm(nc.track_width)
                    if hasattr(nc, "via_size"):
                        entry["via_size"] = self._nm_to_mm(nc.via_size)
                    if hasattr(nc, "via_drill"):
                        entry["via_drill"] = self._nm_to_mm(nc.via_drill)
                    if hasattr(nc, "nets"):
                        entry["nets"] = [str(n) for n in nc.nets]
                    net_classes.append(entry)

            return net_classes
        except Exception as exc:
            raise IpcError(f"Failed to get net classes: {exc}") from exc

    def get_title_block_info(self) -> dict[str, Any]:
        """Get title block fields.

        Returns:
            Dict with: title, revision, date, company, comment1-9
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            info: dict[str, Any] = {}

            if hasattr(board, "title_block") or hasattr(board, "get_title_block"):
                tb = board.title_block if hasattr(board, "title_block") else board.get_title_block()
                if hasattr(tb, "title"):
                    info["title"] = str(tb.title)
                if hasattr(tb, "revision"):
                    info["revision"] = str(tb.revision)
                if hasattr(tb, "date"):
                    info["date"] = str(tb.date)
                if hasattr(tb, "company"):
                    info["company"] = str(tb.company)
                # Comments
                for i in range(1, 10):
                    comment_attr = f"comment{i}"
                    if hasattr(tb, comment_attr):
                        info[comment_attr] = str(getattr(tb, comment_attr))

            return info
        except Exception as exc:
            raise IpcError(f"Failed to get title block info: {exc}") from exc

    def get_text_variables(self) -> dict[str, str]:
        """Get project text variables like ${REVISION}, ${DATE}.

        Returns:
            Dict mapping variable names to values.
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            variables: dict[str, str] = {}

            if hasattr(board, "get_text_variables"):
                vars_dict = board.get_text_variables()
                for key, value in vars_dict.items():
                    variables[str(key)] = str(value)

            return variables
        except Exception as exc:
            raise IpcError(f"Failed to get text variables: {exc}") from exc

    def set_text_variables(self, variables: dict[str, str]) -> None:
        """Set project text variables.

        Args:
            variables: Dict mapping variable names to values.

        Raises:
            IpcError: If variables are invalid or IPC operation fails.
        """
        self.require_connection()

        # Validate input
        for key, value in variables.items():
            if not isinstance(key, str) or not key:
                raise IpcError("Variable name must be a non-empty string")
            if not isinstance(value, str):
                raise IpcError(f"Variable value for '{key}' must be a string")
            # KiCad variable names have length limits
            if len(key) > 255:
                raise IpcError(f"Variable name too long: {key}")
            if len(value) > 1024:
                raise IpcError(f"Variable value for '{key}' too long")

        try:
            board = self._kicad.get_board()
            if hasattr(board, "set_text_variables"):
                board.set_text_variables(variables)
        except Exception as exc:
            raise IpcError(f"Failed to set text variables: {exc}") from exc

    # ── Board operations ────────────────────────────────────────────

    def save_board(self) -> None:
        """Save board via IPC (no kicad-cli needed)."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            if hasattr(board, "save"):
                board.save()
            else:
                raise IpcError("Board save not supported by this KiCad version")
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to save board: {exc}") from exc

    def revert_board(self) -> None:
        """Revert board to last saved state."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            if hasattr(board, "revert"):
                board.revert()
            elif hasattr(board, "reload"):
                board.reload()
            else:
                raise IpcError("Board revert not supported by this KiCad version")
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to revert board: {exc}") from exc

    # ── GUI control ─────────────────────────────────────────────────

    def get_active_layer(self) -> str:
        """Get currently active layer in GUI.

        Returns:
            Layer name (e.g., "F.Cu", "B.Cu").
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            if hasattr(board, "get_active_layer"):
                layer_int = board.get_active_layer()
                return self._layer_name(layer_int)
            return ""
        except Exception as exc:
            raise IpcError(f"Failed to get active layer: {exc}") from exc

    def set_active_layer(self, layer: str) -> None:
        """Set active layer in GUI.

        Args:
            layer: Layer name (e.g., "F.Cu", "B.Cu").
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            if hasattr(board, "set_active_layer"):
                board.set_active_layer(layer)
        except Exception as exc:
            raise IpcError(f"Failed to set active layer: {exc}") from exc

    def set_visible_layers(self, layers: list[str]) -> None:
        """Control layer visibility in GUI.

        Args:
            layers: List of layer names to make visible.
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            if hasattr(board, "set_visible_layers"):
                board.set_visible_layers(layers)
        except Exception as exc:
            raise IpcError(f"Failed to set visible layers: {exc}") from exc

    def move_footprint(self, reference: str, x: float, y: float) -> None:
        """Move a footprint to a new position in KiCad GUI (atomic commit)."""
        self.require_connection()
        try:
            with self.commit(f"MCP: move {reference}") as board:
                self._stage_move(board, reference, x, y)
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to move {reference}: {exc}") from exc

    def _stage_move(self, board: Any, reference: str, x: float, y: float) -> None:
        """Move a footprint on ``board`` (no commit)."""
        fp = self._find_footprint_by_ref(board, reference)
        fp.position = _Vector2.from_xy(self._mm_to_nm(x), self._mm_to_nm(y))
        board.update_items(fp)

    def rotate_footprint(self, reference: str, angle: float) -> None:
        """Rotate a footprint in KiCad GUI (atomic commit)."""
        self.require_connection()
        try:
            with self.commit(f"MCP: rotate {reference}") as board:
                self._stage_rotate(board, reference, angle)
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to rotate {reference}: {exc}") from exc

    def _stage_rotate(self, board: Any, reference: str, angle: float) -> None:
        """Rotate a footprint on ``board`` (no commit)."""
        fp = self._find_footprint_by_ref(board, reference)
        fp.orientation = _Angle.from_degrees(angle)
        board.update_items(fp)

    def delete_footprint(self, reference: str) -> None:
        """Delete a footprint from the KiCad board (atomic commit)."""
        self.require_connection()
        try:
            with self.commit(f"MCP: delete {reference}") as board:
                self._stage_delete(board, reference)
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to delete {reference}: {exc}") from exc

    def _stage_delete(self, board: Any, reference: str) -> None:
        """Delete a footprint on ``board`` (no commit)."""
        fp = self._find_footprint_by_ref(board, reference)
        board.remove_items(fp)

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
                board.clear_selection()
                board.add_to_selection(items)
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
            commit = board.begin_commit()
            board.push_commit(commit, message="MCP session commit")
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
