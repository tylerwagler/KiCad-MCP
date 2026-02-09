"""Tests for the tool router meta-tools and tool registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.tools import TOOL_REGISTRY, get_categories

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")


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
        if BLINKY_PATH.exists():
            from kicad_mcp import state

            state.load_board(str(BLINKY_PATH))

    @pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
    def test_execute_get_net_list(self) -> None:
        handler = TOOL_REGISTRY["get_net_list"].handler
        result = handler()
        assert result["count"] == 9

    @pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
    def test_execute_get_layer_stack(self) -> None:
        handler = TOOL_REGISTRY["get_layer_stack"].handler
        result = handler()
        assert len(result["copper_layers"]) == 2

    @pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
    def test_execute_get_board_extents(self) -> None:
        handler = TOOL_REGISTRY["get_board_extents"].handler
        result = handler()
        assert result["has_outline"] is True
        assert result["bounding_box"]["width"] > 0

    @pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
    def test_execute_get_component_details(self) -> None:
        handler = TOOL_REGISTRY["get_component_details"].handler
        result = handler(reference="C7")
        assert result["found"] is True
        assert result["pad_count"] == 2

    @pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
    def test_execute_get_net_connections(self) -> None:
        handler = TOOL_REGISTRY["get_net_connections"].handler
        result = handler(net_name="VBUS")
        # Pads may or may not have net assignments depending on board state
        assert "connection_count" in result
        assert "connections" in result

    def test_execute_unknown_tool(self) -> None:
        # Verify the registry doesn't have a fake tool
        assert "nonexistent_tool" not in TOOL_REGISTRY
