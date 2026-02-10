"""Tests for auto-placement tool handlers (tools/autoplacement.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from kicad_mcp.schema.board import Footprint, Pad
from kicad_mcp.schema.common import BoundingBox, Position

_EXTRACT = "kicad_mcp.schema.extract"


def _make_footprints() -> list[Footprint]:
    """Create test footprints with shared nets."""
    pad1 = Pad("1", "smd", "rect", Position(0, 0), (1, 1), ["F.Cu"], 1)
    pad2 = Pad("2", "smd", "rect", Position(2, 0), (1, 1), ["F.Cu"], 2)
    return [
        Footprint("R", "R1", "10k", Position(10, 10), "F.Cu", [pad1, pad2]),
        Footprint("R", "R2", "22k", Position(50, 50), "F.Cu", [pad1, pad2]),
    ]


class TestOptimizePlacementHandler:
    def test_session_not_found(self) -> None:
        from kicad_mcp.tools.autoplacement import _optimize_placement_handler

        with patch("kicad_mcp.tools.autoplacement._get_mgr") as mock_mgr:
            mock_mgr.return_value.get_session.side_effect = KeyError("not found")
            result = _optimize_placement_handler(session_id="bad-id")
        assert "error" in result
        assert "not found" in result["error"]

    def test_no_board_outline(self) -> None:
        from kicad_mcp.tools.autoplacement import _optimize_placement_handler

        mock_session = MagicMock()
        mock_session._working_doc = MagicMock()

        with (
            patch("kicad_mcp.tools.autoplacement._get_mgr") as mock_mgr,
            patch(
                f"{_EXTRACT}.extract_footprints",
                return_value=_make_footprints(),
            ),
            patch(
                f"{_EXTRACT}.extract_board_outline",
                return_value=None,
            ),
        ):
            mock_mgr.return_value.get_session.return_value = mock_session
            result = _optimize_placement_handler(session_id="test")
        assert "error" in result
        assert "outline" in result["error"].lower()

    def test_preview_mode(self) -> None:
        from kicad_mcp.tools.autoplacement import _optimize_placement_handler

        mock_session = MagicMock()
        mock_session._working_doc = MagicMock()
        bbox = BoundingBox(0, 0, 100, 100)

        with (
            patch("kicad_mcp.tools.autoplacement._get_mgr") as mock_mgr,
            patch(
                f"{_EXTRACT}.extract_footprints",
                return_value=_make_footprints(),
            ),
            patch(
                f"{_EXTRACT}.extract_board_outline",
                return_value=bbox,
            ),
        ):
            mock_mgr.return_value.get_session.return_value = mock_session
            result = _optimize_placement_handler(session_id="test", apply=False, max_iterations=50)
        assert result["status"] == "preview"
        assert "result" in result

    def test_no_components(self) -> None:
        from kicad_mcp.tools.autoplacement import _optimize_placement_handler

        mock_session = MagicMock()
        mock_session._working_doc = MagicMock()
        bbox = BoundingBox(0, 0, 100, 100)

        with (
            patch("kicad_mcp.tools.autoplacement._get_mgr") as mock_mgr,
            patch(
                f"{_EXTRACT}.extract_footprints",
                return_value=[],
            ),
            patch(
                f"{_EXTRACT}.extract_board_outline",
                return_value=bbox,
            ),
        ):
            mock_mgr.return_value.get_session.return_value = mock_session
            result = _optimize_placement_handler(session_id="test")
        assert "error" in result


class TestEvaluatePlacementHandler:
    def test_session_not_found(self) -> None:
        from kicad_mcp.tools.autoplacement import _evaluate_placement_handler

        with patch("kicad_mcp.tools.autoplacement._get_mgr") as mock_mgr:
            mock_mgr.return_value.get_session.side_effect = KeyError("not found")
            result = _evaluate_placement_handler(session_id="bad-id")
        assert "error" in result

    def test_evaluate_returns_metrics(self) -> None:
        from kicad_mcp.tools.autoplacement import _evaluate_placement_handler

        mock_session = MagicMock()
        mock_session._working_doc = MagicMock()
        bbox = BoundingBox(0, 0, 100, 100)

        with (
            patch("kicad_mcp.tools.autoplacement._get_mgr") as mock_mgr,
            patch(
                f"{_EXTRACT}.extract_footprints",
                return_value=_make_footprints(),
            ),
            patch(
                f"{_EXTRACT}.extract_board_outline",
                return_value=bbox,
            ),
        ):
            mock_mgr.return_value.get_session.return_value = mock_session
            result = _evaluate_placement_handler(session_id="test")
        assert result["status"] == "evaluated"
        assert "hpwl_total" in result["result"]
        assert "overlap_count" in result["result"]
        assert "density" in result["result"]


class TestSpreadComponentsHandler:
    def test_session_not_found(self) -> None:
        from kicad_mcp.tools.autoplacement import _spread_components_handler

        with patch("kicad_mcp.tools.autoplacement._get_mgr") as mock_mgr:
            mock_mgr.return_value.get_session.side_effect = KeyError("not found")
            result = _spread_components_handler(session_id="bad-id")
        assert "error" in result

    def test_preview_mode(self) -> None:
        from kicad_mcp.tools.autoplacement import _spread_components_handler

        mock_session = MagicMock()
        mock_session._working_doc = MagicMock()
        bbox = BoundingBox(0, 0, 100, 100)

        with (
            patch("kicad_mcp.tools.autoplacement._get_mgr") as mock_mgr,
            patch(
                f"{_EXTRACT}.extract_footprints",
                return_value=_make_footprints(),
            ),
            patch(
                f"{_EXTRACT}.extract_board_outline",
                return_value=bbox,
            ),
        ):
            mock_mgr.return_value.get_session.return_value = mock_session
            result = _spread_components_handler(session_id="test", apply=False)
        assert result["status"] == "preview"


class TestToolRegistration:
    def test_tools_registered(self) -> None:
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        assert "optimize_placement" in TOOL_REGISTRY
        assert "evaluate_placement" in TOOL_REGISTRY
        assert "spread_components" in TOOL_REGISTRY

    def test_tool_categories(self) -> None:
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        assert TOOL_REGISTRY["optimize_placement"].category == "autoplacement"
        assert TOOL_REGISTRY["evaluate_placement"].category == "autoplacement"
        assert TOOL_REGISTRY["spread_components"].category == "autoplacement"

    def test_tools_are_routed(self) -> None:
        from kicad_mcp.tools.registry import TOOL_REGISTRY

        assert TOOL_REGISTRY["optimize_placement"].direct is False
        assert TOOL_REGISTRY["evaluate_placement"].direct is False
        assert TOOL_REGISTRY["spread_components"].direct is False
