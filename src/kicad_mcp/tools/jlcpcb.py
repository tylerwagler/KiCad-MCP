"""JLCPCB parts catalog tools — search, availability, auto-assign, BOM+CPL export."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from .. import state
from .registry import register_tool


def _jlcpcb_search_handler(
    query: str,
    package: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search the JLCPCB parts catalog.

    Args:
        query: Search string (e.g., "100nF", "STM32F103", "0.1uF 0805").
        package: Optional package filter (e.g., "0805", "SOIC-8").
        limit: Maximum results to return. Default: 20.
    """
    from ..manufacturers.jlcpcb import JlcpcbApiError, search_parts

    try:
        result = search_parts(query=query, package=package, limit=limit)
        return result.to_dict()
    except JlcpcbApiError as e:
        return {"error": str(e)}


def _jlcpcb_check_availability_handler(lcsc_code: str) -> dict[str, Any]:
    """Check availability and pricing of a specific JLCPCB part.

    Args:
        lcsc_code: LCSC part number (e.g., "C123456").
    """
    from ..manufacturers.jlcpcb import JlcpcbApiError, get_part_details

    try:
        part = get_part_details(lcsc_code)
    except JlcpcbApiError as e:
        return {"error": str(e)}

    if part is None:
        return {"found": False, "message": f"Part {lcsc_code} not found in JLCPCB catalog."}

    return {
        "found": True,
        "in_stock": part.stock > 0,
        "part": part.to_dict(),
    }


def _jlcpcb_auto_assign_handler(
    prefer_basic: bool = True,
    references: str | None = None,
) -> dict[str, Any]:
    """Auto-assign JLCPCB parts to board components.

    Searches the JLCPCB catalog for each component using its value and
    footprint package, then assigns the best match (preferring basic parts).

    Args:
        prefer_basic: Prefer JLCPCB basic parts (lower assembly fee). Default: true.
        references: Comma-separated list of reference designators to process
                    (e.g., "R1,R2,C1"). All components if omitted.
    """
    from ..manufacturers.jlcpcb import (
        JlcpcbApiError,
        extract_package_from_library,
        search_parts,
    )

    try:
        footprints = state.get_footprints()
    except Exception as e:
        return {"error": f"No board loaded: {e}. Use open_project first."}

    ref_filter = None
    if references:
        ref_filter = {r.strip() for r in references.split(",")}

    assignments: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for fp in footprints:
        if not fp.reference or not fp.value:
            skipped.append(
                {
                    "reference": fp.reference or "?",
                    "reason": "missing reference or value",
                }
            )
            continue

        if ref_filter and fp.reference not in ref_filter:
            continue

        # Extract package from library identifier
        pkg = extract_package_from_library(fp.library)

        # Build search query
        search_query = fp.value
        if pkg:
            search_query = f"{fp.value} {pkg}"

        try:
            result = search_parts(query=search_query, package=pkg, limit=5)
        except JlcpcbApiError as e:
            errors.append({"reference": fp.reference, "error": str(e)})
            continue

        if not result.parts:
            skipped.append({"reference": fp.reference, "reason": "no matching parts found"})
            continue

        # Rank: basic-first (if preferred), then by stock descending
        ranked = sorted(
            result.parts,
            key=lambda p: (
                not (p.basic and prefer_basic),  # basic first when preferred
                -p.stock,  # then highest stock
            ),
        )

        best = ranked[0]
        confidence = "high" if pkg else "medium"
        if not best.basic:
            confidence = "low" if confidence == "medium" else "medium"

        from ..manufacturers.jlcpcb import JlcpcbAssignment

        assignment = JlcpcbAssignment(
            reference=fp.reference,
            value=fp.value,
            footprint=fp.library,
            lcsc=best.lcsc_code,
            mfr=best.mfr,
            description=best.description,
            basic=best.basic,
            confidence=confidence,
            alternatives=[p.to_dict() for p in ranked[1:4]],
        )
        assignments.append(assignment.to_dict())

    return {
        "assigned": len(assignments),
        "skipped": len(skipped),
        "errors": len(errors),
        "assignments": assignments,
        "skipped_details": skipped,
        "error_details": errors,
    }


def _jlcpcb_export_bom_cpl_handler(
    output_dir: str | None = None,
    assignments: str | None = None,
) -> dict[str, Any]:
    """Export JLCPCB-format BOM and CPL (pick-and-place) CSV files.

    Args:
        output_dir: Directory to save CSV files. Returns CSV content if omitted.
        assignments: JSON mapping of reference to LCSC code, e.g. '{"R1": "C123456"}'.
                     If omitted, LCSC column will be empty.
    """
    try:
        footprints = state.get_footprints()
    except Exception as e:
        return {"error": f"No board loaded: {e}. Use open_project first."}

    lcsc_map: dict[str, str] = {}
    if assignments:
        try:
            lcsc_map = json.loads(assignments)
        except json.JSONDecodeError as e:
            return {"error": f"Invalid assignments JSON: {e}"}

    # ── BOM CSV ──
    # Group by value + footprint + LCSC
    bom_groups: dict[str, dict[str, Any]] = {}
    for fp in footprints:
        if not fp.reference:
            continue
        lcsc = lcsc_map.get(fp.reference, "")
        key = f"{fp.value}|{fp.library}|{lcsc}"
        if key not in bom_groups:
            bom_groups[key] = {
                "comment": fp.value,
                "footprint": fp.library,
                "lcsc": lcsc,
                "designators": [],
            }
        bom_groups[key]["designators"].append(fp.reference)

    bom_buf = io.StringIO()
    bom_writer = csv.writer(bom_buf)
    bom_writer.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
    for group in sorted(bom_groups.values(), key=lambda g: g["designators"][0]):
        bom_writer.writerow(
            [
                group["comment"],
                ",".join(sorted(group["designators"])),
                group["footprint"],
                group["lcsc"],
            ]
        )

    bom_csv = bom_buf.getvalue()

    # ── CPL CSV ──
    cpl_buf = io.StringIO()
    cpl_writer = csv.writer(cpl_buf)
    cpl_writer.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for fp in sorted(footprints, key=lambda f: f.reference):
        if not fp.reference:
            continue
        layer = "Top" if fp.layer == "F.Cu" else "Bottom"
        cpl_writer.writerow(
            [
                fp.reference,
                f"{fp.position.x:.4f}mm",
                f"{fp.position.y:.4f}mm",
                layer,
                f"{fp.position.angle:.1f}",
            ]
        )

    cpl_csv = cpl_buf.getvalue()

    result: dict[str, Any] = {
        "bom_csv": bom_csv,
        "cpl_csv": cpl_csv,
        "bom_rows": len(bom_groups),
        "cpl_rows": len([fp for fp in footprints if fp.reference]),
    }

    # Write files if output_dir specified
    if output_dir:
        from pathlib import Path

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        bom_path = out / "BOM_jlcpcb.csv"
        cpl_path = out / "CPL_jlcpcb.csv"
        bom_path.write_text(bom_csv, encoding="utf-8")
        cpl_path.write_text(cpl_csv, encoding="utf-8")
        result["bom_path"] = str(bom_path)
        result["cpl_path"] = str(cpl_path)

    return result


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="jlcpcb_search_parts",
    description="Search the JLCPCB parts catalog for components by name, value, or part number.",
    parameters={
        "query": {
            "type": "string",
            "description": "Search string (e.g., '100nF', 'STM32F103', '0.1uF 0805').",
        },
        "package": {
            "type": "string",
            "description": "Optional package filter (e.g., '0805', 'SOIC-8').",
        },
        "limit": {
            "type": "integer",
            "description": "Max results to return. Default: 20.",
        },
    },
    handler=_jlcpcb_search_handler,
    category="jlcpcb",
)

register_tool(
    name="jlcpcb_check_availability",
    description="Check availability and pricing of a specific JLCPCB part by LCSC code.",
    parameters={
        "lcsc_code": {
            "type": "string",
            "description": "LCSC part number (e.g., 'C123456').",
        },
    },
    handler=_jlcpcb_check_availability_handler,
    category="jlcpcb",
)

register_tool(
    name="jlcpcb_auto_assign",
    description=(
        "Auto-assign JLCPCB parts to board components based on value and footprint. "
        "Requires a loaded board."
    ),
    parameters={
        "prefer_basic": {
            "type": "boolean",
            "description": "Prefer basic parts (lower assembly fee). Default: true.",
        },
        "references": {
            "type": "string",
            "description": "Comma-separated references to process (e.g., 'R1,R2,C1').",
        },
    },
    handler=_jlcpcb_auto_assign_handler,
    category="jlcpcb",
)

register_tool(
    name="jlcpcb_export_bom_cpl",
    description=(
        "Export JLCPCB-format BOM and CPL (pick-and-place) CSV files for SMT assembly ordering."
    ),
    parameters={
        "output_dir": {
            "type": "string",
            "description": "Directory to save CSVs. Returns content only if omitted.",
        },
        "assignments": {
            "type": "string",
            "description": 'JSON mapping reference→LCSC code, e.g. \'{"R1": "C123456"}\'.',
        },
    },
    handler=_jlcpcb_export_bom_cpl_handler,
    category="jlcpcb",
)
