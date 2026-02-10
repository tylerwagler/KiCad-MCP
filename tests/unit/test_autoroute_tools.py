"""Tests for auto-routing tool handlers (tools/autoroute.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from kicad_mcp.schema.common import BoundingBox

# Patch paths must target where the import happens: inside the handler functions
# which do `from ..schema.extract import ...`. Since these are lazy imports,
# we patch at the source module level.
_EXTRACT = "kicad_mcp.schema.extract"


class TestAutoRouteNetHandler:
    def test_session_not_found(self) -> None:
        from kicad_mcp.tools.autoroute import _auto_route_net_handler

        with patch("kicad_mcp.tools.autoroute._get_mgr") as mock_mgr:
            mock_mgr.return_value.get_session.side_effect = KeyError("not found")
            result = _auto_route_net_handler(session_id="bad-id", net_name="VCC")
        assert "error" in result
        assert "not found" in result["error"]

    def test_no_board_outline(self) -> None:
        from kicad_mcp.tools.autoroute import _auto_route_net_handler

        mock_session = MagicMock()
        mock_session._working_doc = MagicMock()

        with (
            patch("kicad_mcp.tools.autoroute._get_mgr") as mock_mgr,
            patch(f"{_EXTRACT}.extract_footprints", return_value=[]),
            patch(f"{_EXTRACT}.extract_segments", return_value=[]),
            patch(f"{_EXTRACT}.extract_board_outline", return_value=None),
            patch(f"{_EXTRACT}.extract_nets", return_value=[]),
        ):
            mock_mgr.return_value.get_session.return_value = mock_session
            result = _auto_route_net_handler(session_id="test", net_name="VCC")
        assert "error" in result
        assert "outline" in result["error"].lower()

    def test_no_target_specified(self) -> None:
        from kicad_mcp.tools.autoroute import _auto_route_net_handler

        mock_session = MagicMock()
        mock_session._working_doc = MagicMock()
        bbox = BoundingBox(0, 0, 50, 50)

        with (
            patch("kicad_mcp.tools.autoroute._get_mgr") as mock_mgr,
            patch(f"{_EXTRACT}.extract_footprints", return_value=[]),
            patch(f"{_EXTRACT}.extract_segments", return_value=[]),
            patch(f"{_EXTRACT}.extract_board_outline", return_value=bbox),
            patch(f"{_EXTRACT}.extract_nets", return_value=[]),
        ):
            mock_mgr.return_value.get_session.return_value = mock_session
            result = _auto_route_net_handler(session_id="test")
        assert "error" in result
        assert "Specify" in result["error"]


class TestAutoRouteAllHandler:
    def test_session_not_found(self) -> None:
        from kicad_mcp.tools.autoroute import _auto_route_all_handler

        with patch("kicad_mcp.tools.autoroute._get_mgr") as mock_mgr:
            mock_mgr.return_value.get_session.side_effect = KeyError("not found")
            result = _auto_route_all_handler(session_id="bad-id")
        assert "error" in result

    def test_all_routed(self) -> None:
        from kicad_mcp.tools.autoroute import _auto_route_all_handler

        mock_session = MagicMock()
        mock_session._working_doc = MagicMock()
        bbox = BoundingBox(0, 0, 50, 50)

        with (
            patch("kicad_mcp.tools.autoroute._get_mgr") as mock_mgr,
            patch(f"{_EXTRACT}.extract_footprints", return_value=[]),
            patch(f"{_EXTRACT}.extract_segments", return_value=[]),
            patch(f"{_EXTRACT}.extract_board_outline", return_value=bbox),
        ):
            mock_mgr.return_value.get_session.return_value = mock_session
            mock_mgr.return_value.get_ratsnest.return_value = []
            result = _auto_route_all_handler(session_id="test")
        assert result["status"] == "complete"


class TestPreviewRouteHandler:
    def test_session_not_found(self) -> None:
        from kicad_mcp.tools.autoroute import _preview_route_handler

        with patch("kicad_mcp.tools.autoroute._get_mgr") as mock_mgr:
            mock_mgr.return_value.get_session.side_effect = KeyError("not found")
            result = _preview_route_handler(
                session_id="bad", start_x=0, start_y=0, end_x=10, end_y=10
            )
        assert "error" in result

    def test_preview_returns_distances(self) -> None:
        from kicad_mcp.tools.autoroute import _preview_route_handler

        mock_session = MagicMock()
        mock_session._working_doc = MagicMock()
        bbox = BoundingBox(0, 0, 50, 50)

        with (
            patch("kicad_mcp.tools.autoroute._get_mgr") as mock_mgr,
            patch(f"{_EXTRACT}.extract_footprints", return_value=[]),
            patch(f"{_EXTRACT}.extract_segments", return_value=[]),
            patch(f"{_EXTRACT}.extract_board_outline", return_value=bbox),
        ):
            mock_mgr.return_value.get_session.return_value = mock_session
            result = _preview_route_handler(
                session_id="test",
                start_x=5,
                start_y=5,
                end_x=25,
                end_y=5,
            )
        assert result["status"] == "preview"
        assert result["result"]["manhattan_distance"] == 20.0
        assert result["result"]["straight_line_distance"] == 20.0


class TestToolRegistration:
    def test_tools_registered(self) -> None:
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        assert "auto_route_net" in TOOL_REGISTRY
        assert "auto_route_all" in TOOL_REGISTRY
        assert "preview_route" in TOOL_REGISTRY

    def test_tool_categories(self) -> None:
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        assert TOOL_REGISTRY["auto_route_net"].category == "autoroute"
        assert TOOL_REGISTRY["auto_route_all"].category == "autoroute"
        assert TOOL_REGISTRY["preview_route"].category == "autoroute"

    def test_tools_are_routed(self) -> None:
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        # These should NOT be direct tools (they're routed via meta-tools)
        assert TOOL_REGISTRY["auto_route_net"].direct is False
        assert TOOL_REGISTRY["auto_route_all"].direct is False
        assert TOOL_REGISTRY["preview_route"].direct is False
