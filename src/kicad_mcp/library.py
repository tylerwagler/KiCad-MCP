"""Library discovery and search for KiCad symbol and footprint libraries."""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path
from typing import Any

from .schema.library import FootprintInfo, LibraryEntry, SymbolInfo
from .sexp import Document


def _kicad_env_paths() -> dict[str, Path]:
    """Resolve KiCad environment variable paths."""
    paths: dict[str, Path] = {}
    system = platform.system()

    if system == "Windows":
        candidates = [
            Path(r"C:\Program Files\KiCad\9.0"),
            Path(r"C:\Program Files\KiCad\8.0"),
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport"),
        ]
    else:
        candidates = [
            Path("/usr/share/kicad"),
            Path("/usr/local/share/kicad"),
        ]

    for base in candidates:
        sym_dir = base / "share" / "kicad" / "symbols"
        if not sym_dir.exists():
            sym_dir = base / "symbols"
        fp_dir = base / "share" / "kicad" / "footprints"
        if not fp_dir.exists():
            fp_dir = base / "footprints"
        if sym_dir.exists():
            paths["KICAD9_SYMBOL_DIR"] = sym_dir
            paths["KICAD8_SYMBOL_DIR"] = sym_dir
        if fp_dir.exists():
            paths["KICAD9_FOOTPRINT_DIR"] = fp_dir
            paths["KICAD8_FOOTPRINT_DIR"] = fp_dir
        if sym_dir.exists() or fp_dir.exists():
            break

    # Also check environment variables
    for var in ("KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD_SYMBOL_DIR"):
        val = os.environ.get(var)
        if val and Path(val).exists():
            paths[var] = Path(val)
            break
    for var in ("KICAD9_FOOTPRINT_DIR", "KICAD8_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR"):
        val = os.environ.get(var)
        if val and Path(val).exists():
            paths[var] = Path(val)
            break

    return paths


def _resolve_uri(uri: str, env: dict[str, Path]) -> Path:
    """Resolve a library URI, expanding ${VAR} variables."""
    resolved = uri
    for var, path in env.items():
        resolved = resolved.replace(f"${{{var}}}", str(path))
    return Path(resolved)


def _user_config_dir() -> Path:
    """Return the KiCad user config directory."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Preferences"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    # Try KiCad 9 first, then 8
    for ver in ("9.0", "8.0"):
        d = base / "kicad" / ver
        if d.exists():
            return d
    return base / "kicad" / "9.0"


def discover_lib_tables() -> dict[str, list[LibraryEntry]]:
    """Discover all symbol and footprint library tables.

    Returns a dict with keys 'symbol_libraries' and 'footprint_libraries'.
    """
    config = _user_config_dir()
    env = _kicad_env_paths()

    result: dict[str, list[LibraryEntry]] = {
        "symbol_libraries": [],
        "footprint_libraries": [],
    }

    sym_table = config / "sym-lib-table"
    if sym_table.exists():
        result["symbol_libraries"] = _parse_lib_table(sym_table, env)

    fp_table = config / "fp-lib-table"
    if fp_table.exists():
        result["footprint_libraries"] = _parse_lib_table(fp_table, env)

    return result


def _parse_lib_table(path: Path, env: dict[str, Path]) -> list[LibraryEntry]:
    """Parse a sym-lib-table or fp-lib-table file."""
    doc = Document.load(str(path))
    entries: list[LibraryEntry] = []
    for lib_node in doc.root.find_all("lib"):
        name_node = lib_node.get("name")
        type_node = lib_node.get("type")
        uri_node = lib_node.get("uri")
        descr_node = lib_node.get("descr")

        name = name_node.first_value if name_node else ""
        lib_type = type_node.first_value if type_node else ""
        uri_raw = uri_node.first_value if uri_node else ""
        descr = descr_node.first_value if descr_node else ""

        resolved = str(_resolve_uri(uri_raw, env))
        entries.append(
            LibraryEntry(
                name=name or "",
                lib_type=lib_type or "",
                uri=resolved,
                description=descr or "",
            )
        )
    return entries


def list_symbols_in_library(lib_path: str | Path) -> list[SymbolInfo]:
    """List all symbols defined in a .kicad_sym file.

    Uses fast regex scanning instead of full S-expr parse since .kicad_sym
    files can be very large (100K+ lines).
    """
    path = Path(lib_path)
    if not path.exists():
        return []

    lib_name = path.stem  # e.g., "Device" from "Device.kicad_sym"

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    return _scan_symbols_fast(text, lib_name)


# Regex patterns for fast symbol scanning
_RE_TOP_SYMBOL = re.compile(r'^\t\(symbol\s+"([^"]+)"', re.MULTILINE)
_RE_PROPERTY = re.compile(r'\(property\s+"([^"]+)"\s+"([^"]*)"')
_RE_POWER = re.compile(r"\(power\)")
_RE_PIN = re.compile(r"\(pin\s+\w+\s+\w+")


def _scan_symbols_fast(text: str, lib_name: str) -> list[SymbolInfo]:
    """Scan a .kicad_sym file for top-level symbols using regex.

    Top-level symbols are at indent level 2 (two spaces before the paren).
    Sub-symbols (graphics/pins) are at deeper indentation.
    """
    symbols: list[SymbolInfo] = []

    # Split into top-level symbol blocks by finding their positions
    sym_starts: list[tuple[int, str]] = []
    for m in _RE_TOP_SYMBOL.finditer(text):
        sym_name = m.group(1)
        # Skip sub-symbols: they have _N_N suffix (e.g., "R_0_0", "R_1_1")
        parts = sym_name.rsplit("_", 2)
        if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
            continue
        sym_starts.append((m.start(), sym_name))

    # Extract each symbol block and scan properties
    for i, (start, sym_name) in enumerate(sym_starts):
        end = sym_starts[i + 1][0] if i + 1 < len(sym_starts) else len(text)
        block = text[start:end]

        is_power = _RE_POWER.search(block) is not None

        # Extract properties from block
        props: dict[str, str] = {}
        for pm in _RE_PROPERTY.finditer(block):
            props[pm.group(1)] = pm.group(2)

        pin_count = len(_RE_PIN.findall(block))

        symbols.append(
            SymbolInfo(
                name=sym_name,
                library=lib_name,
                reference=props.get("Reference", ""),
                value=props.get("Value", ""),
                description=props.get("Description", ""),
                keywords=props.get("ki_keywords", ""),
                footprint=props.get("Footprint", ""),
                datasheet=props.get("Datasheet", ""),
                pin_count=pin_count,
                is_power=is_power,
            )
        )
    return symbols


def list_footprints_in_library(lib_path: str | Path) -> list[FootprintInfo]:
    """List all footprints in a .pretty directory."""
    path = Path(lib_path)
    if not path.is_dir():
        return []

    lib_name = path.stem.replace(".pretty", "")
    footprints: list[FootprintInfo] = []

    for mod_file in sorted(path.glob("*.kicad_mod")):
        info = _parse_footprint_file(mod_file, lib_name)
        if info:
            footprints.append(info)

    return footprints


def get_footprint_details(mod_path: str | Path) -> FootprintInfo | None:
    """Get details of a single .kicad_mod footprint file."""
    path = Path(mod_path)
    if not path.exists():
        return None
    lib_name = path.parent.stem.replace(".pretty", "")
    return _parse_footprint_file(path, lib_name)


def _parse_footprint_file(path: Path, lib_name: str) -> FootprintInfo | None:
    """Parse a .kicad_mod file into FootprintInfo."""
    try:
        doc = Document.load(str(path))
    except Exception:
        return None

    root = doc.root
    fp_name = root.first_value or path.stem

    descr_node = root.get("descr")
    descr = descr_node.first_value if descr_node else ""

    tags_node = root.get("tags")
    tags = tags_node.first_value if tags_node else ""

    attr_node = root.get("attr")
    attr = attr_node.first_value if attr_node else ""

    pads = root.find_all("pad")
    pad_infos: list[dict[str, Any]] = []
    for pad in pads:
        pad_vals = pad.atom_values
        pad_info: dict[str, Any] = {"number": pad_vals[0] if pad_vals else ""}
        if len(pad_vals) > 1:
            pad_info["type"] = pad_vals[1]
        if len(pad_vals) > 2:
            pad_info["shape"] = pad_vals[2]
        pad_infos.append(pad_info)

    return FootprintInfo(
        name=fp_name,
        library=lib_name,
        description=descr or "",
        tags=tags or "",
        attribute=attr or "",
        pad_count=len(pads),
        pads=pad_infos,
    )


def search_symbols(
    query: str,
    libraries: list[LibraryEntry] | None = None,
    max_results: int = 50,
) -> list[SymbolInfo]:
    """Search for symbols across libraries by name, keyword, or description.

    Searches library name/description first to prioritize likely matches.
    """
    if libraries is None:
        tables = discover_lib_tables()
        libraries = tables.get("symbol_libraries", [])

    query_lower = query.lower()
    results: list[SymbolInfo] = []

    # Sort libraries: those whose name matches the query come first
    def _lib_priority(lib: LibraryEntry) -> int:
        if query_lower in lib.name.lower():
            return 0
        if query_lower in lib.description.lower():
            return 1
        return 2

    for lib in sorted(libraries, key=_lib_priority):
        lib_path = Path(lib.uri)
        if not lib_path.exists():
            continue

        symbols = list_symbols_in_library(lib_path)
        for sym in symbols:
            if _matches_query(query_lower, sym.name, sym.keywords, sym.description):
                results.append(sym)
                if len(results) >= max_results:
                    return results

    return results


def search_footprints(
    query: str,
    libraries: list[LibraryEntry] | None = None,
    max_results: int = 50,
) -> list[FootprintInfo]:
    """Search for footprints across libraries by name, tags, or description.

    Uses fast filename matching: only parses .kicad_mod files whose name
    matches the query, avoiding the cost of parsing thousands of files.
    """
    if libraries is None:
        tables = discover_lib_tables()
        libraries = tables.get("footprint_libraries", [])

    query_lower = query.lower()
    results: list[FootprintInfo] = []

    for lib in libraries:
        lib_path = Path(lib.uri)
        if not lib_path.is_dir():
            continue

        lib_name = lib_path.stem.replace(".pretty", "")

        # Fast path: match filenames first, only parse matching files
        for mod_file in sorted(lib_path.glob("*.kicad_mod")):
            if query_lower not in mod_file.stem.lower() and query_lower not in lib_name.lower():
                continue
            info = _parse_footprint_file(mod_file, lib_name)
            if info:
                results.append(info)
                if len(results) >= max_results:
                    return results

    return results


def _matches_query(query: str, *fields: str) -> bool:
    """Check if the query matches any of the fields (case-insensitive)."""
    return any(query in f.lower() for f in fields)
