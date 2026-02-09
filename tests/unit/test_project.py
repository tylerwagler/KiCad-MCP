"""Tests for project management tools (create_project, save_project)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from kicad_mcp.sexp import Document


class TestCreateProject:
    def test_create_project_files(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            result = TOOL_REGISTRY["create_project"].handler(
                name="test_project",
                directory=tmpdir,
            )
            assert result["status"] == "created"
            assert len(result["files"]) == 3

            # Check all files exist
            for f in result["files"]:
                assert Path(f).exists()

    def test_create_project_pro_file_valid_json(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            TOOL_REGISTRY["create_project"].handler(
                name="my_board",
                directory=tmpdir,
            )
            pro_path = Path(tmpdir) / "my_board.kicad_pro"
            data = json.loads(pro_path.read_text(encoding="utf-8"))
            assert data["meta"]["filename"] == "my_board.kicad_pro"

    def test_create_project_pcb_parseable(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            TOOL_REGISTRY["create_project"].handler(
                name="my_board",
                directory=tmpdir,
            )
            pcb_path = Path(tmpdir) / "my_board.kicad_pcb"
            doc = Document.load(str(pcb_path))
            assert doc.root.name == "kicad_pcb"

    def test_create_project_sch_parseable(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            TOOL_REGISTRY["create_project"].handler(
                name="my_board",
                directory=tmpdir,
            )
            sch_path = Path(tmpdir) / "my_board.kicad_sch"
            doc = Document.load(str(sch_path))
            assert doc.root.name == "kicad_sch"

    def test_create_project_with_board_size(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            TOOL_REGISTRY["create_project"].handler(
                name="sized_board",
                directory=tmpdir,
                board_size_x=100,
                board_size_y=80,
            )
            pcb_path = Path(tmpdir) / "sized_board.kicad_pcb"
            doc = Document.load(str(pcb_path))

            # Should have Edge.Cuts outline
            edge_cuts = [
                c
                for c in doc.root.children
                if c.name == "gr_line"
                and c.get("layer")
                and c.get("layer").first_value == "Edge.Cuts"
            ]
            assert len(edge_cuts) == 4

    def test_create_project_pcb_has_layers(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            TOOL_REGISTRY["create_project"].handler(
                name="my_board",
                directory=tmpdir,
            )
            pcb_path = Path(tmpdir) / "my_board.kicad_pcb"
            doc = Document.load(str(pcb_path))
            layers = doc.root.get("layers")
            assert layers is not None
            assert len(layers.children) > 0

    def test_create_project_pcb_no_toplevel_uuid(self) -> None:
        """KiCad 9 PCB files must not have a top-level (uuid ...) token."""
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            TOOL_REGISTRY["create_project"].handler(
                name="my_board",
                directory=tmpdir,
            )
            pcb_path = Path(tmpdir) / "my_board.kicad_pcb"
            doc = Document.load(str(pcb_path))
            # uuid must not be a direct child of kicad_pcb
            top_uuid = doc.root.get("uuid")
            assert top_uuid is None, "PCB must not have top-level (uuid ...)"

    def test_create_project_pcb_has_setup(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            TOOL_REGISTRY["create_project"].handler(
                name="my_board",
                directory=tmpdir,
            )
            pcb_path = Path(tmpdir) / "my_board.kicad_pcb"
            doc = Document.load(str(pcb_path))
            setup = doc.root.get("setup")
            assert setup is not None


BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")

skip_no_board = pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")


@skip_no_board
class TestSaveProject:
    def test_save_project(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        state.load_board(str(BLINKY_PATH))
        with tempfile.TemporaryDirectory() as tmpdir:
            out = str(Path(tmpdir) / "saved.kicad_pcb")
            result = TOOL_REGISTRY["save_project"].handler(output_path=out)
            assert result["status"] == "saved"
            assert Path(out).exists()

    def test_save_project_roundtrip(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        state.load_board(str(BLINKY_PATH))
        with tempfile.TemporaryDirectory() as tmpdir:
            out = str(Path(tmpdir) / "saved.kicad_pcb")
            TOOL_REGISTRY["save_project"].handler(output_path=out)

            # Re-load and verify
            doc = Document.load(out)
            assert doc.root.name == "kicad_pcb"
            assert len(doc.root.find_all("footprint")) > 0
