"""MCP Prompt templates — conversation starters for common PCB tasks.

Prompts provide structured conversation templates that help LLMs
approach common PCB design tasks with the right context and methodology.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register prompt templates with the MCP server."""

    @mcp.prompt()
    def design_review() -> str:
        """Review the current PCB design for common issues.

        Analyzes component placement, net connectivity, layer usage,
        and provides actionable recommendations.
        """
        from .. import state

        if not state.is_loaded():
            return (
                "No board is currently loaded. Please use the open_project tool "
                "to load a .kicad_pcb file first, then request a design review."
            )

        summary = state.get_summary()
        return (
            f"Please review the PCB design '{summary.title}' for common issues.\n\n"
            f"Board summary:\n"
            f"- {summary.footprint_count} components\n"
            f"- {summary.net_count} nets\n"
            f"- {len(summary.copper_layers)} copper layers: {', '.join(summary.copper_layers)}\n"
            f"- Board thickness: {summary.thickness}mm\n"
            f"- Routed segments: {summary.segment_count}\n\n"
            f"Please check for:\n"
            f"1. Unconnected nets (ratsnest)\n"
            f"2. Component placement issues (overlaps, clearance)\n"
            f"3. Missing decoupling capacitors near ICs\n"
            f"4. Proper power distribution\n"
            f"5. Signal integrity concerns\n"
            f"6. Manufacturing constraints (trace width, via size, clearance)\n\n"
            f"Use get_board_info, list_components, and the analysis tools "
            f"(via execute_tool) to investigate specific areas."
        )

    @mcp.prompt()
    def drc_troubleshoot(error_type: str = "all") -> str:
        """Help troubleshoot DRC (Design Rule Check) violations.

        Args:
            error_type: Type of DRC error to focus on (e.g., 'clearance', 'unconnected', 'all').
        """
        return (
            f"Help me troubleshoot DRC violations in my PCB design.\n\n"
            f"Focus area: {error_type}\n\n"
            f"Steps:\n"
            f"1. First, run the DRC using the run_drc tool (if available)\n"
            f"2. Review the violations and categorize them by severity\n"
            f"3. For each violation:\n"
            f"   - Explain what the violation means\n"
            f"   - Suggest the most likely fix\n"
            f"   - Indicate if it's critical or can be waived\n"
            f"4. Provide a prioritized action plan\n\n"
            f"Common DRC issues:\n"
            f"- Clearance violations: traces or pads too close together\n"
            f"- Unconnected items: nets that should be connected but aren't\n"
            f"- Track width violations: traces narrower than minimum\n"
            f"- Via violations: vias smaller than minimum drill size\n"
            f"- Courtyard overlaps: component courtyards intersecting"
        )

    @mcp.prompt()
    def component_placement_review() -> str:
        """Review component placement for manufacturability and signal integrity."""
        from .. import state

        if not state.is_loaded():
            return (
                "No board is currently loaded. Please use the open_project tool "
                "to load a .kicad_pcb file first."
            )

        summary = state.get_summary()
        footprints = state.get_footprints()

        # Group by library prefix for summary
        lib_counts: dict[str, int] = {}
        for fp in footprints:
            lib = fp.library.split(":")[0] if ":" in fp.library else fp.library
            lib_counts[lib] = lib_counts.get(lib, 0) + 1

        lib_summary = "\n".join(
            f"  - {lib}: {count}" for lib, count in sorted(lib_counts.items()) if lib
        )

        return (
            f"Review component placement for '{summary.title}'.\n\n"
            f"Board has {summary.footprint_count} components:\n"
            f"{lib_summary}\n\n"
            f"Please evaluate:\n"
            f"1. Component grouping (related components should be close together)\n"
            f"2. Decoupling capacitor placement (should be near IC power pins)\n"
            f"3. Crystal/oscillator placement (should be close to MCU)\n"
            f"4. Connector placement (edge of board, accessible)\n"
            f"5. Thermal considerations (power components need thermal relief)\n"
            f"6. Assembly considerations (consistent orientation, pick-and-place friendly)\n\n"
            f"Use find_component and get_component_details to inspect specific components."
        )
