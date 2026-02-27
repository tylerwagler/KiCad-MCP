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
