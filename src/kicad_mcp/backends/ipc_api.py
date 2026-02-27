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

            # Handle type mismatch: kipy.to_mm expects int but nm may be float
            # Preserve precision by checking type first
            if isinstance(nm, float):
                # Convert float nanometers to mm directly
                result = nm / 1_000_000
            else:
                result = to_mm(int(nm))
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
                    "layer": str(track.layer) if hasattr(track, "layer") else "",
                    "net_code": track.net_code if hasattr(track, "net_code") else 0,
                }
                if hasattr(track, "net") and track.net:
                    entry["net_name"] = track.net.name if hasattr(track.net, "name") else ""
                else:
                    entry["net_name"] = ""
                if hasattr(track, "uuid"):
                    entry["uuid"] = str(track.uuid)
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
                    "size": self._nm_to_mm(via.width) if hasattr(via, "width") else 0.0,
                    "drill": self._nm_to_mm(via.drill) if hasattr(via, "drill") else 0.0,
                    "net_code": via.net_code if hasattr(via, "net_code") else 0,
                }
                # Layer span for via
                if hasattr(via, "layer_start") and hasattr(via, "layer_end"):
                    entry["layers"] = {
                        "start": str(via.layer_start),
                        "end": str(via.layer_end),
                    }
                else:
                    entry["layers"] = {"start": "", "end": ""}
                if hasattr(via, "net") and via.net:
                    entry["net_name"] = via.net.name if hasattr(via.net, "name") else ""
                else:
                    entry["net_name"] = ""
                if hasattr(via, "uuid"):
                    entry["uuid"] = str(via.uuid)
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
                entry = {
                    "net_code": zone.net_code if hasattr(zone, "net_code") else 0,
                    "layer": str(zone.layer) if hasattr(zone, "layer") else "",
                    "filled": zone.is_filled if hasattr(zone, "is_filled") else False,
                    "priority": zone.priority if hasattr(zone, "priority") else 0,
                }
                if hasattr(zone, "net") and zone.net:
                    entry["net_name"] = zone.net.name if hasattr(zone.net, "name") else ""
                else:
                    entry["net_name"] = ""
                # Outline points (simplified)
                if hasattr(zone, "outline") and zone.outline:
                    try:
                        points = []
                        for pt in zone.outline:
                            points.append(
                                {
                                    "x": self._nm_to_mm(pt.x),
                                    "y": self._nm_to_mm(pt.y),
                                }
                            )
                        entry["outline_points"] = points
                    except Exception:
                        entry["outline_points"] = []
                else:
                    entry["outline_points"] = []
                if hasattr(zone, "uuid"):
                    entry["uuid"] = str(zone.uuid)
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
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            # Import track class from kipy (TrackSegment doesn't exist - use Track)
            from kipy.board_types import Track

            # Create track object
            segment = Track()
            segment.start = _Vector2.from_xy(self._mm_to_nm(start_x), self._mm_to_nm(start_y))
            segment.end = _Vector2.from_xy(self._mm_to_nm(end_x), self._mm_to_nm(end_y))
            segment.width = self._mm_to_nm(width)
            segment.net_code = net_code  # type: ignore[attr-defined]
            # Layer assignment will depend on kipy API - may need layer enum
            if hasattr(segment, "layer"):
                segment.layer = layer  # type: ignore[assignment]

            # Add to board
            board.create_items(segment)

            # Return UUID for tracking (Track uses 'id' not 'uuid')
            uuid_str = str(segment.id) if hasattr(segment, "id") else ""
            return uuid_str
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to create track segment: {exc}") from exc

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
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            # Import via class from kipy
            from kipy.board_types import Via

            # Create via object (kipy stubs may not match runtime)
            via = Via()
            via.position = _Vector2.from_xy(self._mm_to_nm(x), self._mm_to_nm(y))
            via.width = self._mm_to_nm(size)  # type: ignore[attr-defined]
            via.drill = self._mm_to_nm(drill)  # type: ignore[attr-defined]
            via.net_code = net_code  # type: ignore[attr-defined]
            # Layer span
            if hasattr(via, "layer_start") and hasattr(via, "layer_end"):
                via.layer_start = layers[0]
                via.layer_end = layers[1]

            # Add to board
            board.create_items(via)

            # Return UUID for tracking (Via may have 'id' instead of 'uuid')
            uuid_str = str(via.id) if hasattr(via, "id") else ""
            return uuid_str
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to create via: {exc}") from exc

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
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            # Import zone class from kipy
            from kipy.board_types import Zone

            # Create zone object (kipy stubs may not match runtime)
            zone = Zone()
            zone.net_code = net_code  # type: ignore[attr-defined]
            if hasattr(zone, "layer"):
                zone.layer = layer
            zone.priority = priority

            # Set outline points
            if hasattr(zone, "outline"):
                outline = []
                for x, y in outline_points:
                    pt = _Vector2.from_xy(self._mm_to_nm(x), self._mm_to_nm(y))
                    outline.append(pt)
                zone.outline = outline  # type: ignore[assignment]

            # Minimum thickness
            if hasattr(zone, "min_thickness"):
                zone.min_thickness = self._mm_to_nm(min_thickness)

            # Add to board
            board.create_items(zone)

            # Return UUID for tracking (Zone may have 'id' instead of 'uuid')
            uuid_str = str(zone.id) if hasattr(zone, "id") else ""
            return uuid_str
        except IpcError:
            raise
        except Exception as exc:
            raise IpcError(f"Failed to create zone: {exc}") from exc

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
            Dict with: layer_count, layers (list of layer info dicts)
        """
        self.require_connection()
        try:
            board = self._kicad.get_board()
            layer_count = 2  # Default to 2-layer

            if hasattr(board, "get_copper_layer_count"):
                layer_count = board.get_copper_layer_count()
            elif hasattr(board, "copper_layer_count"):
                layer_count = board.copper_layer_count

            layers = []
            if hasattr(board, "get_board_stackup"):
                stackup = board.get_board_stackup()
                for layer in stackup:
                    layers.append(
                        {
                            "name": str(layer.name) if hasattr(layer, "name") else "",
                            "type": str(layer.type) if hasattr(layer, "type") else "",
                            "thickness": layer.thickness if hasattr(layer, "thickness") else 0,
                        }
                    )

            return {"layer_count": layer_count, "layers": layers}
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
        """Move a footprint to a new position in KiCad GUI."""
        self.require_connection()
        try:
            board = self._kicad.get_board()
            fp = self._find_footprint_by_ref(board, reference)
            fp.position = _Vector2.from_xy(self._mm_to_nm(x), self._mm_to_nm(y))
            board.update_items(fp)
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
            fp.orientation = _Angle.from_degrees(angle)
            board.update_items(fp)
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
            board.remove_items(fp)
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
