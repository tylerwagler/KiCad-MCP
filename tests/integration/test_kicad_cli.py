"""Integration tests for the kicad-cli backend.

These tests require KiCad to be installed and kicad-cli to be available.
They are skipped if kicad-cli is not found.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from kicad_mcp.backends.kicad_cli import KiCadCli, KiCadCliNotFound

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")

try:
    _cli = KiCadCli()
    HAS_KICAD_CLI = True
except KiCadCliNotFound:
    HAS_KICAD_CLI = False

skip_no_cli = pytest.mark.skipif(not HAS_KICAD_CLI, reason="kicad-cli not found")
skip_no_board = pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")


@skip_no_cli
class TestKiCadCliBasic:
    def test_version(self) -> None:
        cli = KiCadCli()
        version = cli.version()
        assert version  # Non-empty string
        assert "9" in version or "8" in version  # KiCad 8 or 9

    def test_is_available(self) -> None:
        assert KiCadCli.is_available()


@skip_no_cli
@skip_no_board
class TestDRC:
    def test_run_drc(self) -> None:
        cli = KiCadCli()
        result = cli.run_drc(str(BLINKY_PATH))
        assert result.error_count >= 0
        assert result.warning_count >= 0
        assert result.report_path is not None

    def test_run_drc_json_report(self) -> None:
        cli = KiCadCli()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            result = cli.run_drc(str(BLINKY_PATH), output_path=f.name)
        assert Path(result.report_path).exists()  # type: ignore[arg-type]
        # Clean up
        Path(result.report_path).unlink(missing_ok=True)  # type: ignore[arg-type]

    def test_drc_result_to_dict(self) -> None:
        cli = KiCadCli()
        result = cli.run_drc(str(BLINKY_PATH))
        d = result.to_dict()
        assert "passed" in d
        assert "error_count" in d
        assert "violations" in d


@skip_no_cli
@skip_no_board
class TestExport:
    def test_export_gerbers(self) -> None:
        cli = KiCadCli()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cli.export_gerbers(str(BLINKY_PATH), tmpdir)
            assert result.success
            # Should have created some Gerber files
            files = list(Path(tmpdir).iterdir())
            assert len(files) > 0

    def test_export_drill(self) -> None:
        cli = KiCadCli()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cli.export_drill(str(BLINKY_PATH), tmpdir)
            assert result.success

    def test_export_pdf(self) -> None:
        cli = KiCadCli()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            output = f.name
        try:
            result = cli.export_pdf(str(BLINKY_PATH), output, layers=["F.Cu", "Edge.Cuts"])
            assert result.success
            assert Path(output).exists()
        finally:
            Path(output).unlink(missing_ok=True)

    def test_export_svg(self) -> None:
        cli = KiCadCli()
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            output = f.name
        try:
            result = cli.export_svg(str(BLINKY_PATH), output, layers=["F.Cu", "Edge.Cuts"])
            assert result.success
            assert Path(output).exists()
        finally:
            Path(output).unlink(missing_ok=True)

    def test_export_pos(self) -> None:
        cli = KiCadCli()
        with tempfile.NamedTemporaryFile(suffix=".pos", delete=False) as f:
            output = f.name
        try:
            result = cli.export_pos(str(BLINKY_PATH), output)
            assert result.success
        finally:
            Path(output).unlink(missing_ok=True)


@skip_no_board
class TestToolHandlers:
    """Test the registered tool handlers for DRC and export."""

    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    @skip_no_cli
    def test_run_drc_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["run_drc"].handler()
        assert "passed" in result
        assert "error_count" in result

    def test_export_bom_tool(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["export_bom"].handler()
        assert result["total_components"] == 29
        assert result["unique_values"] > 0
        assert len(result["items"]) > 0
