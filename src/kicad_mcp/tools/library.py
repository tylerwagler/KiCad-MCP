"""Library search and browsing tools."""

from __future__ import annotations

from typing import Any

from .registry import register_tool


def _list_libraries_handler() -> dict[str, Any]:
    """List all available symbol and footprint libraries."""
    from ..library import discover_lib_tables

    tables = discover_lib_tables()
    return {
        "symbol_libraries": {
            "count": len(tables["symbol_libraries"]),
            "libraries": [e.to_dict() for e in tables["symbol_libraries"]],
        },
        "footprint_libraries": {
            "count": len(tables["footprint_libraries"]),
            "libraries": [e.to_dict() for e in tables["footprint_libraries"]],
        },
    }


def _search_symbols_handler(
    query: str,
    library: str | None = None,
    max_results: int = 50,
) -> dict[str, Any]:
    """Search for symbols by name, keyword, or description.

    Args:
        query: Search string (e.g., "resistor", "op amp", "LM317").
        library: Optional library name to restrict search (e.g., "Device").
        max_results: Maximum number of results. Default: 50.
    """
    from ..library import discover_lib_tables, search_symbols

    libs = None
    if library:
        tables = discover_lib_tables()
        libs = [e for e in tables["symbol_libraries"] if e.name == library]
        if not libs:
            return {"error": f"Symbol library '{library}' not found"}

    results = search_symbols(query, libraries=libs, max_results=max_results)
    return {
        "query": query,
        "count": len(results),
        "symbols": [s.to_dict() for s in results],
    }


def _search_footprints_handler(
    query: str,
    library: str | None = None,
    max_results: int = 50,
) -> dict[str, Any]:
    """Search for footprints by name, tags, or description.

    Args:
        query: Search string (e.g., "0402", "QFP", "SOT-23").
        library: Optional library name to restrict search (e.g., "Resistor_SMD").
        max_results: Maximum number of results. Default: 50.
    """
    from ..library import discover_lib_tables, search_footprints

    libs = None
    if library:
        tables = discover_lib_tables()
        libs = [e for e in tables["footprint_libraries"] if e.name == library]
        if not libs:
            return {"error": f"Footprint library '{library}' not found"}

    results = search_footprints(query, libraries=libs, max_results=max_results)
    return {
        "query": query,
        "count": len(results),
        "footprints": [f.to_dict() for f in results],
    }


def _list_symbols_in_lib_handler(library: str) -> dict[str, Any]:
    """List all symbols in a specific symbol library.

    Args:
        library: Library name (e.g., "Device", "Amplifier_Operational").
    """
    from pathlib import Path

    from ..library import discover_lib_tables, list_symbols_in_library

    tables = discover_lib_tables()
    matches = [e for e in tables["symbol_libraries"] if e.name == library]
    if not matches:
        return {"error": f"Symbol library '{library}' not found"}

    lib_path = Path(matches[0].uri)
    if not lib_path.exists():
        return {"error": f"Library file not found: {matches[0].uri}"}

    symbols = list_symbols_in_library(lib_path)
    return {
        "library": library,
        "count": len(symbols),
        "symbols": [s.to_dict() for s in symbols],
    }


def _list_footprints_in_lib_handler(library: str) -> dict[str, Any]:
    """List all footprints in a specific footprint library.

    Args:
        library: Library name (e.g., "Resistor_SMD", "Package_QFP").
    """
    from pathlib import Path

    from ..library import discover_lib_tables, list_footprints_in_library

    tables = discover_lib_tables()
    matches = [e for e in tables["footprint_libraries"] if e.name == library]
    if not matches:
        return {"error": f"Footprint library '{library}' not found"}

    lib_path = Path(matches[0].uri)
    if not lib_path.is_dir():
        return {"error": f"Library directory not found: {matches[0].uri}"}

    footprints = list_footprints_in_library(lib_path)
    return {
        "library": library,
        "count": len(footprints),
        "footprints": [f.to_dict() for f in footprints],
    }


def _get_footprint_details_handler(library: str, footprint: str) -> dict[str, Any]:
    """Get detailed information about a specific footprint.

    Args:
        library: Library name (e.g., "Resistor_SMD").
        footprint: Footprint name (e.g., "R_0402_1005Metric").
    """
    from pathlib import Path

    from ..library import discover_lib_tables, get_footprint_details

    tables = discover_lib_tables()
    matches = [e for e in tables["footprint_libraries"] if e.name == library]
    if not matches:
        return {"error": f"Footprint library '{library}' not found"}

    lib_path = Path(matches[0].uri)
    mod_path = lib_path / f"{footprint}.kicad_mod"
    if not mod_path.exists():
        return {"error": f"Footprint '{footprint}' not found in {library}"}

    info = get_footprint_details(mod_path)
    if info is None:
        return {"error": f"Failed to parse footprint '{footprint}'"}

    d = info.to_dict()
    d["pads"] = info.pads
    return {"found": True, **d}


# ── Registration ────────────────────────────────────────────────────

register_tool(
    name="list_libraries",
    description="List all available KiCad symbol and footprint libraries.",
    parameters={},
    handler=_list_libraries_handler,
    category="library",
    direct=True,
)

register_tool(
    name="search_symbols",
    description="Search for symbols by name, keyword, or description across all libraries.",
    parameters={
        "query": {
            "type": "string",
            "description": "Search string (e.g., 'resistor', 'op amp', 'LM317').",
        },
        "library": {
            "type": "string",
            "description": "Optional: restrict search to a specific library.",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum results to return. Default: 50.",
        },
    },
    handler=_search_symbols_handler,
    category="library",
)

register_tool(
    name="search_footprints",
    description="Search for footprints by name, tags, or description across all libraries.",
    parameters={
        "query": {
            "type": "string",
            "description": "Search string (e.g., '0402', 'QFP', 'SOT-23').",
        },
        "library": {
            "type": "string",
            "description": "Optional: restrict search to a specific library.",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum results to return. Default: 50.",
        },
    },
    handler=_search_footprints_handler,
    category="library",
)

register_tool(
    name="list_symbols_in_library",
    description="List all symbols in a specific symbol library.",
    parameters={
        "library": {
            "type": "string",
            "description": "Library name (e.g., 'Device', 'Amplifier_Operational').",
        },
    },
    handler=_list_symbols_in_lib_handler,
    category="library",
)

register_tool(
    name="list_footprints_in_library",
    description="List all footprints in a specific footprint library.",
    parameters={
        "library": {
            "type": "string",
            "description": "Library name (e.g., 'Resistor_SMD', 'Package_QFP').",
        },
    },
    handler=_list_footprints_in_lib_handler,
    category="library",
)

register_tool(
    name="get_footprint_details",
    description="Get detailed info about a specific footprint (pads, layers, dimensions).",
    parameters={
        "library": {
            "type": "string",
            "description": "Library name (e.g., 'Resistor_SMD').",
        },
        "footprint": {
            "type": "string",
            "description": "Footprint name (e.g., 'R_0402_1005Metric').",
        },
    },
    handler=_get_footprint_details_handler,
    category="library",
)
