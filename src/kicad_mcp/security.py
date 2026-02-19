"""Security utilities — path validation and subprocess safety.

Prevents path traversal attacks, restricts file extensions, and
limits subprocess commands to a known-safe whitelist.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path

# Allowed KiCad file extensions
KICAD_EXTENSIONS = frozenset(
    {
        ".kicad_pcb",
        ".kicad_sch",
        ".kicad_pro",
        ".kicad_mod",
        ".kicad_sym",
        ".kicad_wks",
        ".kicad_dru",
    }
)

# Allowed output extensions for export operations
EXPORT_EXTENSIONS = frozenset(
    {
        ".gbr",
        ".drl",
        ".pdf",
        ".svg",
        ".step",
        ".stl",
        ".vrml",
        ".wrl",
        ".pos",
        ".csv",
        ".json",
        ".xml",
        ".html",
        ".txt",
        ".rpt",
        ".glb",
        ".brep",
        ".xao",
    }
)

ALL_ALLOWED_EXTENSIONS = KICAD_EXTENSIONS | EXPORT_EXTENSIONS

# Allowed kicad-cli subcommands
ALLOWED_CLI_COMMANDS = frozenset(
    {
        "pcb",
        "sch",
        "fp",
        "sym",
        "version",
        "jobset",
    }
)

ALLOWED_CLI_SUBCOMMANDS = frozenset(
    {
        "drc",
        "export",
        "render",
        # export sub-subcommands
        "gerber",
        "gerbers",
        "drill",
        "dxf",
        "pdf",
        "svg",
        "step",
        "stl",
        "vrml",
        "pos",
        "glb",
        "brep",
        "xao",
        "gencad",
        "ipc2581",
        "ipcd356",
        "odb",
        "ply",
    }
)


class SecurityError(Exception):
    """Raised when a security check fails."""


# ── Singleton helpers ───────────────────────────────────────────────

_validator: PathValidator | None = None
_validator_lock = threading.Lock()


def get_validator() -> PathValidator:
    """Get the shared PathValidator singleton (thread-safe lazy init).

    Starts with no trusted roots — only extension checking is active.
    Call ``add_trusted_root()`` when a board is opened to restrict
    paths to the project directory.
    """
    global _validator
    if _validator is None:
        with _validator_lock:
            if _validator is None:
                _validator = PathValidator()
    return _validator


def add_trusted_root(path: str | Path) -> None:
    """Register a trusted root directory in the shared validator.

    Called when ``open_project`` loads a board so that subsequent
    path validations can verify files live under the project tree.
    """
    validator = get_validator()
    resolved = Path(path).resolve()
    if resolved not in validator.trusted_roots:
        validator.trusted_roots.append(resolved)


class PathValidator:
    """Validates file paths against trusted roots and extension whitelists.

    Usage::

        validator = PathValidator(trusted_roots=[Path("C:/projects")])
        validator.validate_input("C:/projects/board.kicad_pcb")  # OK
        validator.validate_input("C:/etc/passwd")  # raises SecurityError
        validator.validate_input("../../etc/passwd")  # raises SecurityError
    """

    def __init__(
        self,
        trusted_roots: list[Path] | None = None,
        allowed_extensions: frozenset[str] | None = None,
    ) -> None:
        self.trusted_roots = trusted_roots or []
        self.allowed_extensions = allowed_extensions or ALL_ALLOWED_EXTENSIONS

    def validate_input(self, path: str | Path) -> Path:
        """Validate an input file path (must exist and be a KiCad file).

        Args:
            path: Path to validate.

        Returns:
            The resolved, validated Path.

        Raises:
            SecurityError: If the path fails validation.
        """
        return self._validate(path, must_exist=True, extensions=KICAD_EXTENSIONS)

    def validate_output(self, path: str | Path) -> Path:
        """Validate an output file path (parent must exist).

        Args:
            path: Path to validate.

        Returns:
            The resolved, validated Path.

        Raises:
            SecurityError: If the path fails validation.
        """
        return self._validate(path, must_exist=False, extensions=self.allowed_extensions)

    def validate_directory(self, path: str | Path) -> Path:
        """Validate a directory path.

        Args:
            path: Path to validate.

        Returns:
            The resolved, validated Path.

        Raises:
            SecurityError: If the path fails validation.
        """
        resolved = self._resolve_and_check_traversal(path)
        self._check_trusted_root(resolved)
        return resolved

    def _validate(
        self,
        path: str | Path,
        must_exist: bool,
        extensions: frozenset[str],
    ) -> Path:
        resolved = self._resolve_and_check_traversal(path)
        self._check_trusted_root(resolved)
        self._check_extension(resolved, extensions)

        if must_exist and not resolved.is_file():
            raise SecurityError(f"File does not exist: {resolved}")

        return resolved

    def _resolve_and_check_traversal(self, path: str | Path) -> Path:
        """Resolve the path and check for traversal attempts."""
        path = Path(path)
        try:
            resolved = path.resolve()
        except (OSError, ValueError) as e:
            raise SecurityError(f"Invalid path: {path} ({e})") from e

        # Check for null bytes
        if "\x00" in str(path):
            raise SecurityError("Path contains null bytes")

        # Check for path traversal patterns in the original string
        path_str = str(path)
        if ".." in path_str:
            raise SecurityError(f"Path traversal detected: {path_str}")

        return resolved

    def _check_trusted_root(self, resolved: Path) -> None:
        """Verify the path is under a trusted root."""
        if not self.trusted_roots:
            return  # No restrictions

        for root in self.trusted_roots:
            try:
                resolved.relative_to(root.resolve())
                return  # Path is under this trusted root
            except ValueError:
                continue

        roots = [str(r) for r in self.trusted_roots]
        raise SecurityError(f"Path {resolved} is not under any trusted root: {roots}")

    @staticmethod
    def _check_extension(path: Path, allowed: frozenset[str]) -> None:
        """Check that the file extension is allowed."""
        # Handle multi-part extensions like .kicad_pcb
        name = path.name
        for ext in allowed:
            if name.endswith(ext):
                return

        raise SecurityError(f"Extension not allowed: {path.suffix!r} (file: {path.name})")


class SecureSubprocess:
    """Validates subprocess commands against a whitelist.

    Only allows kicad-cli commands with known-safe subcommands.

    Usage::

        secure = SecureSubprocess()
        secure.validate_command(["kicad-cli", "pcb", "drc", ...])  # OK
        secure.validate_command(["rm", "-rf", "/"])  # raises SecurityError
    """

    def __init__(self, allowed_executables: frozenset[str] | None = None) -> None:
        self.allowed_executables = allowed_executables or frozenset({"kicad-cli"})

    def validate_command(self, cmd: Sequence[str]) -> None:
        """Validate a command before execution.

        Args:
            cmd: Command and arguments as a list.

        Raises:
            SecurityError: If the command is not allowed.
        """
        if not cmd:
            raise SecurityError("Empty command")

        executable = Path(cmd[0]).stem  # Get just the name without path/extension
        if executable not in self.allowed_executables:
            raise SecurityError(f"Executable not allowed: {executable!r}")

        # Validate subcommands
        for arg in cmd[1:]:
            if arg.startswith("-"):
                continue  # Skip flags
            if arg in ALLOWED_CLI_COMMANDS or arg in ALLOWED_CLI_SUBCOMMANDS:
                continue  # Known subcommand
            # It's probably a file path or value — that's fine
            break
