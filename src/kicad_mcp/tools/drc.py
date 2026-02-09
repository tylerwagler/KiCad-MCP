"""DRC tools — run design rule checks via kicad-cli."""

from __future__ import annotations

from typing import Any

from .registry import register_tool


def _run_drc_handler(output_path: str | None = None) -> dict[str, Any]:
    """Run Design Rule Check (DRC) on the currently loaded board.

    Args:
        output_path: Optional path to save the DRC report JSON.
    """
    from .. import state
    from ..backends.kicad_cli import KiCadCli, KiCadCliNotFound

    board_path = state.get_board_path()
    if not board_path:
        return {"error": "No board loaded. Use open_project first."}

    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found. Install KiCad 8+ to use DRC."}

    result = cli.run_drc(board_path, output_path=output_path)
    return result.to_dict()


def _get_drc_violations_handler(severity: str = "all") -> dict[str, Any]:
    """Get DRC violations from the most recent DRC run, filtered by severity.

    Args:
        severity: Filter by severity: 'all', 'error', or 'warning'.
    """
    from .. import state
    from ..backends.kicad_cli import KiCadCli, KiCadCliNotFound

    board_path = state.get_board_path()
    if not board_path:
        return {"error": "No board loaded. Use open_project first."}

    try:
        cli = KiCadCli()
    except KiCadCliNotFound:
        return {"error": "kicad-cli not found. Install KiCad 8+ to use DRC."}

    result = cli.run_drc(board_path)
    violations = result.violations

    if severity != "all":
        violations = [v for v in violations if v.severity == severity]

    return {
        "severity_filter": severity,
        "count": len(violations),
        "violations": [v.to_dict() for v in violations],
    }


# DRC direct tool
register_tool(
    name="run_drc",
    description=(
        "Run Design Rule Check (DRC) on the currently loaded board."
        " Returns violations with severity and descriptions."
    ),
    parameters={
        "output_path": {
            "type": "string",
            "description": "Optional path to save the DRC report JSON.",
        },
    },
    handler=_run_drc_handler,
    category="drc",
    direct=True,
)

# DRC routed tools
register_tool(
    name="get_drc_violations",
    description="Get DRC violations filtered by severity (all, error, warning).",
    parameters={
        "severity": {
            "type": "string",
            "description": "Filter: 'all', 'error', or 'warning'.",
        },
    },
    handler=_get_drc_violations_handler,
    category="drc",
)
