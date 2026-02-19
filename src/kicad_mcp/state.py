"""Global board state for the MCP server.

Holds the currently loaded board document and extracted schema models.
Thread-safe: all reads and writes go through a module-level lock.
"""

from __future__ import annotations

import threading

from .schema import BoardSummary, Footprint
from .schema.extract import (
    extract_board_summary,
    extract_footprints,
)
from .sexp import Document

_lock = threading.Lock()
_current_doc: Document | None = None
_current_summary: BoardSummary | None = None
_current_footprints: list[Footprint] | None = None


def load_board(path: str) -> BoardSummary:
    """Load a board file and extract its summary."""
    global _current_doc, _current_summary, _current_footprints
    # Do I/O outside the lock
    doc = Document.load(path)
    summary = extract_board_summary(doc)
    footprints = extract_footprints(doc)
    # Swap all three atomically under the lock
    with _lock:
        _current_doc = doc
        _current_summary = summary
        _current_footprints = footprints
    return summary


def get_document() -> Document:
    """Get the currently loaded document, or raise."""
    with _lock:
        if _current_doc is None:
            raise RuntimeError("No board loaded. Use open_project first.")
        return _current_doc


def get_summary() -> BoardSummary:
    """Get the current board summary, or raise."""
    with _lock:
        if _current_summary is None:
            raise RuntimeError("No board loaded. Use open_project first.")
        return _current_summary


def get_footprints() -> list[Footprint]:
    """Get the current footprint list, or raise."""
    with _lock:
        if _current_footprints is None:
            raise RuntimeError("No board loaded. Use open_project first.")
        return _current_footprints


def is_loaded() -> bool:
    """Check if a board is currently loaded."""
    with _lock:
        return _current_doc is not None


def get_board_path() -> str | None:
    """Get the path of the currently loaded board."""
    with _lock:
        if _current_doc is None:
            return None
        return str(_current_doc.path)
