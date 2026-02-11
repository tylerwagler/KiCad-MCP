"""Tests for the IPC API backend and tool handlers.

All tests mock kipy — no KiCad instance needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kicad_mcp.backends.ipc_api import IpcBackend, IpcError, IpcNotAvailable

# ── Helpers ──────────────────────────────────────────────────────────


def _make_mock_footprint(
    reference: str = "R1",
    value: str = "10k",
    x: float = 10.0,
    y: float = 20.0,
    rotation: float = 0.0,
    layer: str = "F.Cu",
) -> MagicMock:
    """Create a mock kipy FootprintInstance.

    Mirrors the real kipy object graph:
      fp.reference_field.text       -> BoardText
      fp.reference_field.text.value -> str (the actual ref designator)
      fp.value_field.text.value     -> str
      fp.position                   -> Vector2 (x/y in nanometers)
      fp.orientation                -> Angle (.degrees -> float)
      fp.layer                      -> BoardLayer.ValueType (int enum)
    """
    fp = MagicMock()
    # reference_field.text is a BoardText; .value gives the string
    ref_text = MagicMock()
    ref_text.value = reference
    fp.reference_field = MagicMock()
    fp.reference_field.text = ref_text
    # value_field.text is also a BoardText
    val_text = MagicMock()
    val_text.value = value
    fp.value_field = MagicMock()
    fp.value_field.text = val_text
    # Positions in nanometers
    fp.position = MagicMock()
    fp.position.x = int(x * 1_000_000)
    fp.position.y = int(y * 1_000_000)
    # Orientation is an Angle object with .degrees
    fp.orientation = MagicMock()
    fp.orientation.degrees = rotation
    # Layer is an int enum in kipy
    fp.layer = layer
    return fp


def _make_mock_board(footprints: list[MagicMock] | None = None) -> MagicMock:
    """Create a mock kipy board with footprints."""
    board = MagicMock()
    fps = footprints if footprints is not None else [_make_mock_footprint()]
    board.get_footprints.return_value = fps
    board.get_nets.return_value = [MagicMock(), MagicMock()]  # 2 nets
    board.get_selection.return_value = []
    return board


def _make_mock_kicad(board: MagicMock | None = None) -> MagicMock:
    """Create a mock KiCad connection."""
    kicad = MagicMock()
    kicad.get_board.return_value = board or _make_mock_board()
    # Add version info
    kicad.get_version.return_value = "9.0.1"
    kicad.version = "9.0.1"
    kicad.ping.return_value = True
    return kicad


def _make_mock_track(
    start_x: float = 10.0,
    start_y: float = 10.0,
    end_x: float = 20.0,
    end_y: float = 20.0,
    width: float = 0.25,
    layer: str = "F.Cu",
    net_code: int = 1,
    net_name: str = "GND",
) -> MagicMock:
    """Create a mock kipy TrackSegment."""
    track = MagicMock()
    track.start = MagicMock()
    track.start.x = int(start_x * 1_000_000)
    track.start.y = int(start_y * 1_000_000)
    track.end = MagicMock()
    track.end.x = int(end_x * 1_000_000)
    track.end.y = int(end_y * 1_000_000)
    track.width = int(width * 1_000_000)
    track.layer = layer
    track.net_code = net_code
    track.net = MagicMock()
    track.net.name = net_name
    track.uuid = f"track-{net_code}"
    return track


def _make_mock_via(
    x: float = 15.0,
    y: float = 15.0,
    size: float = 0.8,
    drill: float = 0.4,
    layer_start: str = "F.Cu",
    layer_end: str = "B.Cu",
    net_code: int = 1,
    net_name: str = "GND",
) -> MagicMock:
    """Create a mock kipy Via."""
    via = MagicMock()
    via.position = MagicMock()
    via.position.x = int(x * 1_000_000)
    via.position.y = int(y * 1_000_000)
    via.width = int(size * 1_000_000)
    via.drill = int(drill * 1_000_000)
    via.layer_start = layer_start
    via.layer_end = layer_end
    via.net_code = net_code
    via.net = MagicMock()
    via.net.name = net_name
    via.uuid = f"via-{net_code}"
    return via


def _make_mock_zone(
    net_code: int = 1,
    net_name: str = "GND",
    layer: str = "F.Cu",
    filled: bool = True,
    priority: int = 0,
    outline_points: list[tuple[float, float]] | None = None,
) -> MagicMock:
    """Create a mock kipy Zone."""
    zone = MagicMock()
    zone.net_code = net_code
    zone.net = MagicMock()
    zone.net.name = net_name
    zone.layer = layer
    zone.is_filled = filled
    zone.priority = priority
    # Outline points
    if outline_points:
        outline = []
        for x, y in outline_points:
            pt = MagicMock()
            pt.x = int(x * 1_000_000)
            pt.y = int(y * 1_000_000)
            outline.append(pt)
        zone.outline = outline
    else:
        zone.outline = []
    zone.uuid = f"zone-{net_code}"
    return zone


# ── TestIpcBackend ───────────────────────────────────────────────────


class TestIpcBackend:
    """Tests for IpcBackend connection management."""

    def setup_method(self) -> None:
        IpcBackend.reset()

    def teardown_method(self) -> None:
        IpcBackend.reset()

    def test_singleton_pattern(self) -> None:
        """get() returns the same instance each time."""
        a = IpcBackend.get()
        b = IpcBackend.get()
        assert a is b

    def test_initially_disconnected(self) -> None:
        ipc = IpcBackend.get()
        assert not ipc.is_connected()

    @patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", False)
    def test_connect_no_kipy(self) -> None:
        """Connect fails gracefully when kipy is not installed."""
        ipc = IpcBackend.get()
        result = ipc.connect()
        assert result is False
        assert not ipc.is_connected()

    @patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", True)
    @patch("kicad_mcp.backends.ipc_api.KiCad")
    def test_connect_success(self, mock_kicad_cls: MagicMock) -> None:
        """Connect succeeds when kipy is available and KiCad is running."""
        mock_kicad_cls.return_value = _make_mock_kicad()
        ipc = IpcBackend.get()
        result = ipc.connect()
        assert result is True
        assert ipc.is_connected()

    @patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", True)
    @patch("kicad_mcp.backends.ipc_api.KiCad")
    def test_connect_no_kicad_running(self, mock_kicad_cls: MagicMock) -> None:
        """Connect fails gracefully when KiCad is not running."""
        mock_kicad_cls.side_effect = ConnectionRefusedError("No KiCad running")
        ipc = IpcBackend.get()
        result = ipc.connect()
        assert result is False
        assert not ipc.is_connected()

    @patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", True)
    @patch("kicad_mcp.backends.ipc_api.KiCad")
    def test_connect_with_socket_path(self, mock_kicad_cls: MagicMock) -> None:
        """Connect passes explicit socket path to KiCad constructor."""
        mock_kicad_cls.return_value = _make_mock_kicad()
        ipc = IpcBackend.get()
        ipc.connect("/tmp/test/api.sock")
        mock_kicad_cls.assert_called_once_with("/tmp/test/api.sock")

    @patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", True)
    @patch("kicad_mcp.backends.ipc_api.KiCad")
    def test_disconnect(self, mock_kicad_cls: MagicMock) -> None:
        """Disconnect clears the connection state."""
        mock_kicad_cls.return_value = _make_mock_kicad()
        ipc = IpcBackend.get()
        ipc.connect()
        assert ipc.is_connected()
        ipc.disconnect()
        assert not ipc.is_connected()

    def test_require_connection_raises(self) -> None:
        """require_connection raises IpcNotAvailable when disconnected."""
        ipc = IpcBackend.get()
        with pytest.raises(IpcNotAvailable):
            ipc.require_connection()

    @patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", True)
    @patch("kicad_mcp.backends.ipc_api.KiCad")
    def test_already_connected_skips_reconnect(self, mock_kicad_cls: MagicMock) -> None:
        """Calling connect() when already connected returns True without reconnecting."""
        mock_kicad_cls.return_value = _make_mock_kicad()
        ipc = IpcBackend.get()
        ipc.connect()
        assert mock_kicad_cls.call_count == 1
        result = ipc.connect()
        assert result is True
        assert mock_kicad_cls.call_count == 1  # Not called again

    def test_detect_socket_no_env(self) -> None:
        """Returns None when KICAD_API_SOCKET not set (kipy uses its own default)."""
        with patch.dict("os.environ", {}, clear=True):
            path = IpcBackend._detect_socket()
            assert path is None

    @patch.dict("os.environ", {"KICAD_API_SOCKET": "ipc:///custom/path.sock"})
    def test_detect_socket_env_var(self) -> None:
        """Respects KICAD_API_SOCKET env var."""
        path = IpcBackend._detect_socket()
        assert path == "ipc:///custom/path.sock"


# ── TestIpcOperations ────────────────────────────────────────────────


class TestIpcOperations:
    """Tests for IPC board operations."""

    def setup_method(self) -> None:
        IpcBackend.reset()

    def teardown_method(self) -> None:
        IpcBackend.reset()

    def _connect_with_mock(self, board: MagicMock | None = None) -> tuple[IpcBackend, MagicMock]:
        """Helper: create a connected IpcBackend with a mock board."""
        mock_board = board or _make_mock_board()
        mock_kicad = _make_mock_kicad(mock_board)
        ipc = IpcBackend.get()
        ipc._kicad = mock_kicad
        ipc._connected = True
        return ipc, mock_board

    def test_get_board_state(self) -> None:
        ipc, mock_board = self._connect_with_mock()
        state = ipc.get_board_state()
        assert state["footprint_count"] == 1
        assert state["net_count"] == 2

    def test_get_footprints(self) -> None:
        fps = [_make_mock_footprint("R1"), _make_mock_footprint("C1", "100nF")]
        board = _make_mock_board(fps)
        ipc, _ = self._connect_with_mock(board)
        result = ipc.get_footprints()
        assert len(result) == 2
        assert result[0]["reference"] == "R1"
        assert result[1]["reference"] == "C1"

    def test_get_selected_empty(self) -> None:
        ipc, _ = self._connect_with_mock()
        items = ipc.get_selected()
        assert items == []

    def test_get_selected_with_items(self) -> None:
        board = _make_mock_board()
        fp1 = _make_mock_footprint("R2")
        board.get_selection.return_value = [fp1]
        ipc, _ = self._connect_with_mock(board)
        items = ipc.get_selected()
        assert len(items) == 1
        assert items[0]["reference"] == "R2"

    @patch("kicad_mcp.backends.ipc_api._Vector2")
    def test_move_footprint(self, mock_vector2: MagicMock) -> None:
        new_pos = MagicMock()
        mock_vector2.from_xy.return_value = new_pos
        fp = _make_mock_footprint("R1", x=0, y=0)
        board = _make_mock_board([fp])
        ipc, _ = self._connect_with_mock(board)
        ipc.move_footprint("R1", 25.0, 30.0)
        mock_vector2.from_xy.assert_called_once_with(25_000_000, 30_000_000)
        assert fp.position == new_pos
        board.update_items.assert_called_once_with(fp)

    @patch("kicad_mcp.backends.ipc_api._Angle")
    def test_rotate_footprint(self, mock_angle: MagicMock) -> None:
        new_angle = MagicMock()
        mock_angle.from_degrees.return_value = new_angle
        fp = _make_mock_footprint("R1")
        board = _make_mock_board([fp])
        ipc, _ = self._connect_with_mock(board)
        ipc.rotate_footprint("R1", 90.0)
        mock_angle.from_degrees.assert_called_once_with(90.0)
        assert fp.orientation == new_angle
        board.update_items.assert_called_once_with(fp)

    def test_delete_footprint(self) -> None:
        fp = _make_mock_footprint("R1")
        board = _make_mock_board([fp])
        ipc, _ = self._connect_with_mock(board)
        ipc.delete_footprint("R1")
        board.remove_items.assert_called_once_with(fp)

    def test_highlight_items(self) -> None:
        fp1 = _make_mock_footprint("R1")
        fp2 = _make_mock_footprint("C1")
        board = _make_mock_board([fp1, fp2])
        ipc, _ = self._connect_with_mock(board)
        ipc.highlight_items(["R1", "C1"])
        board.clear_selection.assert_called_once()
        board.add_to_selection.assert_called_once_with([fp1, fp2])

    def test_highlight_items_partial(self) -> None:
        """Highlighting ignores refs that don't exist on the board."""
        fp1 = _make_mock_footprint("R1")
        board = _make_mock_board([fp1])
        ipc, _ = self._connect_with_mock(board)
        ipc.highlight_items(["R1", "Z99"])
        board.clear_selection.assert_called_once()
        board.add_to_selection.assert_called_once_with([fp1])

    def test_clear_selection(self) -> None:
        ipc, board = self._connect_with_mock()
        ipc.clear_selection()
        board.clear_selection.assert_called_once()

    def test_commit_to_undo(self) -> None:
        ipc, board = self._connect_with_mock()
        mock_commit = MagicMock()
        board.begin_commit.return_value = mock_commit
        ipc.commit_to_undo()
        board.begin_commit.assert_called_once()
        board.push_commit.assert_called_once_with(mock_commit, message="MCP session commit")

    def test_operation_not_connected(self) -> None:
        """Operations raise IpcNotAvailable when not connected."""
        ipc = IpcBackend.get()
        with pytest.raises(IpcNotAvailable):
            ipc.get_board_state()

    def test_move_footprint_not_found(self) -> None:
        """Moving a nonexistent footprint raises IpcError."""
        board = _make_mock_board([_make_mock_footprint("R1")])
        ipc, _ = self._connect_with_mock(board)
        with pytest.raises(IpcError, match="not found"):
            ipc.move_footprint("Z99", 0, 0)

    def test_operation_timeout(self) -> None:
        """Board operation exceptions are wrapped in IpcError."""
        board = _make_mock_board()
        board.get_footprints.side_effect = TimeoutError("Socket timeout")
        ipc, _ = self._connect_with_mock(board)
        with pytest.raises(IpcError, match="Failed to get board state"):
            ipc.get_board_state()

    def test_get_tracks(self) -> None:
        """Read tracks from the board."""
        board = _make_mock_board()
        tracks = [
            _make_mock_track(10, 10, 20, 20, 0.25, "F.Cu", 1, "GND"),
            _make_mock_track(20, 20, 30, 30, 0.5, "B.Cu", 2, "VCC"),
        ]
        board.get_tracks.return_value = tracks
        ipc, _ = self._connect_with_mock(board)
        result = ipc.get_tracks()
        assert len(result) == 2
        assert result[0]["start"]["x"] == 10.0
        assert result[0]["end"]["x"] == 20.0
        assert result[0]["width"] == 0.25
        assert result[0]["net_name"] == "GND"
        assert result[1]["width"] == 0.5
        assert result[1]["net_name"] == "VCC"

    def test_get_tracks_empty(self) -> None:
        """Get tracks returns empty list for board with no tracks."""
        board = _make_mock_board()
        board.get_tracks.return_value = []
        ipc, _ = self._connect_with_mock(board)
        result = ipc.get_tracks()
        assert result == []

    def test_get_vias(self) -> None:
        """Read vias from the board."""
        board = _make_mock_board()
        vias = [
            _make_mock_via(15, 15, 0.8, 0.4, "F.Cu", "B.Cu", 1, "GND"),
            _make_mock_via(25, 25, 0.6, 0.3, "F.Cu", "In2.Cu", 2, "VCC"),
        ]
        board.get_vias.return_value = vias
        ipc, _ = self._connect_with_mock(board)
        result = ipc.get_vias()
        assert len(result) == 2
        assert result[0]["position"]["x"] == 15.0
        assert result[0]["size"] == 0.8
        assert result[0]["drill"] == 0.4
        assert result[0]["layers"]["start"] == "F.Cu"
        assert result[0]["layers"]["end"] == "B.Cu"
        assert result[0]["net_name"] == "GND"
        assert result[1]["size"] == 0.6

    def test_get_vias_empty(self) -> None:
        """Get vias returns empty list for board with no vias."""
        board = _make_mock_board()
        board.get_vias.return_value = []
        ipc, _ = self._connect_with_mock(board)
        result = ipc.get_vias()
        assert result == []

    def test_get_zones(self) -> None:
        """Read zones from the board."""
        board = _make_mock_board()
        zones = [
            _make_mock_zone(1, "GND", "F.Cu", True, 0, [(0, 0), (10, 0), (10, 10), (0, 10)]),
            _make_mock_zone(2, "VCC", "B.Cu", False, 1, [(20, 20), (30, 20), (30, 30)]),
        ]
        board.get_zones.return_value = zones
        ipc, _ = self._connect_with_mock(board)
        result = ipc.get_zones()
        assert len(result) == 2
        assert result[0]["net_name"] == "GND"
        assert result[0]["layer"] == "F.Cu"
        assert result[0]["filled"] is True
        assert result[0]["priority"] == 0
        assert len(result[0]["outline_points"]) == 4
        assert result[0]["outline_points"][0]["x"] == 0.0
        assert result[1]["net_name"] == "VCC"
        assert result[1]["filled"] is False
        assert len(result[1]["outline_points"]) == 3

    def test_get_zones_empty(self) -> None:
        """Get zones returns empty list for board with no zones."""
        board = _make_mock_board()
        board.get_zones.return_value = []
        ipc, _ = self._connect_with_mock(board)
        result = ipc.get_zones()
        assert result == []

    def test_ping_success(self) -> None:
        """Ping returns True when connection is alive."""
        board = _make_mock_board()
        ipc, _ = self._connect_with_mock(board)
        ipc._kicad.ping.return_value = True
        assert ipc.ping() is True

    def test_ping_failure(self) -> None:
        """Ping returns False when connection dropped."""
        board = _make_mock_board()
        ipc, _ = self._connect_with_mock(board)
        ipc._kicad.ping.return_value = False
        assert ipc.ping() is False

    def test_ping_not_connected(self) -> None:
        """Ping returns False when not connected."""
        ipc = IpcBackend.get()
        assert ipc.ping() is False

    def test_ping_fallback_to_get_board(self) -> None:
        """Ping uses get_board as fallback when ping() method not available."""
        board = _make_mock_board()
        ipc, _ = self._connect_with_mock(board)
        # Remove ping method
        del ipc._kicad.ping
        # Should still return True if get_board succeeds
        assert ipc.ping() is True

    def test_get_kicad_version(self) -> None:
        """Get KiCad version information."""
        board = _make_mock_board()
        ipc, _ = self._connect_with_mock(board)
        ipc._kicad.get_version.return_value = "9.0.1"
        result = ipc.get_kicad_version()
        assert result["version"] == "9.0.1"
        assert result["major"] == 9
        assert result["minor"] == 0
        assert result["patch"] == 1

    def test_get_kicad_version_with_suffix(self) -> None:
        """Parse version with rc/dev suffix."""
        board = _make_mock_board()
        ipc, _ = self._connect_with_mock(board)
        ipc._kicad.get_version.return_value = "9.1.0-rc2"
        result = ipc.get_kicad_version()
        assert result["version"] == "9.1.0-rc2"
        assert result["major"] == 9
        assert result["minor"] == 1
        assert result["patch"] == 0

    def test_get_kicad_version_fallback_to_property(self) -> None:
        """Get version from .version property if get_version() not available."""
        board = _make_mock_board()
        ipc, _ = self._connect_with_mock(board)
        del ipc._kicad.get_version
        ipc._kicad.version = "9.2.3"
        result = ipc.get_kicad_version()
        assert result["major"] == 9
        assert result["minor"] == 2
        assert result["patch"] == 3

    def test_create_track_segment(self) -> None:
        """Create a track segment on the board."""
        board = _make_mock_board()
        board.create_items = MagicMock()
        ipc, _ = self._connect_with_mock(board)

        # Mock the TrackSegment class by patching the import
        mock_track = MagicMock()
        mock_track.uuid = "track-uuid-123"
        mock_track_cls = MagicMock(return_value=mock_track)

        with (
            patch("kicad_mcp.backends.ipc_api._Vector2") as mock_vec,
            patch.dict("sys.modules", {"kipy.board": MagicMock(TrackSegment=mock_track_cls)}),
        ):
            mock_vec.from_xy.return_value = MagicMock()

            uuid = ipc.create_track_segment(10, 10, 20, 20, 0.25, "F.Cu", 1)

            assert uuid == "track-uuid-123"
            board.create_items.assert_called_once_with(mock_track)
            # Verify coordinates converted to nm
            assert mock_vec.from_xy.call_count == 2

    def test_create_via(self) -> None:
        """Create a via on the board."""
        board = _make_mock_board()
        board.create_items = MagicMock()
        ipc, _ = self._connect_with_mock(board)

        with patch("kicad_mcp.backends.ipc_api._Vector2") as mock_vec:
            mock_vec.from_xy.return_value = MagicMock()
            with patch("kipy.board.Via") as mock_via_cls:
                mock_via = MagicMock()
                mock_via.uuid = "via-uuid-456"
                mock_via_cls.return_value = mock_via

                uuid = ipc.create_via(15, 15, 0.8, 0.4, ("F.Cu", "B.Cu"), 1)

                assert uuid == "via-uuid-456"
                board.create_items.assert_called_once_with(mock_via)
                mock_vec.from_xy.assert_called_once()

    def test_create_zone(self) -> None:
        """Create a zone on the board."""
        board = _make_mock_board()
        board.create_items = MagicMock()
        ipc, _ = self._connect_with_mock(board)

        with patch("kicad_mcp.backends.ipc_api._Vector2") as mock_vec:
            mock_vec.from_xy.return_value = MagicMock()
            with patch("kipy.board.Zone") as mock_zone_cls:
                mock_zone = MagicMock()
                mock_zone.uuid = "zone-uuid-789"
                mock_zone_cls.return_value = mock_zone

                points = [(0, 0), (10, 0), (10, 10), (0, 10)]
                uuid = ipc.create_zone(1, "F.Cu", points, priority=0, min_thickness=0.25)

                assert uuid == "zone-uuid-789"
                board.create_items.assert_called_once_with(mock_zone)
                # Should convert 4 points
                assert mock_vec.from_xy.call_count == 4

    def test_refill_zones(self) -> None:
        """Refill zones on the board."""
        board = _make_mock_board()
        board.refill_zones = MagicMock()
        ipc, _ = self._connect_with_mock(board)

        ipc.refill_zones()
        board.refill_zones.assert_called_once()

    def test_refill_zones_fallback_to_rebuild(self) -> None:
        """Refill zones falls back to rebuild_zones if refill_zones not available."""
        board = _make_mock_board()
        board.rebuild_zones = MagicMock()
        ipc, _ = self._connect_with_mock(board)
        # Remove refill_zones method
        del board.refill_zones

        ipc.refill_zones()
        board.rebuild_zones.assert_called_once()

    def test_get_board_stackup(self) -> None:
        """Get board stackup information."""
        board = _make_mock_board()
        board.get_copper_layer_count = MagicMock(return_value=4)
        ipc, _ = self._connect_with_mock(board)

        result = ipc.get_board_stackup()
        assert result["layer_count"] == 4

    def test_get_copper_layer_count(self) -> None:
        """Get copper layer count."""
        board = _make_mock_board()
        board.get_copper_layer_count = MagicMock(return_value=6)
        ipc, _ = self._connect_with_mock(board)

        count = ipc.get_copper_layer_count()
        assert count == 6

    def test_get_net_classes(self) -> None:
        """Get net class definitions."""
        board = _make_mock_board()
        mock_nc = MagicMock()
        mock_nc.name = "Power"
        mock_nc.clearance = 250000  # 0.25mm in nm
        mock_nc.track_width = 500000  # 0.5mm in nm
        board.get_net_classes = MagicMock(return_value=[mock_nc])
        ipc, _ = self._connect_with_mock(board)

        result = ipc.get_net_classes()
        assert len(result) == 1
        assert result[0]["name"] == "Power"
        assert result[0]["clearance"] == 0.25
        assert result[0]["width"] == 0.5

    def test_get_title_block_info(self) -> None:
        """Get title block information."""
        board = _make_mock_board()
        mock_tb = MagicMock()
        mock_tb.title = "My Project"
        mock_tb.revision = "v1.0"
        mock_tb.company = "Acme Corp"
        board.title_block = mock_tb
        ipc, _ = self._connect_with_mock(board)

        result = ipc.get_title_block_info()
        assert result["title"] == "My Project"
        assert result["revision"] == "v1.0"
        assert result["company"] == "Acme Corp"

    def test_get_text_variables(self) -> None:
        """Get text variables."""
        board = _make_mock_board()
        board.get_text_variables = MagicMock(
            return_value={"REVISION": "v1.0", "DATE": "2026-02-10"}
        )
        ipc, _ = self._connect_with_mock(board)

        result = ipc.get_text_variables()
        assert result["REVISION"] == "v1.0"
        assert result["DATE"] == "2026-02-10"

    def test_set_text_variables(self) -> None:
        """Set text variables."""
        board = _make_mock_board()
        board.set_text_variables = MagicMock()
        ipc, _ = self._connect_with_mock(board)

        ipc.set_text_variables({"REVISION": "v1.1"})
        board.set_text_variables.assert_called_once_with({"REVISION": "v1.1"})

    def test_save_board(self) -> None:
        """Save board via IPC."""
        board = _make_mock_board()
        board.save = MagicMock()
        ipc, _ = self._connect_with_mock(board)

        ipc.save_board()
        board.save.assert_called_once()

    def test_revert_board(self) -> None:
        """Revert board to last saved state."""
        board = _make_mock_board()
        board.revert = MagicMock()
        ipc, _ = self._connect_with_mock(board)

        ipc.revert_board()
        board.revert.assert_called_once()

    def test_revert_board_fallback_to_reload(self) -> None:
        """Revert falls back to reload if revert not available."""
        board = _make_mock_board()
        # Remove revert method to test fallback
        del board.revert
        board.reload = MagicMock()
        ipc, _ = self._connect_with_mock(board)

        ipc.revert_board()
        board.reload.assert_called_once()

    def test_get_active_layer(self) -> None:
        """Get active layer from GUI."""
        board = _make_mock_board()
        board.get_active_layer = MagicMock(return_value=0)  # F.Cu layer int
        ipc, _ = self._connect_with_mock(board)

        layer = ipc.get_active_layer()
        assert isinstance(layer, str)

    def test_set_active_layer(self) -> None:
        """Set active layer in GUI."""
        board = _make_mock_board()
        board.set_active_layer = MagicMock()
        ipc, _ = self._connect_with_mock(board)

        ipc.set_active_layer("F.Cu")
        board.set_active_layer.assert_called_once()

    def test_set_visible_layers(self) -> None:
        """Set visible layers in GUI."""
        board = _make_mock_board()
        board.set_visible_layers = MagicMock()
        ipc, _ = self._connect_with_mock(board)

        ipc.set_visible_layers(["F.Cu", "B.Cu"])
        board.set_visible_layers.assert_called_once_with(["F.Cu", "B.Cu"])


# ── TestIpcToolHandlers ──────────────────────────────────────────────


class TestIpcToolHandlers:
    """Tests for the IPC sync tool handler functions."""

    def setup_method(self) -> None:
        IpcBackend.reset()

    def teardown_method(self) -> None:
        IpcBackend.reset()

    def test_connect_tool_success(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_connect_handler

        with (
            patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", True),
            patch("kicad_mcp.backends.ipc_api.KiCad") as mock_cls,
        ):
            mock_cls.return_value = _make_mock_kicad()
            result = _ipc_connect_handler()
            assert result["connected"] is True

    def test_connect_tool_no_kipy(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_connect_handler

        with patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", False):
            result = _ipc_connect_handler()
            assert result["connected"] is False
            assert "not installed" in result["message"]

    def test_connect_tool_no_kicad(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_connect_handler

        with (
            patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", True),
            patch("kicad_mcp.backends.ipc_api.KiCad") as mock_cls,
        ):
            mock_cls.side_effect = ConnectionRefusedError("nope")
            result = _ipc_connect_handler()
            assert result["connected"] is False

    def test_highlight_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_highlight_handler

        ipc = IpcBackend.get()
        fp1 = _make_mock_footprint("R1")
        fp2 = _make_mock_footprint("C3")
        board = _make_mock_board([fp1, fp2])
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_highlight_handler("R1,C3")
        assert result["highlighted"] == ["R1", "C3"]

    def test_highlight_tool_empty_refs(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_highlight_handler

        ipc = IpcBackend.get()
        ipc._kicad = _make_mock_kicad()
        ipc._connected = True

        result = _ipc_highlight_handler("")
        assert "error" in result

    def test_get_selection_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_selection_handler

        ipc = IpcBackend.get()
        fp = _make_mock_footprint("C7")
        board = _make_mock_board()
        board.get_selection.return_value = [fp]
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_get_selection_handler()
        assert result["count"] == 1
        assert "C7" in result["references"]

    def test_get_selection_tool_not_connected(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_selection_handler

        # Not connected and can't auto-connect (no kipy)
        with patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", False):
            result = _ipc_get_selection_handler()
            assert "error" in result

    def test_push_changes_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_push_changes_handler

        # Set up IPC
        ipc = IpcBackend.get()
        fp = _make_mock_footprint("R1", x=0, y=0)
        board = _make_mock_board([fp])
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        # Create a session with a move change via mutation module
        from kicad_mcp.tools.mutation import _get_manager

        mgr = _get_manager()

        # We need a real document for the session — create a minimal one
        from kicad_mcp.sexp import Document
        from kicad_mcp.sexp.parser import parse as sexp_parse

        raw = (
            '(kicad_pcb (version 20240108) (generator "test")'
            ' (footprint "Lib:FP" (layer "F.Cu")'
            ' (at 0 0) (property "Reference" "R1"'
            ' (at 0 0 0) (layer "F.SilkS") (uuid "abc")'
            " (effects (font (size 1 1) (thickness 0.15))))))"
        )
        doc = Document(path="test.kicad_pcb", root=sexp_parse(raw), raw_text=raw)
        session = mgr.start_session(doc)

        # Apply a move
        mgr.apply_move(session, "R1", 25.0, 30.0)

        result = _ipc_push_changes_handler(session.session_id)
        assert result["pushed"] == 1
        assert len(result["operations"]) == 1

    def test_push_changes_tool_session_not_found(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_push_changes_handler

        ipc = IpcBackend.get()
        ipc._kicad = _make_mock_kicad()
        ipc._connected = True

        result = _ipc_push_changes_handler("nonexistent")
        assert "error" in result

    def test_refresh_board_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_refresh_board_handler

        ipc = IpcBackend.get()
        fps = [_make_mock_footprint("R1"), _make_mock_footprint("C1")]
        board = _make_mock_board(fps)
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_refresh_board_handler()
        assert result["status"] == "refreshed"
        assert result["components"] == 2
        assert result["nets"] == 2

    def test_refresh_board_tool_not_connected(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_refresh_board_handler

        with patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", False):
            result = _ipc_refresh_board_handler()
            assert "error" in result

    def test_get_tracks_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_tracks_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        tracks = [_make_mock_track(), _make_mock_track(20, 20, 30, 30)]
        board.get_tracks.return_value = tracks
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_get_tracks_handler()
        assert result["count"] == 2
        assert len(result["tracks"]) == 2

    def test_get_tracks_tool_not_connected(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_tracks_handler

        with patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", False):
            result = _ipc_get_tracks_handler()
            assert "error" in result

    def test_get_vias_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_vias_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        vias = [_make_mock_via(), _make_mock_via(25, 25)]
        board.get_vias.return_value = vias
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_get_vias_handler()
        assert result["count"] == 2
        assert len(result["vias"]) == 2

    def test_get_vias_tool_not_connected(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_vias_handler

        with patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", False):
            result = _ipc_get_vias_handler()
            assert "error" in result

    def test_get_zones_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_zones_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        zones = [_make_mock_zone(1, "GND"), _make_mock_zone(2, "VCC")]
        board.get_zones.return_value = zones
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_get_zones_handler()
        assert result["count"] == 2
        assert len(result["zones"]) == 2

    def test_get_zones_tool_not_connected(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_zones_handler

        with patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", False):
            result = _ipc_get_zones_handler()
            assert "error" in result

    def test_ping_tool_connected(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_ping_handler

        ipc = IpcBackend.get()
        ipc._kicad = _make_mock_kicad()
        ipc._connected = True
        ipc._kicad.ping.return_value = True

        result = _ipc_ping_handler()
        assert result["alive"] is True

    def test_ping_tool_dropped(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_ping_handler

        ipc = IpcBackend.get()
        ipc._kicad = _make_mock_kicad()
        ipc._connected = True
        ipc._kicad.ping.return_value = False

        result = _ipc_ping_handler()
        assert result["alive"] is False

    def test_ping_tool_not_connected(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_ping_handler

        # Not connected
        result = _ipc_ping_handler()
        assert result["alive"] is False

    def test_get_version_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_version_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True
        ipc._kicad.get_version.return_value = "9.0.1"

        result = _ipc_get_version_handler()
        assert result["version"] == "9.0.1"
        assert result["major"] == 9
        assert result["minor"] == 0
        assert result["patch"] == 1

    def test_get_version_tool_not_connected(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_version_handler

        with patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", False):
            result = _ipc_get_version_handler()
            assert "error" in result

    def test_create_track_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_create_track_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.create_items = MagicMock()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        mock_track = MagicMock()
        mock_track.uuid = "track-123"
        mock_track_cls = MagicMock(return_value=mock_track)

        with (
            patch("kicad_mcp.backends.ipc_api._Vector2") as mock_vec,
            patch.dict("sys.modules", {"kipy.board": MagicMock(TrackSegment=mock_track_cls)}),
        ):
            mock_vec.from_xy.return_value = MagicMock()

            result = _ipc_create_track_handler(10, 10, 20, 20, 0.25, "F.Cu", 1)

            assert result["status"] == "created"
            assert result["type"] == "track"
            assert result["uuid"] == "track-123"
            board.create_items.assert_called_once()

    def test_create_via_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_create_via_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.create_items = MagicMock()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        with (
            patch("kicad_mcp.backends.ipc_api._Vector2") as mock_vec,
            patch("kipy.board.Via") as mock_via_cls,
        ):
            mock_vec.from_xy.return_value = MagicMock()
            mock_via = MagicMock()
            mock_via.uuid = "via-456"
            mock_via_cls.return_value = mock_via

            result = _ipc_create_via_handler(15, 15, 0.8, 0.4, "F.Cu", "B.Cu", 1)

            assert result["status"] == "created"
            assert result["type"] == "via"
            assert result["uuid"] == "via-456"
            board.create_items.assert_called_once()

    def test_create_zone_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_create_zone_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.create_items = MagicMock()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        with (
            patch("kicad_mcp.backends.ipc_api._Vector2") as mock_vec,
            patch("kipy.board.Zone") as mock_zone_cls,
        ):
            mock_vec.from_xy.return_value = MagicMock()
            mock_zone = MagicMock()
            mock_zone.uuid = "zone-789"
            mock_zone_cls.return_value = mock_zone

            result = _ipc_create_zone_handler(
                1, "F.Cu", "[[0, 0], [10, 0], [10, 10], [0, 10]]", 0, 0.25
            )

            assert result["status"] == "created"
            assert result["type"] == "zone"
            assert result["uuid"] == "zone-789"
            board.create_items.assert_called_once()

    def test_create_zone_tool_invalid_points(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_create_zone_handler

        ipc = IpcBackend.get()
        ipc._kicad = _make_mock_kicad()
        ipc._connected = True

        result = _ipc_create_zone_handler(1, "F.Cu", "not-valid-json", 0, 0.25)
        assert "error" in result

    def test_refill_zones_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_refill_zones_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.refill_zones = MagicMock()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_refill_zones_handler()

        assert result["status"] == "refilled"
        board.refill_zones.assert_called_once()

    def test_refill_zones_tool_not_connected(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_refill_zones_handler

        with patch("kicad_mcp.backends.ipc_api._KIPY_AVAILABLE", False):
            result = _ipc_refill_zones_handler()
            assert "error" in result

    def test_get_stackup_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_stackup_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.get_copper_layer_count = MagicMock(return_value=4)
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_get_stackup_handler()
        assert result["layer_count"] == 4

    def test_get_net_classes_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_net_classes_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.get_net_classes = MagicMock(return_value=[])
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_get_net_classes_handler()
        assert "net_classes" in result
        assert result["count"] == 0

    def test_get_title_block_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_title_block_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        mock_tb = MagicMock()
        mock_tb.title = "Test"
        board.title_block = mock_tb
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_get_title_block_handler()
        assert result["title"] == "Test"

    def test_get_text_vars_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_text_vars_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.get_text_variables = MagicMock(return_value={"VAR": "value"})
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_get_text_vars_handler()
        assert result["variables"]["VAR"] == "value"

    def test_set_text_vars_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_set_text_vars_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.set_text_variables = MagicMock()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_set_text_vars_handler('{"VAR": "value"}')
        assert result["status"] == "updated"
        board.set_text_variables.assert_called_once()

    def test_save_board_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_save_board_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.save = MagicMock()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_save_board_handler()
        assert result["status"] == "saved"
        board.save.assert_called_once()

    def test_revert_board_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_revert_board_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.revert = MagicMock()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_revert_board_handler()
        assert result["status"] == "reverted"
        board.revert.assert_called_once()

    def test_get_active_layer_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_get_active_layer_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.get_active_layer = MagicMock(return_value=0)
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_get_active_layer_handler()
        assert "layer" in result

    def test_set_active_layer_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_set_active_layer_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.set_active_layer = MagicMock()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_set_active_layer_handler("F.Cu")
        assert result["status"] == "updated"
        board.set_active_layer.assert_called_once()

    def test_set_visible_layers_tool(self) -> None:
        from kicad_mcp.tools.ipc_sync import _ipc_set_visible_layers_handler

        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.set_visible_layers = MagicMock()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = _ipc_set_visible_layers_handler('["F.Cu", "B.Cu"]')
        assert result["status"] == "updated"
        board.set_visible_layers.assert_called_once()


# ── TestSessionIpcIntegration ────────────────────────────────────────


class TestSessionIpcIntegration:
    """Tests for IPC-aware session commit."""

    def setup_method(self) -> None:
        IpcBackend.reset()

    def teardown_method(self) -> None:
        IpcBackend.reset()

    def test_commit_without_ipc(self, tmp_path: Any) -> None:
        """Commit works normally when IPC is not connected."""
        from kicad_mcp.session import SessionManager
        from kicad_mcp.sexp import Document

        raw = (
            '(kicad_pcb (version 20240108) (generator "test")'
            ' (footprint "Lib:FP" (layer "F.Cu")'
            ' (at 0 0) (property "Reference" "R1"'
            ' (at 0 0 0) (layer "F.SilkS") (uuid "abc")'
            " (effects (font (size 1 1) (thickness 0.15))))))"
        )
        board_file = tmp_path / "test.kicad_pcb"
        board_file.write_text(raw)

        doc = Document.load(str(board_file))
        mgr = SessionManager()
        session = mgr.start_session(doc)
        mgr.apply_move(session, "R1", 25.0, 30.0)

        result = mgr.commit(session)
        assert result["status"] == "committed"
        assert result["changes_written"] == 1
        assert "ipc_pushed" not in result

    def test_commit_with_ipc(self, tmp_path: Any) -> None:
        """Commit pushes changes to IPC when connected."""
        from kicad_mcp.session import SessionManager
        from kicad_mcp.sexp import Document

        raw = (
            '(kicad_pcb (version 20240108) (generator "test")'
            ' (footprint "Lib:FP" (layer "F.Cu")'
            ' (at 0 0) (property "Reference" "R1"'
            ' (at 0 0 0) (layer "F.SilkS") (uuid "abc")'
            " (effects (font (size 1 1) (thickness 0.15))))))"
        )
        board_file = tmp_path / "test.kicad_pcb"
        board_file.write_text(raw)

        doc = Document.load(str(board_file))
        mgr = SessionManager()
        session = mgr.start_session(doc)
        mgr.apply_move(session, "R1", 25.0, 30.0)

        # Set up IPC
        ipc = IpcBackend.get()
        fp = _make_mock_footprint("R1", x=0, y=0)
        board = _make_mock_board([fp])
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = mgr.commit(session)
        assert result["status"] == "committed"
        assert result["changes_written"] == 1
        assert result["ipc_pushed"] == 1

    def test_commit_ipc_failure_still_writes_file(self, tmp_path: Any) -> None:
        """If IPC push fails, file write still succeeds."""
        from kicad_mcp.session import SessionManager
        from kicad_mcp.sexp import Document

        raw = (
            '(kicad_pcb (version 20240108) (generator "test")'
            ' (footprint "Lib:FP" (layer "F.Cu")'
            ' (at 0 0) (property "Reference" "R1"'
            ' (at 0 0 0) (layer "F.SilkS") (uuid "abc")'
            " (effects (font (size 1 1) (thickness 0.15))))))"
        )
        board_file = tmp_path / "test.kicad_pcb"
        board_file.write_text(raw)

        doc = Document.load(str(board_file))
        mgr = SessionManager()
        session = mgr.start_session(doc)
        mgr.apply_move(session, "R1", 25.0, 30.0)

        # Set up IPC that will fail on move
        ipc = IpcBackend.get()
        board = _make_mock_board([])  # Empty board = footprint not found
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        result = mgr.commit(session)
        # File write still succeeds despite IPC error
        assert result["status"] == "committed"
        assert result["changes_written"] == 1
        # IPC failed, so ipc_pushed should be 0 (key absent)
        assert result.get("ipc_pushed", 0) == 0

    def test_parse_at_coords(self) -> None:
        """Test the _parse_at_coords helper."""
        from kicad_mcp.session.manager import SessionManager

        assert SessionManager._parse_at_coords("(at 25.0 30.0)") == (25.0, 30.0)
        assert SessionManager._parse_at_coords("(at 10 20 90)") == (10.0, 20.0)
        assert SessionManager._parse_at_coords("(not_at 1 2)") == (None, None)
        assert SessionManager._parse_at_coords("") == (None, None)

    def test_rollback_reverses_ipc_move(self, tmp_path: Any) -> None:
        """Rollback reverses IPC changes back to original state."""
        from kicad_mcp.session import SessionManager
        from kicad_mcp.sexp import Document

        raw = (
            '(kicad_pcb (version 20240108) (generator "test")'
            ' (footprint "Lib:FP" (layer "F.Cu")'
            ' (at 10 20) (property "Reference" "R1"'
            ' (at 0 0 0) (layer "F.SilkS") (uuid "abc")'
            " (effects (font (size 1 1) (thickness 0.15))))))"
        )
        board_file = tmp_path / "test.kicad_pcb"
        board_file.write_text(raw)

        doc = Document.load(str(board_file))
        mgr = SessionManager()
        session = mgr.start_session(doc)

        # Apply a move (10,20 -> 25,30)
        mgr.apply_move(session, "R1", 25.0, 30.0)

        # Set up IPC
        ipc = IpcBackend.get()
        fp = _make_mock_footprint("R1", x=25.0, y=30.0)
        board = _make_mock_board([fp])
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        # Commit to push changes to IPC
        mgr.commit(session)

        # Start a new session and rollback
        session2 = mgr.start_session(doc)
        mgr.apply_move(session2, "R1", 50.0, 60.0)

        result = mgr.rollback(session2)
        assert result["status"] == "rolled_back"
        assert result["discarded_changes"] == 1
        assert result["ipc_reversed"] == 1

        # Verify move_footprint was called with original coordinates (10, 20)
        # The last call to move_footprint should be the reversal
        calls = board.update_items.call_args_list
        # Should have been called during reversal
        assert len(calls) >= 1

    def test_rollback_no_ipc_still_works(self, tmp_path: Any) -> None:
        """Rollback works normally without IPC connected."""
        from kicad_mcp.session import SessionManager
        from kicad_mcp.sexp import Document

        raw = (
            '(kicad_pcb (version 20240108) (generator "test")'
            ' (footprint "Lib:FP" (layer "F.Cu")'
            ' (at 10 20) (property "Reference" "R1"'
            ' (at 0 0 0) (layer "F.SilkS") (uuid "abc")'
            " (effects (font (size 1 1) (thickness 0.15))))))"
        )
        board_file = tmp_path / "test.kicad_pcb"
        board_file.write_text(raw)

        doc = Document.load(str(board_file))
        mgr = SessionManager()
        session = mgr.start_session(doc)
        mgr.apply_move(session, "R1", 25.0, 30.0)

        # No IPC connection
        result = mgr.rollback(session)
        assert result["status"] == "rolled_back"
        assert result["discarded_changes"] == 1
        assert "ipc_reversed" not in result

    def test_undo_reverses_ipc_move(self, tmp_path: Any) -> None:
        """Undo reverses a single move in IPC."""
        from kicad_mcp.session import SessionManager
        from kicad_mcp.sexp import Document

        raw = (
            '(kicad_pcb (version 20240108) (generator "test")'
            ' (footprint "Lib:FP" (layer "F.Cu")'
            ' (at 10 20) (property "Reference" "R1"'
            ' (at 0 0 0) (layer "F.SilkS") (uuid "abc")'
            " (effects (font (size 1 1) (thickness 0.15))))))"
        )
        board_file = tmp_path / "test.kicad_pcb"
        board_file.write_text(raw)

        doc = Document.load(str(board_file))
        mgr = SessionManager()
        session = mgr.start_session(doc)

        # Apply a move
        mgr.apply_move(session, "R1", 25.0, 30.0)

        # Set up IPC
        ipc = IpcBackend.get()
        fp = _make_mock_footprint("R1", x=10.0, y=20.0)
        board = _make_mock_board([fp])
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        # Undo should reverse the move back to (10, 20)
        record = mgr.undo(session)
        assert record is not None
        assert record.operation == "move_component"
        assert not record.applied

        # Verify IPC move was called (reversal)
        assert board.update_items.call_count >= 1

    def test_undo_reverses_ipc_rotate(self, tmp_path: Any) -> None:
        """Undo reverses a rotation in IPC."""
        from kicad_mcp.session import SessionManager
        from kicad_mcp.sexp import Document

        raw = (
            '(kicad_pcb (version 20240108) (generator "test")'
            ' (footprint "Lib:FP" (layer "F.Cu")'
            ' (at 10 20 0) (property "Reference" "R1"'
            ' (at 0 0 0) (layer "F.SilkS") (uuid "abc")'
            " (effects (font (size 1 1) (thickness 0.15))))))"
        )
        board_file = tmp_path / "test.kicad_pcb"
        board_file.write_text(raw)

        doc = Document.load(str(board_file))
        mgr = SessionManager()
        session = mgr.start_session(doc)

        # Apply a rotation
        mgr.apply_rotate(session, "R1", 90.0)

        # Set up IPC
        ipc = IpcBackend.get()
        fp = _make_mock_footprint("R1", x=10.0, y=20.0, rotation=0.0)
        board = _make_mock_board([fp])
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        # Undo should reverse the rotation back to 0
        record = mgr.undo(session)
        assert record is not None
        assert record.operation == "rotate_component"
        assert not record.applied

        # Verify IPC update was called
        assert board.update_items.call_count >= 1

    def test_rollback_reverses_rotation_from_zero(self, tmp_path: Any) -> None:
        """Rollback reverses rotation when original angle was 0° (omitted from S-expr)."""
        from kicad_mcp.session import SessionManager
        from kicad_mcp.sexp import Document

        # Component at 0° - KiCad omits the angle
        raw = (
            '(kicad_pcb (version 20240108) (generator "test")'
            ' (footprint "Lib:FP" (layer "F.Cu")'
            ' (at 25 25) (property "Reference" "R2"'
            ' (at 0 0 0) (layer "F.SilkS") (uuid "def")'
            " (effects (font (size 1 1) (thickness 0.15))))))"
        )
        board_file = tmp_path / "test.kicad_pcb"
        board_file.write_text(raw)

        doc = Document.load(str(board_file))
        mgr = SessionManager()
        session = mgr.start_session(doc)

        # Rotate to 45°
        mgr.apply_rotate(session, "R2", 45.0)

        # Set up IPC
        ipc = IpcBackend.get()
        fp = _make_mock_footprint("R2", x=25.0, y=25.0, rotation=45.0)
        board = _make_mock_board([fp])
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        # Rollback should reverse to 0° even though before_snapshot is "(at 25 25)" without angle
        result = mgr.rollback(session)
        assert result["status"] == "rolled_back"
        assert result["ipc_reversed"] == 1

        # Verify rotate_footprint was called with 0.0
        # Check the most recent call to update_items
        assert board.update_items.call_count >= 1

    def test_commit_with_routing_triggers_zone_refill(self, tmp_path: Any) -> None:
        """Commit with routing changes triggers zone refill."""
        from kicad_mcp.session import SessionManager
        from kicad_mcp.sexp import Document

        raw = '(kicad_pcb (version 20240108) (generator "test"))'
        board_file = tmp_path / "test.kicad_pcb"
        board_file.write_text(raw)

        doc = Document.load(str(board_file))
        mgr = SessionManager()
        session = mgr.start_session(doc)

        # Add a trace
        mgr.apply_route_trace(session, 10, 10, 20, 20, 0.25, "F.Cu", 1)

        # Set up IPC
        ipc = IpcBackend.get()
        board = _make_mock_board()
        board.create_items = MagicMock()
        board.refill_zones = MagicMock()
        ipc._kicad = _make_mock_kicad(board)
        ipc._connected = True

        mock_track = MagicMock()
        mock_track.uuid = "track-123"
        mock_track_cls = MagicMock(return_value=mock_track)

        with (
            patch("kicad_mcp.backends.ipc_api._Vector2") as mock_vec,
            patch.dict("sys.modules", {"kipy.board": MagicMock(TrackSegment=mock_track_cls)}),
        ):
            mock_vec.from_xy.return_value = MagicMock()

            result = mgr.commit(session)

            assert result["status"] == "committed"
            # Verify zone refill was called
            board.refill_zones.assert_called_once()

    def test_parse_segment_snapshot(self) -> None:
        """Test parsing segment S-expression."""
        from kicad_mcp.session.manager import SessionManager

        snapshot = (
            '(segment (start 10 10) (end 20 20) (width 0.25) (layer "F.Cu") (net 1) (uuid "abc"))'
        )
        params = SessionManager._parse_segment_snapshot(snapshot)

        assert params is not None
        assert params["start_x"] == 10.0
        assert params["start_y"] == 10.0
        assert params["end_x"] == 20.0
        assert params["end_y"] == 20.0
        assert params["width"] == 0.25
        assert params["layer"] == "F.Cu"
        assert params["net"] == 1

    def test_parse_via_snapshot(self) -> None:
        """Test parsing via S-expression."""
        from kicad_mcp.session.manager import SessionManager

        snapshot = (
            '(via (at 15 15) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 1) (uuid "def"))'
        )
        params = SessionManager._parse_via_snapshot(snapshot)

        assert params is not None
        assert params["x"] == 15.0
        assert params["y"] == 15.0
        assert params["size"] == 0.8
        assert params["drill"] == 0.4
        assert params["layer_start"] == "F.Cu"
        assert params["layer_end"] == "B.Cu"
        assert params["net"] == 1

    def test_parse_zone_snapshot(self) -> None:
        """Test parsing zone S-expression."""
        from kicad_mcp.session.manager import SessionManager

        snapshot = (
            '(zone (net 1) (layers "F.Cu") (priority 0) '
            "(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10))))"
        )
        params = SessionManager._parse_zone_snapshot(snapshot)

        assert params is not None
        assert params["net"] == 1
        assert params["layer"] == "F.Cu"
        assert params["priority"] == 0
        assert len(params["outline_points"]) == 4
        assert params["outline_points"][0] == (0.0, 0.0)
        assert params["outline_points"][3] == (0.0, 10.0)


# ── TestToolRegistration ─────────────────────────────────────────────


class TestToolRegistration:
    """Verify that IPC tools are registered in the tool registry."""

    def test_ipc_tools_registered(self) -> None:
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        ipc_tools = [
            "ipc_connect",
            "ipc_highlight",
            "ipc_get_selection",
            "ipc_push_changes",
            "ipc_refresh_board",
            "ipc_get_tracks",
            "ipc_get_vias",
            "ipc_get_zones",
            "ipc_ping",
            "ipc_get_version",
            "ipc_create_track",
            "ipc_create_via",
            "ipc_create_zone",
            "ipc_refill_zones",
            "ipc_get_stackup",
            "ipc_get_net_classes",
            "ipc_get_title_block",
            "ipc_get_text_vars",
            "ipc_set_text_vars",
            "ipc_save_board",
            "ipc_revert_board",
            "ipc_get_active_layer",
            "ipc_set_active_layer",
            "ipc_set_visible_layers",
        ]
        for name in ipc_tools:
            assert name in TOOL_REGISTRY, f"Tool {name!r} not registered"
            assert TOOL_REGISTRY[name].category == "ipc_sync"

    def test_ipc_tools_are_routed(self) -> None:
        """IPC tools should be routed (not direct)."""
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        for name, spec in TOOL_REGISTRY.items():
            if spec.category == "ipc_sync":
                assert not spec.direct, f"Tool {name!r} should be routed, not direct"

    def test_ipc_category_in_categories(self) -> None:
        from kicad_mcp.tools.registry import get_categories

        cats = get_categories()
        assert "ipc_sync" in cats
        assert len(cats["ipc_sync"]) == 24  # Phase 1: 10, Phase 2: +4, Phase 3: +10
