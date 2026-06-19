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
    """Load a single schematic file and extract its summary.

    Clears any previously loaded hierarchy so single-file edits don't pick up a
    stale multi-sheet context.
    """
    global _current_doc, _current_summary, _current_symbols
    global _hierarchy, _current_sheet_path
    _hierarchy = None
    _current_sheet_path = None
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
    """Set the active sheet placement and repoint the single-file API at it.

    Repointing ``_current_doc`` means the existing edit tools (add_symbol,
    add_wire, add_label, …) operate on the selected sheet's document.
    """
    global _current_sheet_path, _current_doc, _current_summary, _current_symbols
    node = get_hierarchy().find_node(instance_path)
    if node is None:
        raise RuntimeError(f"No sheet placement with path {instance_path!r}")
    if node.is_cycle or node.missing:
        raise RuntimeError(f"Sheet placement {instance_path!r} is not loadable")
    _current_sheet_path = instance_path
    _current_doc = get_hierarchy().docs[node.file]
    _current_summary = extract_schematic_summary(_current_doc)
    _current_symbols = extract_symbols(_current_doc)
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


def register_child_sheet(
    parent_path: str, sheet_uuid: str, child_file: str, name: str, page: str
) -> SheetTreeNode:
    """Add a newly created sub-sheet to the in-memory hierarchy tree.

    Keeps the tree consistent after add_sheet without reloading from disk
    (which would discard unsaved parent edits). The child file is parsed and
    cached so subsequent operations resolve it.
    """
    h = get_hierarchy()
    parent = h.find_node(parent_path)
    if parent is None:
        raise RuntimeError(f"No sheet placement with path {parent_path!r}")
    if child_file not in h.docs:
        h.docs[child_file] = Document.load(child_file)
    child = SheetTreeNode(
        name=name,
        file=child_file,
        sheet_uuid=sheet_uuid,
        instance_path=f"{parent.instance_path}/{sheet_uuid}",
        page=page,
    )
    parent.children.append(child)
    return child


def unregister_child_sheet(sheet_uuid: str) -> None:
    """Remove sub-sheet placements with the given sheet uuid from the tree."""
    h = get_hierarchy()
    for node in h.iter_nodes():
        node.children = [c for c in node.children if c.sheet_uuid != sheet_uuid]


def save_hierarchy() -> list[str]:
    """Write every loaded sheet document back to disk. Returns saved paths."""
    h = get_hierarchy()
    saved: list[str] = []
    for path, doc in h.docs.items():
        doc.save(path)
        saved.append(path)
    return saved
