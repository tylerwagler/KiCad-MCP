"""Integration tests for the MCP server end-to-end flow."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import create_server

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")


class TestServerCreation:
    def test_create_server(self) -> None:
        server = create_server()
        assert server is not None
        assert server.name == "kicad-mcp"


@pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
class TestEndToEnd:
    """Test the full flow: open board -> query info -> find components."""

    def test_open_and_query(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        # Open project
        result = TOOL_REGISTRY["open_project"].handler(board_path=str(BLINKY_PATH))
        assert result["status"] == "ok"
        assert "blinky" in result["message"]

        # Get board info
        info = TOOL_REGISTRY["get_board_info"].handler()
        assert info["footprint_count"] == 29
        assert info["net_count"] == 9

        # List components
        components = TOOL_REGISTRY["list_components"].handler()
        assert components["count"] == 29

        # Find specific component
        found = TOOL_REGISTRY["find_component"].handler(reference="U1")
        assert found["found"] is True

        # Find non-existent component
        not_found = TOOL_REGISTRY["find_component"].handler(reference="Z99")
        assert not_found["found"] is False
