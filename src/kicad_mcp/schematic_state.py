"""Global schematic state for the MCP server."""

from __future__ import annotations

from .schema.extract_schematic import extract_schematic_summary, extract_symbols
from .schema.hierarchy import Hierarchy, SheetTreeNode, build_hierarchy
from .schema.schematic import SchematicSummary, SchSymbol
from .sexp import Document

_current_doc: Document | None = None
_current_summary: SchematicSummary | None = None
_current_symbols: list[SchSymbol] | None = None

# Hierarchy (multi-sheet) state, independent of the single-file state above.
_hierarchy: Hierarchy | None = None
_current_sheet_path: str | None = None  # instance path of the active sheet


def load_schematic(path: str) -> SchematicSummary:
    """Load a schematic file and extract its summary."""
    global _current_doc, _current_summary, _current_symbols
    _current_doc = Document.load(path)
    _current_summary = extract_schematic_summary(_current_doc)
    _current_symbols = extract_symbols(_current_doc)
    return _current_summary


def get_document() -> Document:
    if _current_doc is None:
        raise RuntimeError("No schematic loaded. Use open_schematic first.")
    return _current_doc


def get_summary() -> SchematicSummary:
    if _current_summary is None:
        raise RuntimeError("No schematic loaded. Use open_schematic first.")
    return _current_summary


def get_symbols() -> list[SchSymbol]:
    if _current_symbols is None:
        raise RuntimeError("No schematic loaded. Use open_schematic first.")
    return _current_symbols


def refresh() -> None:
    """Re-extract summary and symbols from the in-memory document."""
    global _current_summary, _current_symbols
    if _current_doc is None:
        raise RuntimeError("No schematic loaded. Use open_schematic first.")
    _current_summary = extract_schematic_summary(_current_doc)
    _current_symbols = extract_symbols(_current_doc)


def is_loaded() -> bool:
    return _current_doc is not None


# ── Hierarchy (multi-sheet) state ───────────────────────────────────


def load_hierarchy(root_path: str) -> Hierarchy:
    """Resolve and load a full sheet hierarchy from a root .kicad_sch.

    Also loads the root file into the single-file state so existing tools keep
    working on the root sheet, and sets the active sheet to the root.
    """
    global _hierarchy, _current_sheet_path
    _hierarchy = build_hierarchy(root_path)
    _current_sheet_path = _hierarchy.root.instance_path
    # Keep the single-file API pointed at the root document.
    global _current_doc, _current_summary, _current_symbols
    _current_doc = _hierarchy.docs[_hierarchy.root.file]
    _current_summary = extract_schematic_summary(_current_doc)
    _current_symbols = extract_symbols(_current_doc)
    return _hierarchy


def hierarchy_loaded() -> bool:
    return _hierarchy is not None


def get_hierarchy() -> Hierarchy:
    if _hierarchy is None:
        raise RuntimeError("No hierarchy loaded. Use open_hierarchy first.")
    return _hierarchy


def set_current_sheet(instance_path: str) -> SheetTreeNode:
    """Set the active sheet placement (for sheet-scoped edits)."""
    global _current_sheet_path
    node = get_hierarchy().find_node(instance_path)
    if node is None:
        raise RuntimeError(f"No sheet placement with path {instance_path!r}")
    _current_sheet_path = instance_path
    return node


def get_current_node() -> SheetTreeNode:
    """Return the active sheet placement node (defaults to the root)."""
    h = get_hierarchy()
    if _current_sheet_path is None:
        return h.root
    node = h.find_node(_current_sheet_path)
    return node if node is not None else h.root


def get_current_hierarchy_doc() -> Document:
    """Return the parsed Document for the active sheet's file."""
    node = get_current_node()
    return get_hierarchy().docs[node.file]


def save_hierarchy() -> list[str]:
    """Write every loaded sheet document back to disk. Returns saved paths."""
    h = get_hierarchy()
    saved: list[str] = []
    for path, doc in h.docs.items():
        doc.save(path)
        saved.append(path)
    return saved
