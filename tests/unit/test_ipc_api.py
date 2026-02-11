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
    """Create a mock kipy footprint object."""
    fp = MagicMock()
    fp.reference_field = MagicMock()
    fp.reference_field.text = reference
    fp.value_field = MagicMock()
    fp.value_field.text = value
    fp.position = MagicMock()
    fp.position.x = x
    fp.position.y = y
    fp.orientation = rotation
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
    return kicad


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

    @patch("kicad_mcp.backends.ipc_api.sys")
    def test_detect_socket_linux(self, mock_sys: MagicMock) -> None:
        """Socket auto-detect returns correct path on Linux."""
        mock_sys.platform = "linux"
        path = IpcBackend._detect_socket()
        assert path == "/tmp/kicad/api.sock"

    @patch("kicad_mcp.backends.ipc_api.sys")
    def test_detect_socket_macos(self, mock_sys: MagicMock) -> None:
        """Socket auto-detect returns correct path on macOS."""
        mock_sys.platform = "darwin"
        path = IpcBackend._detect_socket()
        assert path == "/tmp/kicad/api.sock"

    @patch("kicad_mcp.backends.ipc_api.sys")
    def test_detect_socket_windows(self, mock_sys: MagicMock) -> None:
        """Socket auto-detect returns None on Windows (kipy handles pipes)."""
        mock_sys.platform = "win32"
        path = IpcBackend._detect_socket()
        assert path is None

    @patch.dict("os.environ", {"KICAD_API_SOCKET": "/custom/path.sock"})
    def test_detect_socket_env_var(self) -> None:
        """Socket auto-detect respects KICAD_API_SOCKET env var."""
        path = IpcBackend._detect_socket()
        assert path == "/custom/path.sock"


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

    def test_move_footprint(self) -> None:
        fp = _make_mock_footprint("R1", x=0, y=0)
        board = _make_mock_board([fp])
        ipc, _ = self._connect_with_mock(board)
        ipc.move_footprint("R1", 25.0, 30.0)
        assert fp.position.x == 25.0
        assert fp.position.y == 30.0
        board.update_footprint.assert_called_once_with(fp)

    def test_rotate_footprint(self) -> None:
        fp = _make_mock_footprint("R1")
        board = _make_mock_board([fp])
        ipc, _ = self._connect_with_mock(board)
        ipc.rotate_footprint("R1", 90.0)
        assert fp.orientation == 90.0
        board.update_footprint.assert_called_once_with(fp)

    def test_delete_footprint(self) -> None:
        fp = _make_mock_footprint("R1")
        board = _make_mock_board([fp])
        ipc, _ = self._connect_with_mock(board)
        ipc.delete_footprint("R1")
        board.remove_footprint.assert_called_once_with(fp)

    def test_highlight_items(self) -> None:
        fp1 = _make_mock_footprint("R1")
        fp2 = _make_mock_footprint("C1")
        board = _make_mock_board([fp1, fp2])
        ipc, _ = self._connect_with_mock(board)
        ipc.highlight_items(["R1", "C1"])
        board.set_selection.assert_called_once_with([fp1, fp2])

    def test_highlight_items_partial(self) -> None:
        """Highlighting ignores refs that don't exist on the board."""
        fp1 = _make_mock_footprint("R1")
        board = _make_mock_board([fp1])
        ipc, _ = self._connect_with_mock(board)
        ipc.highlight_items(["R1", "Z99"])
        board.set_selection.assert_called_once_with([fp1])

    def test_clear_selection(self) -> None:
        ipc, board = self._connect_with_mock()
        ipc.clear_selection()
        board.clear_selection.assert_called_once()

    def test_commit_to_undo(self) -> None:
        ipc, board = self._connect_with_mock()
        ipc.commit_to_undo()
        board.commit.assert_called_once()

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
        assert len(cats["ipc_sync"]) == 5
