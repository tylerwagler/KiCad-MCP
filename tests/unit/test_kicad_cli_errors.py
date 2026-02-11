"""Unit tests for kicad-cli error messages and path detection."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from kicad_mcp.backends.kicad_cli import KiCadCli, KiCadCliError, KiCadCliNotFound


class TestGlobPathDetection:
    """Tests for the glob fallback in _find_cli()."""

    @patch("kicad_mcp.backends.kicad_cli.glob.glob")
    @patch("kicad_mcp.backends.kicad_cli.Path.is_file", return_value=False)
    @patch("shutil.which", return_value=None)
    @patch("kicad_mcp.backends.kicad_cli.sys.platform", "win32")
    def test_glob_finds_versioned_windows_path(self, mock_which, mock_is_file, mock_glob) -> None:
        mock_glob.return_value = [
            r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
            r"C:\Program Files\KiCad\9.0.2\bin\kicad-cli.exe",
        ]
        # sorted(..., reverse=True) will pick 9.0.2 first
        result = KiCadCli._find_cli()
        assert "9.0.2" in result

    @patch("kicad_mcp.backends.kicad_cli.glob.glob")
    @patch("kicad_mcp.backends.kicad_cli.Path.is_file", return_value=False)
    @patch("shutil.which", return_value=None)
    @patch("kicad_mcp.backends.kicad_cli.sys.platform", "win32")
    def test_glob_no_matches_raises(self, mock_which, mock_is_file, mock_glob) -> None:
        mock_glob.return_value = []
        with pytest.raises(KiCadCliNotFound):
            KiCadCli._find_cli()

    @patch("kicad_mcp.backends.kicad_cli.glob.glob")
    @patch("kicad_mcp.backends.kicad_cli.Path.is_file", return_value=False)
    @patch("shutil.which", return_value=None)
    @patch("kicad_mcp.backends.kicad_cli.sys.platform", "linux")
    def test_glob_linux_pattern(self, mock_which, mock_is_file, mock_glob) -> None:
        mock_glob.return_value = ["/usr/lib/kicad/9.1/bin/kicad-cli"]
        result = KiCadCli._find_cli()
        assert result == "/usr/lib/kicad/9.1/bin/kicad-cli"

    @patch("kicad_mcp.backends.kicad_cli.Path.is_file", return_value=False)
    @patch("shutil.which", return_value="/usr/bin/kicad-cli")
    def test_which_takes_priority(self, mock_which, mock_is_file) -> None:
        result = KiCadCli._find_cli()
        assert result == "/usr/bin/kicad-cli"


class TestFormatError:
    """Tests for the _format_error() helper."""

    def test_includes_stderr_and_command(self) -> None:
        cli = KiCadCli.__new__(KiCadCli)
        cli.cli_path = "/usr/bin/kicad-cli"

        result = subprocess.CompletedProcess(
            args=["kicad-cli", "pcb", "export", "gerbers", "board.kicad_pcb"],
            returncode=1,
            stdout="",
            stderr="Failed to load board",
        )
        msg = cli._format_error(result, "Gerber export failed")
        assert "Failed to load board" in msg
        assert "exit code: 1" in msg
        assert "cli path: /usr/bin/kicad-cli" in msg
        assert "kicad-cli pcb export gerbers board.kicad_pcb" in msg

    def test_falls_back_to_stdout(self) -> None:
        cli = KiCadCli.__new__(KiCadCli)
        cli.cli_path = "/usr/bin/kicad-cli"

        result = subprocess.CompletedProcess(
            args=["kicad-cli", "pcb", "drc", "board.kicad_pcb"],
            returncode=2,
            stdout="Some stdout info",
            stderr="",
        )
        msg = cli._format_error(result, "DRC failed")
        assert "Some stdout info" in msg
        assert "DRC failed" not in msg  # stdout is non-empty, so fallback unused

    def test_uses_fallback_when_no_output(self) -> None:
        cli = KiCadCli.__new__(KiCadCli)
        cli.cli_path = "/usr/bin/kicad-cli"

        result = subprocess.CompletedProcess(
            args=["kicad-cli", "version"],
            returncode=127,
            stdout="",
            stderr="",
        )
        msg = cli._format_error(result, "Version check failed")
        assert "Version check failed" in msg
        assert "exit code: 127" in msg


class TestRunErrors:
    """Tests for _run() error handling."""

    def test_file_not_found_raises_cli_not_found(self) -> None:
        cli = KiCadCli.__new__(KiCadCli)
        cli.cli_path = "/nonexistent/kicad-cli"
        cli.timeout = 10

        with (
            patch("subprocess.run", side_effect=FileNotFoundError("No such file")),
            pytest.raises(KiCadCliNotFound, match="/nonexistent/kicad-cli"),
        ):
            cli._run(["version"])

    def test_timeout_raises_cli_error(self) -> None:
        cli = KiCadCli.__new__(KiCadCli)
        cli.cli_path = "/usr/bin/kicad-cli"
        cli.timeout = 5

        with (
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="kicad-cli", timeout=5),
            ),
            pytest.raises(KiCadCliError, match="timed out after 5s"),
        ):
            cli._run(["pcb", "drc", "board.kicad_pcb"])


class TestExportHandlerCatchesCliError:
    """Tests that tool handlers catch KiCadCliError for timeouts."""

    def test_gerber_handler_catches_timeout(self) -> None:
        from kicad_mcp.tools.export import _export_gerbers_handler

        with (
            patch(
                "kicad_mcp.state.get_board_path",
                return_value="/tmp/board.kicad_pcb",
            ),
            patch("kicad_mcp.backends.kicad_cli.KiCadCli.__init__", return_value=None),
            patch(
                "kicad_mcp.backends.kicad_cli.KiCadCli.export_gerbers",
                side_effect=KiCadCliError("kicad-cli timed out after 120s"),
            ),
        ):
            result = _export_gerbers_handler("/tmp/out")
            assert "error" in result
            assert "timed out" in result["error"]

    def test_drc_handler_catches_timeout(self) -> None:
        from kicad_mcp.tools.drc import _run_drc_handler

        with (
            patch(
                "kicad_mcp.state.get_board_path",
                return_value="/tmp/board.kicad_pcb",
            ),
            patch("kicad_mcp.backends.kicad_cli.KiCadCli.__init__", return_value=None),
            patch(
                "kicad_mcp.backends.kicad_cli.KiCadCli.run_drc",
                side_effect=KiCadCliError("kicad-cli timed out after 120s"),
            ),
        ):
            result = _run_drc_handler()
            assert "error" in result
            assert "timed out" in result["error"]

    def test_pdf_handler_catches_timeout(self) -> None:
        from kicad_mcp.tools.export import _export_pdf_handler

        with (
            patch(
                "kicad_mcp.state.get_board_path",
                return_value="/tmp/board.kicad_pcb",
            ),
            patch("kicad_mcp.backends.kicad_cli.KiCadCli.__init__", return_value=None),
            patch(
                "kicad_mcp.backends.kicad_cli.KiCadCli.export_pdf",
                side_effect=KiCadCliError("kicad-cli timed out after 120s"),
            ),
        ):
            result = _export_pdf_handler("/tmp/out.pdf")
            assert "error" in result
            assert "timed out" in result["error"]
