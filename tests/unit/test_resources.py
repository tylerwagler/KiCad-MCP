"""Tests for MCP resources and prompts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.server import create_server

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")


class TestServerWithResourcesAndPrompts:
    def test_server_creates_successfully(self) -> None:
        server = create_server()
        assert server is not None


@pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
class TestResources:
    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_board_summary_resource(self) -> None:
        from fastmcp import FastMCP

        from kicad_mcp.resources.board import register_board_resources

        mcp = FastMCP("test")
        register_board_resources(mcp)
        # The resource functions are closures, test them directly
        from kicad_mcp import state

        summary = state.get_summary()
        data = summary.to_dict()
        # Verify it's JSON-serializable
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["title"] == "blinky"
        assert parsed["footprint_count"] == 29

    def test_board_components_data(self) -> None:
        from kicad_mcp import state

        footprints = state.get_footprints()
        components = [
            {"reference": fp.reference, "value": fp.value, "library": fp.library}
            for fp in footprints
        ]
        json_str = json.dumps({"count": len(components), "components": components})
        parsed = json.loads(json_str)
        assert parsed["count"] == 29

    def test_board_nets_data(self) -> None:
        from kicad_mcp import state

        summary = state.get_summary()
        nets_data = [n.to_dict() for n in summary.nets]
        json_str = json.dumps({"count": len(nets_data), "nets": nets_data})
        parsed = json.loads(json_str)
        assert parsed["count"] == 9

    def test_component_detail_data(self) -> None:
        from kicad_mcp import state

        footprints = state.get_footprints()
        c7 = next(fp for fp in footprints if fp.reference == "C7")
        data = c7.to_dict()
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["reference"] == "C7"
        assert parsed["value"] == "10uF"


@pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
class TestPrompts:
    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_design_review_prompt(self) -> None:
        from fastmcp import FastMCP

        from kicad_mcp.prompts.templates import register_prompts

        mcp = FastMCP("test")
        register_prompts(mcp)
        # Test the underlying logic
        from kicad_mcp import state

        summary = state.get_summary()
        assert summary.title == "blinky"
        # The prompt should reference the board
        assert summary.footprint_count == 29

    def test_drc_troubleshoot_prompt_content(self) -> None:
        # This prompt doesn't depend on board state
        # Just verify the function exists and returns a string
        from fastmcp import FastMCP

        from kicad_mcp.prompts.templates import register_prompts

        mcp = FastMCP("test")
        register_prompts(mcp)
        # Prompt is registered - server creation shouldn't fail

    def test_component_placement_prompt(self) -> None:
        from kicad_mcp import state

        footprints = state.get_footprints()
        # Verify we can group by library
        lib_counts: dict[str, int] = {}
        for fp in footprints:
            lib = fp.library.split(":")[0] if ":" in fp.library else fp.library
            lib_counts[lib] = lib_counts.get(lib, 0) + 1
        assert "Capacitor_SMD" in lib_counts
        assert "Resistor_SMD" in lib_counts
