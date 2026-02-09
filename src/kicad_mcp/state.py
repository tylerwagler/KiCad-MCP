"""Global board state for the MCP server.

Holds the currently loaded board document and extracted schema models.
This is a simple module-level state for now; the session model (Phase 5)
will wrap this with transactions and undo.
"""

from __future__ import annotations

from .schema import BoardSummary, Footprint
from .schema.extract import (
    extract_board_summary,
    extract_footprints,
)
from .sexp import Document

_current_doc: Document | None = None
_current_summary: BoardSummary | None = None
_current_footprints: list[Footprint] | None = None


def load_board(path: str) -> BoardSummary:
    """Load a board file and extract its summary."""
    global _current_doc, _current_summary, _current_footprints
    _current_doc = Document.load(path)
    _current_summary = extract_board_summary(_current_doc)
    _current_footprints = extract_footprints(_current_doc)
    return _current_summary


def get_document() -> Document:
    """Get the currently loaded document, or raise."""
    if _current_doc is None:
        raise RuntimeError("No board loaded. Use open_project first.")
    return _current_doc


def get_summary() -> BoardSummary:
    """Get the current board summary, or raise."""
    if _current_summary is None:
        raise RuntimeError("No board loaded. Use open_project first.")
    return _current_summary


def get_footprints() -> list[Footprint]:
    """Get the current footprint list, or raise."""
    if _current_footprints is None:
        raise RuntimeError("No board loaded. Use open_project first.")
    return _current_footprints


def is_loaded() -> bool:
    """Check if a board is currently loaded."""
    return _current_doc is not None


def get_board_path() -> str | None:
    """Get the path of the currently loaded board."""
    if _current_doc is None:
        return None
    return str(_current_doc.path)
