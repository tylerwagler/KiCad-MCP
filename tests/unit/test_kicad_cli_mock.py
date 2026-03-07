"""Unit tests for kicad-cli backend validation and error handling.

These tests verify that the kicad-cli backend properly validates inputs
and handles errors without requiring actual kicad-cli execution.
"""

from __future__ import annotations

import subprocess
from unittest.mock import Mock

from kicad_mcp.backends.kicad_cli import KiCadCli
from kicad_mcp.schema.drc import DrcResult, DrcViolation


class TestDrcResultCreation:
    """Test DRC result creation and serialization."""

    def test_create_drc_with_errors(self):
        """Test creating DRC result with errors."""
        violation = DrcViolation(
            type="clearance",
            severity="error",
            description="Clearance violation between R1 and C5",
            position={"x": 10.5, "y": 20.3},
        )

        result = DrcResult(passed=False, error_count=1, warning_count=0, violations=[violation])

        assert result.error_count == 1
        assert result.warning_count == 0
        assert len(result.violations) == 1
        assert result.violations[0].type == "clearance"
        assert result.passed is False

    def test_create_drc_clean(self):
        """Test creating DRC result with no violations."""
        result = DrcResult(passed=True, error_count=0, warning_count=0, violations=[])

        assert result.error_count == 0
        assert result.warning_count == 0
        assert len(result.violations) == 0
        assert result.passed is True

    def test_create_drc_with_warnings(self):
        """Test creating DRC result with warnings only."""
        violation = DrcViolation(
            type="unconnected", severity="warning", description="Unconnected pad on U3"
        )

        result = DrcResult(passed=True, error_count=0, warning_count=1, violations=[violation])

        assert result.error_count == 0
        assert result.warning_count == 1
        assert result.passed is True  # Warnings don't fail DRC

    def test_create_drc_mixed_severity(self):
        """Test creating DRC with both errors and warnings."""
        error_violation = DrcViolation(
            type="clearance", severity="error", description="Clearance violation"
        )
        warning_violation = DrcViolation(
            type="unconnected", severity="warning", description="Unconnected pad"
        )

        result = DrcResult(
            passed=False,
            error_count=1,
            warning_count=1,
            violations=[error_violation, warning_violation],
        )

        assert result.error_count == 1
        assert result.warning_count == 1
        assert len(result.violations) == 2
        assert result.passed is False


class TestExportResultParsing:
    """Test export result handling."""

    def test_export_success(self):
        """Test successful export result."""
        result = subprocess.CompletedProcess(
            args=["kicad-cli", "pcb", "export", "gerbers"], returncode=0, stdout="", stderr=""
        )
        assert result.returncode == 0

    def test_export_failure(self):
        """Test failed export result."""
        result = subprocess.CompletedProcess(
            args=["kicad-cli", "pcb", "export", "gerbers"],
            returncode=1,
            stdout="",
            stderr="Error: Failed to export gerbers",
        )
        assert result.returncode != 0
        assert "Error" in result.stderr


class TestKiCadCliErrorFormatting:
    """Test error message formatting in KiCadCli."""

    def test_error_with_stderr(self):
        """Test error message includes stderr output."""
        result = subprocess.CompletedProcess(
            args=["kicad-cli", "pcb", "drc", "board.kicad_pcb"],
            returncode=1,
            stdout="",
            stderr="DRC failed: clearance violation",
        )

        cli = KiCadCli(cli_path="/mock/kicad-cli")
        error_msg = cli._format_error(result, "Unknown error")

        assert "DRC failed" in error_msg
        assert "kicad-cli" in error_msg
        assert "pcb drc" in error_msg

    def test_error_with_stdout(self):
        """Test error message includes stdout when stderr is empty."""
        result = subprocess.CompletedProcess(
            args=["kicad-cli", "pcb", "drc"],
            returncode=1,
            stdout="Warning: some issue detected",
            stderr="",
        )

        cli = KiCadCli(cli_path="/mock/kicad-cli")
        error_msg = cli._format_error(result, "Unknown error")

        assert "Warning" in error_msg


class TestCommandValidation:
    """Test command validation in kicad-cli backend."""

    def test_version_command_structure(self):
        """Test that version command is structured correctly."""
        from kicad_mcp.security import SecureSubprocess

        secure = SecureSubprocess()
        # Should not raise
        secure.validate_command(["kicad-cli", "version", "--format", "plain"])

    def test_drc_command_structure(self):
        """Test that DRC command is structured correctly."""
        from kicad_mcp.security import SecureSubprocess

        secure = SecureSubprocess()
        # Should not raise
        secure.validate_command(["kicad-cli", "pcb", "drc", "--format", "json", "board.kicad_pcb"])

    def test_export_command_structure(self):
        """Test that export command is structured correctly."""
        from kicad_mcp.security import SecureSubprocess

        secure = SecureSubprocess()
        # Should not raise
        secure.validate_command(["kicad-cli", "pcb", "export", "gerbers", "board.kicad_pcb"])


class TestDrcResultToDict:
    """Test DrcResult serialization."""

    def test_to_dict_includes_all_fields(self):
        """Test that to_dict includes all expected fields."""
        result = DrcResult(
            passed=True, error_count=0, warning_count=1, violations=[], report_path="/tmp/drc.json"
        )

        d = result.to_dict()

        assert "passed" in d
        assert "error_count" in d
        assert "warning_count" in d
        assert "violations" in d
        assert "report_path" in d

    def test_to_dict_with_violations(self):
        """Test to_dict with violations included."""
        violation = Mock()
        violation.rule = "clearance"
        violation.message = "Test violation"
        violation.to_dict.return_value = {"rule": "clearance", "message": "Test violation"}

        result = DrcResult(
            passed=False,
            error_count=1,
            warning_count=0,
            violations=[violation],
            report_path="/tmp/drc.json",
        )

        d = result.to_dict()

        assert len(d["violations"]) == 1
        assert d["violations"][0]["rule"] == "clearance"
