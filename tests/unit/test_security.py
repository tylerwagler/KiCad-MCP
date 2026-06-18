"""Tests for security utilities — path validation and subprocess safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.security import (
    PathValidator,
    SecureSubprocess,
    SecurityError,
)


class TestPathValidator:
    @pytest.fixture()
    def validator(self) -> PathValidator:
        return PathValidator()

    @pytest.fixture()
    def strict_validator(self, tmp_path: Path) -> PathValidator:
        return PathValidator(trusted_roots=[tmp_path])

    def test_validate_traversal_rejection(self, validator: PathValidator) -> None:
        with pytest.raises(SecurityError, match="traversal"):
            validator.validate_input("../../etc/passwd")

    def test_validate_traversal_with_trusted_root(self, tmp_path: Path) -> None:
        """Test that traversal is rejected even with trusted root configured."""
        validator = PathValidator(trusted_roots=[tmp_path])
        # Path traversal in the raw string is caught before trusted root check
        with pytest.raises(SecurityError, match="traversal"):
            validator.validate_input(str(tmp_path / ".." / ".." / "etc" / "passwd"))

    def test_validate_null_bytes(self, validator: PathValidator) -> None:
        with pytest.raises(SecurityError, match="null bytes"):
            validator.validate_input("board\x00.kicad_pcb")

    def test_validate_extension_kicad_pcb(self, tmp_path: Path) -> None:
        board = tmp_path / "test.kicad_pcb"
        board.write_text("(kicad_pcb)")
        validator = PathValidator(trusted_roots=[tmp_path])
        result = validator.validate_input(str(board))
        assert result == board.resolve()

    def test_validate_extension_rejected(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "malware.exe"
        bad_file.write_text("bad")
        validator = PathValidator(trusted_roots=[tmp_path])
        with pytest.raises(SecurityError, match="Extension not allowed"):
            validator.validate_input(str(bad_file))

    def test_validate_trusted_root(self, tmp_path: Path) -> None:
        board = tmp_path / "project" / "test.kicad_pcb"
        board.parent.mkdir()
        board.write_text("(kicad_pcb)")
        validator = PathValidator(trusted_roots=[tmp_path])
        result = validator.validate_input(str(board))
        assert result == board.resolve()

    def test_validate_untrusted_root(self, tmp_path: Path) -> None:
        board = Path("C:/other/project/test.kicad_pcb")
        validator = PathValidator(trusted_roots=[tmp_path])
        with pytest.raises(SecurityError, match="not under any trusted root"):
            validator.validate_input(str(board))

    def test_validate_output_path(self, tmp_path: Path) -> None:
        output = tmp_path / "output.pdf"
        validator = PathValidator(trusted_roots=[tmp_path])
        result = validator.validate_output(str(output))
        assert result == output.resolve()

    def test_validate_output_bad_extension(self, tmp_path: Path) -> None:
        output = tmp_path / "output.exe"
        validator = PathValidator(trusted_roots=[tmp_path])
        with pytest.raises(SecurityError, match="Extension not allowed"):
            validator.validate_output(str(output))

    def test_validate_directory(self, tmp_path: Path) -> None:
        validator = PathValidator(trusted_roots=[tmp_path])
        result = validator.validate_directory(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_no_trusted_roots_allows_all(self, tmp_path: Path) -> None:
        board = tmp_path / "test.kicad_pcb"
        board.write_text("(kicad_pcb)")
        validator = PathValidator()  # No trusted roots
        result = validator.validate_input(str(board))
        assert result == board.resolve()

    def test_file_must_exist_for_input(self, tmp_path: Path) -> None:
        validator = PathValidator(trusted_roots=[tmp_path])
        with pytest.raises(SecurityError, match="does not exist"):
            validator.validate_input(str(tmp_path / "nonexistent.kicad_pcb"))

    def test_resolved_path_traversal_rejected(self, tmp_path: Path) -> None:
        """Test that paths with .. that resolve outside trusted root are rejected.

        This tests that any path containing .. is rejected, regardless of
        whether it would resolve outside the trusted root.
        """
        validator = PathValidator(trusted_roots=[tmp_path])
        # Any path with .. should be rejected
        with pytest.raises(SecurityError, match="traversal"):
            # Construct a path that would resolve outside the trusted root
            validator.validate_input(str(tmp_path / ".." / ".." / "etc" / "passwd.kicad_pcb"))

    def test_explicit_double_dot_rejected(self, tmp_path: Path) -> None:
        """Test that explicit .. in path is always rejected."""
        validator = PathValidator(trusted_roots=[tmp_path])
        with pytest.raises(SecurityError, match="traversal"):
            validator.validate_input("../../../etc/passwd.kicad_pcb")

    def test_tilde_traversal_rejected(self, tmp_path: Path) -> None:
        """Test that ~ in path is rejected as potential traversal."""
        validator = PathValidator(trusted_roots=[tmp_path])
        with pytest.raises(SecurityError, match="traversal"):
            validator.validate_input("~/../etc/passwd.kicad_pcb")


class TestSecureSubprocess:
    @pytest.fixture()
    def secure(self) -> SecureSubprocess:
        return SecureSubprocess()

    def test_allow_kicad_cli(self, secure: SecureSubprocess) -> None:
        secure.validate_command(["kicad-cli", "pcb", "drc", "board.kicad_pcb"])

    def test_allow_kicad_cli_with_path(self, secure: SecureSubprocess) -> None:
        secure.validate_command(
            [
                r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
                "pcb",
                "export",
                "gerbers",
                "board.kicad_pcb",
            ]
        )

    def test_reject_unknown_executable(self, secure: SecureSubprocess) -> None:
        with pytest.raises(SecurityError, match="not allowed"):
            secure.validate_command(["rm", "-rf", "/"])

    def test_reject_empty_command(self, secure: SecureSubprocess) -> None:
        with pytest.raises(SecurityError, match="Empty command"):
            secure.validate_command([])

    def test_allow_kicad_cli_with_full_path(self, secure: SecureSubprocess) -> None:
        """Test that kicad-cli with full path is accepted."""
        secure.validate_command(
            [
                "/usr/bin/kicad-cli",
                "pcb",
                "drc",
                "board.kicad_pcb",
            ]
        )

    def test_reject_path_traversal_in_argument(self, secure: SecureSubprocess) -> None:
        """Test that path traversal in file path arguments is rejected."""
        with pytest.raises(SecurityError, match="traversal"):
            secure.validate_command(["kicad-cli", "pcb", "drc", "../../etc/passwd.kicad_pcb"])

    def test_reject_null_byte_in_path(self, secure: SecureSubprocess) -> None:
        """Test that null bytes in paths are rejected."""
        with pytest.raises(SecurityError, match="null bytes"):
            secure.validate_command(["kicad-cli", "pcb", "drc", "board\x00.kicad_pcb"])

    def test_reject_absolute_path(self, secure: SecureSubprocess) -> None:
        """Test that absolute paths are rejected."""
        with pytest.raises(SecurityError, match="Absolute paths not allowed"):
            secure.validate_command(["kicad-cli", "pcb", "drc", "/etc/passwd.kicad_pcb"])

    def test_allow_absolute_export_output(self, secure: SecureSubprocess) -> None:
        """Absolute export-output paths (e.g. SVG/PDF) must be accepted."""
        secure.validate_command(
            [
                "kicad-cli",
                "pcb",
                "export",
                "svg",
                "--output",
                "/tmp/board_view.svg",
                "--layers",
                "F.Cu,B.Cu,Edge.Cuts",
                "board.kicad_pcb",
            ]
        )

    def test_reject_suspicious_absolute_export_path(self, secure: SecureSubprocess) -> None:
        """A masquerading system path must stay rejected even with an export extension."""
        with pytest.raises(SecurityError, match="Absolute paths not allowed"):
            secure._validate_file_path("/etc/passwd.svg")

    def test_allow_comma_separated_layers(self, secure: SecureSubprocess) -> None:
        """A comma-separated --layers value is a safe literal."""
        secure.validate_command(
            [
                "kicad-cli",
                "pcb",
                "export",
                "pdf",
                "--layers",
                "F.Cu,B.Cu,F.SilkS,Edge.Cuts",
                "board.kicad_pcb",
            ]
        )

    def test_reject_layers_with_unsafe_token(self, secure: SecureSubprocess) -> None:
        """A comma list element with shell-meta characters is rejected as a literal."""
        with pytest.raises(SecurityError, match="Invalid value"):
            secure.validate_command(
                ["kicad-cli", "pcb", "export", "pdf", "--layers", "F.Cu,bad;token", "b.kicad_pcb"]
            )

    def test_reject_invalid_flag_value(self, secure: SecureSubprocess) -> None:
        """Test that invalid flag values are rejected."""
        with pytest.raises(SecurityError, match="Invalid value"):
            secure.validate_command(
                ["kicad-cli", "pcb", "export", "gerbers", "--format", "exe", "board.kicad_pcb"]
            )

    def test_accept_valid_command(self, secure: SecureSubprocess) -> None:
        """Test that valid commands are accepted."""
        # Should not raise
        secure.validate_command(
            [
                "kicad-cli",
                "pcb",
                "drc",
                "--format",
                "json",
                "--output",
                "report.json",
                "board.kicad_pcb",
            ]
        )

    def test_accept_valid_command_with_relative_path(self, secure: SecureSubprocess) -> None:
        """Test that relative paths are accepted."""
        # Should not raise
        secure.validate_command(["kicad-cli", "pcb", "drc", "subdir/board.kicad_pcb"])

    def test_accept_valid_subcommand_path(self, secure: SecureSubprocess) -> None:
        """Test that valid kicad file paths are accepted."""
        secure.validate_command(
            ["kicad-cli", "pcb", "export", "gerbers", "--output", "output/", "board.kicad_pcb"]
        )

    def test_reject_command_injection_via_flag(self, secure: SecureSubprocess) -> None:
        """Test that command injection via flags is rejected."""
        with pytest.raises(SecurityError):
            # Malicious path with shell metacharacters
            secure.validate_command(
                [
                    "kicad-cli",
                    "pcb",
                    "drc",
                    "--output",
                    "/tmp/malware.sh && rm -rf /",
                    "board.kicad_pcb",
                ]
            )
