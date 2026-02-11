"""kicad-cli backend — DRC, export, and rendering via KiCad's CLI tool.

kicad-cli is the official command-line interface (KiCad 8+) that handles
DRC, Gerber export, PDF rendering, and other operations without the GUI.

This backend auto-detects the kicad-cli path and provides a safe wrapper
with timeouts and command validation.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..schema.drc import DrcResult, DrcViolation, ExportResult

# Common installation paths for kicad-cli
_SEARCH_PATHS = [
    r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
    r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
    r"C:\Program Files\KiCad\bin\kicad-cli.exe",
    "/usr/bin/kicad-cli",
    "/usr/local/bin/kicad-cli",
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
]

DEFAULT_TIMEOUT = 120  # seconds


class KiCadCliNotFound(Exception):
    """Raised when kicad-cli cannot be found."""


class KiCadCliError(Exception):
    """Raised when kicad-cli returns an error."""


class KiCadCli:
    """Wrapper around the kicad-cli command-line tool."""

    def __init__(self, cli_path: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.cli_path = cli_path or self._find_cli()
        self.timeout = timeout

    @staticmethod
    def _find_cli() -> str:
        """Auto-detect kicad-cli path."""
        # Check PATH first
        from shutil import which

        found = which("kicad-cli")
        if found:
            return found

        # Check common installation paths
        for path in _SEARCH_PATHS:
            if Path(path).is_file():
                return path

        # Glob fallback — find versioned installations (e.g. 9.0.2, 9.1)
        _GLOB_PATTERNS: list[str] = []
        if sys.platform == "win32":
            _GLOB_PATTERNS.append(r"C:\Program Files\KiCad\*\bin\kicad-cli.exe")
        elif sys.platform == "darwin":
            _GLOB_PATTERNS.append("/Applications/KiCad/KiCad*.app/Contents/MacOS/kicad-cli")
        else:
            _GLOB_PATTERNS.append("/usr/lib/kicad/*/bin/kicad-cli")

        for pattern in _GLOB_PATTERNS:
            matches = sorted(glob.glob(pattern), reverse=True)
            if matches:
                return matches[0]

        raise KiCadCliNotFound("kicad-cli not found. Install KiCad 8+ or set the path manually.")

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run a kicad-cli command with timeout and error handling."""
        cmd = [self.cli_path] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return result
        except subprocess.TimeoutExpired as e:
            raise KiCadCliError(f"kicad-cli timed out after {self.timeout}s") from e
        except FileNotFoundError as e:
            raise KiCadCliNotFound(f"kicad-cli not found at {self.cli_path}") from e

    def _format_error(
        self,
        result: subprocess.CompletedProcess[str],
        fallback_message: str,
    ) -> str:
        """Build a rich error message from a failed kicad-cli invocation.

        Combines the CLI path, full command, exit code, and any stderr/stdout
        output into a single diagnostic string.
        """
        cmd_str = " ".join(result.args) if isinstance(result.args, list) else str(result.args)
        output = result.stderr.strip() or result.stdout.strip() or fallback_message
        return (
            f"{output}\n"
            f"  command: {cmd_str}\n"
            f"  exit code: {result.returncode}\n"
            f"  cli path: {self.cli_path}"
        )

    @staticmethod
    def is_available() -> bool:
        """Check if kicad-cli is available on this system."""
        try:
            KiCadCli._find_cli()
            return True
        except KiCadCliNotFound:
            return False

    def version(self) -> str:
        """Get the kicad-cli version string."""
        result = self._run(["version", "--format", "plain"])
        return result.stdout.strip()

    def run_drc(
        self,
        board_path: str,
        output_path: str | None = None,
        severity: str = "all",
    ) -> DrcResult:
        """Run Design Rule Check on a board.

        Args:
            board_path: Path to .kicad_pcb file.
            output_path: Optional path for the JSON report.
            severity: 'all', 'error', 'warning'.

        Returns:
            DrcResult with violation details.
        """
        if not Path(board_path).exists():
            raise FileNotFoundError(f"Board not found: {board_path}")

        # Create temp output file if none specified
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".json", prefix="drc_")
            os.close(fd)

        args = [
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            output_path,
            "--severity-all",
            "--units",
            "mm",
            board_path,
        ]

        result = self._run(args)

        # Parse JSON report
        try:
            report = json.loads(Path(output_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            # JSON not produced — kicad-cli likely failed to run DRC
            message = self._format_error(result, "kicad-cli produced no DRC report")
            return DrcResult(
                passed=False,
                error_count=0,
                warning_count=0,
                report_path=output_path,
                message=f"DRC report unavailable: {message}",
            )

        return self._parse_drc_report(report, output_path, result.stderr.strip())

    @staticmethod
    def _parse_drc_report(report: dict[str, Any], report_path: str, stderr: str = "") -> DrcResult:
        """Parse a kicad-cli DRC JSON report into a DrcResult."""
        violations: list[DrcViolation] = []
        error_count = 0
        warning_count = 0

        for violation_data in report.get("violations", []):
            severity = violation_data.get("severity", "error")
            if severity == "error":
                error_count += 1
            else:
                warning_count += 1

            pos = None
            if "pos" in violation_data:
                pos = {
                    "x": violation_data["pos"].get("x", 0),
                    "y": violation_data["pos"].get("y", 0),
                }

            items = []
            for item in violation_data.get("items", []):
                desc = item.get("description", "")
                if desc:
                    items.append(desc)

            violations.append(
                DrcViolation(
                    type=violation_data.get("type", "unknown"),
                    severity=severity,
                    description=violation_data.get("description", ""),
                    position=pos,
                    items=items,
                )
            )

        for violation_data in report.get("unconnected_items", []):
            error_count += 1
            violations.append(
                DrcViolation(
                    type="unconnected_items",
                    severity="error",
                    description=violation_data.get("description", "Unconnected items"),
                    items=[
                        item.get("description", "")
                        for item in violation_data.get("items", [])
                        if item.get("description")
                    ],
                )
            )

        return DrcResult(
            passed=error_count == 0,
            error_count=error_count,
            warning_count=warning_count,
            violations=violations,
            report_path=report_path,
            message=stderr if stderr and error_count == 0 else "",
        )

    def export_gerbers(
        self,
        board_path: str,
        output_dir: str,
    ) -> ExportResult:
        """Export Gerber files for manufacturing.

        Args:
            board_path: Path to .kicad_pcb file.
            output_dir: Directory to save Gerber files.
        """
        if not Path(board_path).exists():
            raise FileNotFoundError(f"Board not found: {board_path}")

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        args = [
            "pcb",
            "export",
            "gerbers",
            "--output",
            output_dir + "/",
            board_path,
        ]

        result = self._run(args)
        if result.returncode != 0:
            return ExportResult(
                success=False,
                output_path=output_dir,
                message=self._format_error(result, "Gerber export failed"),
            )

        return ExportResult(
            success=True,
            output_path=output_dir,
            message="Gerber files exported successfully",
        )

    def export_drill(
        self,
        board_path: str,
        output_dir: str,
    ) -> ExportResult:
        """Export drill files.

        Args:
            board_path: Path to .kicad_pcb file.
            output_dir: Directory to save drill files.
        """
        if not Path(board_path).exists():
            raise FileNotFoundError(f"Board not found: {board_path}")

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        args = [
            "pcb",
            "export",
            "drill",
            "--output",
            output_dir + "/",
            board_path,
        ]

        result = self._run(args)
        if result.returncode != 0:
            return ExportResult(
                success=False,
                output_path=output_dir,
                message=self._format_error(result, "Drill export failed"),
            )

        return ExportResult(
            success=True,
            output_path=output_dir,
            message="Drill files exported successfully",
        )

    def export_pdf(
        self,
        board_path: str,
        output_path: str,
        layers: list[str] | None = None,
    ) -> ExportResult:
        """Export board to PDF.

        Args:
            board_path: Path to .kicad_pcb file.
            output_path: Path for the output PDF.
            layers: Optional list of layer names to include.
        """
        if not Path(board_path).exists():
            raise FileNotFoundError(f"Board not found: {board_path}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if not layers:
            layers = ["F.Cu", "B.Cu", "F.SilkS", "B.SilkS", "Edge.Cuts"]

        args = [
            "pcb",
            "export",
            "pdf",
            "--output",
            output_path,
            "--layers",
            ",".join(layers),
            board_path,
        ]

        result = self._run(args)
        if result.returncode != 0:
            return ExportResult(
                success=False,
                output_path=output_path,
                message=self._format_error(result, "PDF export failed"),
            )

        return ExportResult(
            success=True,
            output_path=output_path,
            message="PDF exported successfully",
        )

    def export_svg(
        self,
        board_path: str,
        output_path: str,
        layers: list[str] | None = None,
    ) -> ExportResult:
        """Export board to SVG.

        Args:
            board_path: Path to .kicad_pcb file.
            output_path: Path for the output SVG.
            layers: Optional list of layer names to include.
        """
        if not Path(board_path).exists():
            raise FileNotFoundError(f"Board not found: {board_path}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if not layers:
            layers = ["F.Cu", "B.Cu", "F.SilkS", "B.SilkS", "Edge.Cuts"]

        args = [
            "pcb",
            "export",
            "svg",
            "--output",
            output_path,
            "--layers",
            ",".join(layers),
            board_path,
        ]

        result = self._run(args)
        if result.returncode != 0:
            return ExportResult(
                success=False,
                output_path=output_path,
                message=self._format_error(result, "SVG export failed"),
            )

        return ExportResult(
            success=True,
            output_path=output_path,
            message="SVG exported successfully",
        )

    def export_step(
        self,
        board_path: str,
        output_path: str,
    ) -> ExportResult:
        """Export board as 3D STEP model.

        Args:
            board_path: Path to .kicad_pcb file.
            output_path: Path for the output STEP file.
        """
        if not Path(board_path).exists():
            raise FileNotFoundError(f"Board not found: {board_path}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        args = [
            "pcb",
            "export",
            "step",
            "--output",
            output_path,
            board_path,
        ]

        result = self._run(args)
        if result.returncode != 0:
            return ExportResult(
                success=False,
                output_path=output_path,
                message=self._format_error(result, "STEP export failed"),
            )

        return ExportResult(
            success=True,
            output_path=output_path,
            message="STEP file exported successfully",
        )

    def export_vrml(
        self,
        board_path: str,
        output_path: str,
    ) -> ExportResult:
        """Export board as VRML 3D model.

        Args:
            board_path: Path to .kicad_pcb file.
            output_path: Path for the output VRML file.
        """
        if not Path(board_path).exists():
            raise FileNotFoundError(f"Board not found: {board_path}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        args = [
            "pcb",
            "export",
            "vrml",
            "--output",
            output_path,
            board_path,
        ]

        result = self._run(args)
        if result.returncode != 0:
            return ExportResult(
                success=False,
                output_path=output_path,
                message=self._format_error(result, "VRML export failed"),
            )

        return ExportResult(
            success=True,
            output_path=output_path,
            message="VRML file exported successfully",
        )

    def export_pos(
        self,
        board_path: str,
        output_path: str,
        side: str = "both",
    ) -> ExportResult:
        """Export component position file (pick-and-place).

        Args:
            board_path: Path to .kicad_pcb file.
            output_path: Path for the output position file.
            side: 'front', 'back', or 'both'.
        """
        if not Path(board_path).exists():
            raise FileNotFoundError(f"Board not found: {board_path}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        args = [
            "pcb",
            "export",
            "pos",
            "--output",
            output_path,
            "--side",
            side,
            "--units",
            "mm",
            board_path,
        ]

        result = self._run(args)
        if result.returncode != 0:
            return ExportResult(
                success=False,
                output_path=output_path,
                message=self._format_error(result, "Position file export failed"),
            )

        return ExportResult(
            success=True,
            output_path=output_path,
            message="Position file exported successfully",
        )
