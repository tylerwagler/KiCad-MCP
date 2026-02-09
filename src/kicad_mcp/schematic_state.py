"""Global schematic state for the MCP server."""

from __future__ import annotations

from .schema.extract_schematic import extract_schematic_summary, extract_symbols
from .schema.schematic import SchematicSummary, SchSymbol
from .sexp import Document

_current_doc: Document | None = None
_current_summary: SchematicSummary | None = None
_current_symbols: list[SchSymbol] | None = None


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
