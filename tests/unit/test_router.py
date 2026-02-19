"""Tests for the tool router meta-tools and tool registry."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kicad_mcp.tools import TOOL_REGISTRY, get_categories

# Default to the synthetic fixture; override with KICAD_TEST_BOARD env var
FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "minimal_board.kicad_pcb"
BOARD_PATH = Path(os.environ.get("KICAD_TEST_BOARD", str(FIXTURE_PATH)))


class TestToolRegistry:
    def test_tools_registered(self) -> None:
        # Direct tools
        assert "open_project" in TOOL_REGISTRY
        assert "get_board_info" in TOOL_REGISTRY
        assert "list_components" in TOOL_REGISTRY
        assert "find_component" in TOOL_REGISTRY
        # Routed tools
        assert "get_net_list" in TOOL_REGISTRY
        assert "get_layer_stack" in TOOL_REGISTRY
        assert "get_board_extents" in TOOL_REGISTRY
        assert "get_component_details" in TOOL_REGISTRY
        assert "get_net_connections" in TOOL_REGISTRY

    def test_direct_flag(self) -> None:
        assert TOOL_REGISTRY["open_project"].direct is True
        assert TOOL_REGISTRY["get_net_list"].direct is False

    def test_categories(self) -> None:
        cats = get_categories()
        assert "project" in cats
        assert "analysis" in cats

    def test_category_contents(self) -> None:
        cats = get_categories()
        project_names = [t.name for t in cats["project"]]
        assert "open_project" in project_names
        analysis_names = [t.name for t in cats["analysis"]]
        assert "get_net_list" in analysis_names


class TestRouterDispatch:
    """Test the execute_tool dispatch mechanism directly via handler calls."""

    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        if BOARD_PATH.exists():
            from kicad_mcp import state

            state.load_board(str(BOARD_PATH))

    @pytest.mark.skipif(not BOARD_PATH.exists(), reason="Test fixture not available")
    def test_execute_get_net_list(self) -> None:
        handler = TOOL_REGISTRY["get_net_list"].handler
        result = handler()
        assert result["count"] >= 3

    @pytest.mark.skipif(not BOARD_PATH.exists(), reason="Test fixture not available")
    def test_execute_get_layer_stack(self) -> None:
        handler = TOOL_REGISTRY["get_layer_stack"].handler
        result = handler()
        assert len(result["copper_layers"]) == 2

    @pytest.mark.skipif(not BOARD_PATH.exists(), reason="Test fixture not available")
    def test_execute_get_board_extents(self) -> None:
        handler = TOOL_REGISTRY["get_board_extents"].handler
        result = handler()
        assert result["has_outline"] is True
        assert result["bounding_box"]["width"] > 0

    @pytest.mark.skipif(not BOARD_PATH.exists(), reason="Test fixture not available")
    def test_execute_get_component_details(self) -> None:
        handler = TOOL_REGISTRY["get_component_details"].handler
        result = handler(reference="R1")
        assert result["found"] is True
        assert result["pad_count"] == 2

    @pytest.mark.skipif(not BOARD_PATH.exists(), reason="Test fixture not available")
    def test_execute_get_net_connections(self) -> None:
        handler = TOOL_REGISTRY["get_net_connections"].handler
        result = handler(net_name="VCC")
        assert "connection_count" in result
        assert "connections" in result

    def test_execute_unknown_tool(self) -> None:
        # Verify the registry doesn't have a fake tool
        assert "nonexistent_tool" not in TOOL_REGISTRY


class TestTruncateResponse:
    """Test the _truncate_response safety net."""

    def test_small_response_unchanged(self) -> None:
        from kicad_mcp.tools.router import _truncate_response

        data = {"items": [1, 2, 3], "count": 3}
        result = _truncate_response(data)
        assert result == {"items": [1, 2, 3], "count": 3}
        assert "_truncated" not in result

    def test_large_response_truncated(self) -> None:
        from kicad_mcp.tools.router import MAX_RESPONSE_CHARS, _truncate_response

        # Build a response that exceeds the limit
        big_list = [{"name": f"item_{i}", "data": "x" * 200} for i in range(1000)]
        data = {"items": big_list, "count": len(big_list)}
        import json

        assert len(json.dumps(data)) > MAX_RESPONSE_CHARS

        result = _truncate_response(data)
        assert result["_truncated"] is True
        assert "_message" in result
        assert len(result["items"]) < 1000

        # Result should now fit within the limit
        assert len(json.dumps(result, default=str)) <= MAX_RESPONSE_CHARS

    def test_no_list_fields_unchanged(self) -> None:
        from kicad_mcp.tools.router import _truncate_response

        data = {"big_string": "x" * 100_000}
        result = _truncate_response(data)
        # Can't truncate a non-list field, so returned as-is
        assert "_truncated" not in result

    def test_truncation_picks_largest_list(self) -> None:
        from kicad_mcp.tools.router import _truncate_response

        big_list = [{"data": "x" * 300} for _ in range(500)]
        small_list = [1, 2, 3]
        data = {"big": big_list, "small": small_list, "count": 500}
        result = _truncate_response(data)
        assert result["_truncated"] is True
        # Small list should be untouched
        assert result["small"] == [1, 2, 3]
        assert len(result["big"]) < 500
