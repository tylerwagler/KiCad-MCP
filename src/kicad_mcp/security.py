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
    # Ensure the path is a directory, not a file
    if not resolved.is_dir():
        raise SecurityError(f"Trusted root must be a directory: {path}")
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
        # Check for path traversal pattern in raw path string FIRST
        # This catches cases like ../../etc/passwd before any resolution
        path_str = str(path)
        # detect ".." followed by path separator or at the start of a path component
        if ".." in path_str and ("/" in path_str or "\\" in path_str):
            raise SecurityError(f"Path contains traversal: {path_str}")

        resolved = self._resolve_and_check_traversal(path)
        self._check_trusted_root(resolved)
        self._check_extension(resolved, extensions)

        if must_exist and not resolved.is_file():
            raise SecurityError(f"File does not exist: {resolved}")

        return resolved

    def _resolve_and_check_traversal(self, path: str | Path) -> Path:
        """Resolve the path and check for traversal attempts."""
        path_str = str(path)

        # Check for null bytes FIRST - before any path operations
        if "\x00" in path_str:
            raise SecurityError("Path contains null bytes")

        path = Path(path)
        try:
            # Use strict=False for output files that may not exist yet
            resolved = path.resolve(strict=False)
        except (OSError, ValueError) as e:
            raise SecurityError(f"Invalid path: {path} ({e})") from e

        # Check for null bytes in resolved path (shouldn't happen but be safe)
        if "\x00" in str(resolved):
            raise SecurityError("Path contains null bytes")

        # Resolve any ".." that may have been resolved
        try:
            canonical = resolved.expanduser()
        except (OSError, ValueError):
            canonical = resolved

        # Double-check for ".." in the resolved path
        # This catches cases where the path was constructed to bypass the raw check
        # e.g., /tmp/../etc/passwd (raw check passes, but resolved path has ..)
        resolved_str = str(canonical)
        if ".." in resolved_str:
            raise SecurityError(f"Path contains traversal after resolution: {path_str}")

        return canonical

    def _check_trusted_root(self, resolved: Path) -> None:
        """Verify the path is under a trusted root."""
        if not self.trusted_roots:
            return  # No restrictions

        resolved_resolved = resolved.resolve()

        for root in self.trusted_roots:
            try:
                root_resolved = root.resolve()
                # Use relative_to to check if path is under root
                # If this succeeds and doesn't return '..', path is under root
                rel = resolved_resolved.relative_to(root_resolved)
                # Check that the relative path doesn't contain '..' components
                # (shouldn't happen if relative_to succeeded, but be defensive)
                if not str(rel).startswith(".."):
                    return  # Path is under this trusted root
            except ValueError:
                # resolved_resolved is not under root_resolved
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
    Validates ALL arguments including file paths and flag values.

    Usage::

        secure = SecureSubprocess()
        secure.validate_command(["kicad-cli", "pcb", "drc", ...])  # OK
        secure.validate_command(["rm", "-rf", "/"])  # raises SecurityError
    """

    # Patterns for safe values (layer names, units, etc.)
    _SAFE_LAYER_NAMES = frozenset(
        {
            "F.Cu",
            "B.Cu",
            "F.Paste",
            "B.Paste",
            "F.SilkS",
            "B.SilkS",
            "F.CrtYd",
            "B.CrtYd",
            "F.Fab",
            "B.Fab",
            "F.Mask",
            "B.Mask",
            "Dwgs.User",
            "Cmts.User",
            "Eco1.User",
            "Eco2.User",
            "Edge.Cuts",
            "F.Adhes",
            "B.Adhes",
            "PASTE",
            "SOLDERMASK",
            "SILKSCREEN",
            "F.Copper",
            "B.Copper",
            "In1.Cu",
            "In2.Cu",
            "In3.Cu",
            "In4.Cu",
        }
    )

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

        # Extract executable name from full path (handle Windows paths properly)
        exec_path = cmd[0]
        # Handle Windows paths (backslashes) and Unix paths (forward slashes)
        # Use rsplit to split from the right, getting the last component
        if "\\" in exec_path:
            # Windows-style path
            executable = exec_path.split("\\")[-1]
        elif "/" in exec_path:
            # Unix-style path
            executable = exec_path.split("/")[-1]
        else:
            # No path separators, just the executable name
            executable = exec_path
        # Remove extension (*.exe, etc.)
        executable = executable.rsplit(".", 1)[0] if "." in executable else executable
        if executable not in self.allowed_executables:
            raise SecurityError(f"Executable not allowed: {executable!r}")

        # Validate ALL arguments - not just subcommands
        self._validate_all_args(cmd[1:])

    def _validate_all_args(self, args: Sequence[str]) -> None:
        """Validate all command arguments."""
        i = 0
        while i < len(args):
            arg = args[i]

            if arg.startswith("-"):
                # This is a flag/option
                # Validate the flag name
                # Remove leading dashes (e.g., "--output" -> "output")
                flag_name = arg.lstrip("-")
                if not flag_name:
                    raise SecurityError("Empty flag name")

                # Special case: - and -- are sometimes used as placeholders
                # but we'll be strict and require named flags
                if flag_name == "-":
                    raise SecurityError("Invalid flag: single dash")

                # Check if this flag has a value (does next arg exist and not start with -?)
                if i + 1 < len(args) and not args[i + 1].startswith("-"):
                    value = args[i + 1]
                    self._validate_flag_value(value, flag_name)
                    i += 2  # Skip both flag and value
                else:
                    # Flag without value (boolean flag like --verbose)
                    i += 1
            else:
                # Not a flag - must be a subcommand, file path, or value
                self._validate_non_flag_arg(arg)
                i += 1

    def _validate_non_flag_arg(self, arg: str) -> None:
        """Validate a non-flag argument (subcommand, file path, or value)."""
        # Check for subcommand
        if arg in ALLOWED_CLI_COMMANDS or arg in ALLOWED_CLI_SUBCOMMANDS:
            return  # Valid subcommand

        # Must be a file path or other value
        # KiCad commands typically take file paths after subcommands
        if self._looks_like_path(arg):
            self._validate_file_path(arg)
        elif self._is_safe_literal(arg):
            return  # Safe literal value
        else:
            raise SecurityError(f"Invalid command argument: {arg!r}")

    def _looks_like_path(self, arg: str) -> bool:
        """Check if argument looks like a file path."""
        # Common path indicators
        if "/" in arg or "\\" in arg:
            return True
        # KiCad files often end with common extensions
        for ext in [".kicad_pcb", ".kicad_sch", ".kicad_mod", ".kicad_pro", ".kicad_sym"]:
            if arg.endswith(ext):
                return True
        return False

    def _looks_like_suspicious_path(self, path: str) -> bool:
        """Check if an absolute path looks like a suspicious attempt to masquerade."""
        # Extract just the filename part
        if "/" in path:
            filename = path.rsplit("/", 1)[-1]
        elif "\\" in path:
            filename = path.rsplit("\\", 1)[-1]
        else:
            filename = path

        # Check if the filename looks like a system file (e.g., passwd, shadow)
        # followed by a KiCad extension
        suspicious_prefixes = {"passwd", "shadow", "group", "hosts", "resolv"}
        name_without_ext = filename.rsplit(".", 1)[0]

        if name_without_ext.lower() in suspicious_prefixes:
            return True

        # Also check for other common suspicious patterns
        return name_without_ext.startswith("etc") or name_without_ext.startswith("var")

    def _validate_file_path(self, path: str) -> None:
        """Validate a file path argument."""
        # Reject null bytes
        if "\x00" in path:
            raise SecurityError("Path contains null bytes")

        # Reject path traversal in the raw string
        if ".." in path:
            raise SecurityError(f"Path traversal detected: {path}")

        # Allow absolute paths that end with KiCad extensions AND look like legitimate paths
        # These are acceptable when passed to kicad-cli which handles path resolution
        kiCad_extensions = (
            ".kicad_pcb",
            ".kicad_sch",
            ".kicad_mod",
            ".kicad_pro",
            ".kicad_sym",
            ".kicad_wks",
            ".kicad_dru",
            ".kicad_sym",
        )

        # Only allow absolute paths with KiCad extensions if they don't look suspicious
        # A legitimate KiCad file path should have a directory component with valid characters
        if path.startswith(("/", "~")) and any(path.endswith(ext) for ext in kiCad_extensions):
            # Reject paths that try to masquerade as KiCad files (e.g., /etc/passwd.kicad_pcb)
            # by checking the directory part doesn't look suspicious
            if self._looks_like_suspicious_path(path):
                raise SecurityError(f"Absolute paths not allowed: {path}")
            return  # Allow known KiCad file paths

        # Reject absolute paths that don't match KiCad extension patterns
        # Note: Relative paths are always allowed - this is safer for subprocess calls
        # and the trusted root validation happens at the PathValidator level for file I/O
        if path.startswith(("/", "~")):
            # Reject absolute paths not matching KiCad patterns
            raise SecurityError(f"Absolute paths not allowed: {path}")

    def _validate_flag_value(self, value: str, flag_name: str) -> None:
        """Validate a flag's value."""
        # Certain flags should only accept specific values
        if flag_name in {"format", "layer", "units"}:
            self._validate_known_value(value, flag_name)
        else:
            # Generic validation - could be a path or value
            if self._looks_like_path(value):
                self._validate_file_path(value)
            elif self._is_safe_literal(value):
                return
            else:
                raise SecurityError(f"Invalid value for flag --{flag_name}: {value!r}")

    def _validate_known_value(self, value: str, flag_name: str) -> None:
        """Validate value against known-safe set for specific flags."""
        safe_values: dict[str, frozenset[str]] = {
            "format": frozenset(
                {"json", "svg", "pdf", "dxf", "gerber", "step", "vrml", "pos", "gerbers"}
            ),
            "units": frozenset({"mm", "mil", "in", "cm"}),
        }

        if flag_name in safe_values and value not in safe_values[flag_name]:
            raise SecurityError(
                f"Invalid value for --{flag_name}: {value!r}. "
                f"Expected one of: {', '.join(sorted(safe_values[flag_name]))}"
            )

    def _is_safe_literal(self, value: str) -> bool:
        """Check if value is a safe literal (layer name, number, etc.)."""
        # Empty string is ok in some contexts
        if not value:
            return True

        # Whitespace-only is suspicious
        if value.strip() != value:
            return False

        # Layer names (KiCad style)
        if value.replace(".", "").replace("_", "").replace(" ", "").isalnum():
            return True

        # Numbers (including negative and decimal)
        try:
            float(value)
            return True
        except ValueError:
            pass

        # Specific known-safe patterns
        return bool(
            value
            and (value[0].isalpha() or value[0].isdigit())
            and value.replace("_", "").isalnum()
        )
