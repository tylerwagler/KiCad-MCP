"""Shared helper functions for session operations."""

from __future__ import annotations

from ..sexp import Document, SExp
from ..sexp.parser import parse as sexp_parse


def footprint_field(fp_node: SExp, field: str) -> str | None:
    """Read a footprint field (``Reference`` or ``Value``) in either format.

    KiCad 7+ stores these as ``(property "Reference" "R1" …)``. Footprints
    imported from KiCad 6 or older ``.kicad_mod`` files instead declare them
    with the legacy ``(fp_text reference "R1" …)`` syntax. Matching both keeps
    placement and net assignment from silently skipping legacy footprints.

    Args:
        fp_node: A ``footprint`` node.
        field: ``"Reference"`` or ``"Value"`` (case-insensitive).

    Returns:
        The field text, or None if absent.
    """
    for prop in fp_node.find_all("property"):
        if prop.first_value == field:
            vals = prop.atom_values
            if len(vals) > 1:
                return vals[1]
    # Legacy fp_text: the kind keyword is lowercase ("reference"/"value").
    legacy_kind = field.lower()
    for ft in fp_node.find_all("fp_text"):
        vals = ft.atom_values
        if len(vals) > 1 and vals[0] == legacy_kind:
            return vals[1]
    return None


def find_footprint(doc: Document, reference: str) -> SExp | None:
    """Find a footprint node by reference designator.

    Args:
        doc: The document to search.
        reference: The reference designator to find (e.g., 'R1').

    Returns:
        The footprint node if found, None otherwise.
    """
    for fp_node in doc.root.find_all("footprint"):
        if footprint_field(fp_node, "Reference") == reference:
            return fp_node
    return None


def find_footprint_by_uuid(doc: Document, uuid: str) -> SExp | None:
    """Find a footprint node by its UUID.

    Args:
        doc: The document to search.
        uuid: The UUID value to match.

    Returns:
        The footprint node if found, None otherwise.
    """
    for fp_node in doc.root.find_all("footprint"):
        uuid_node = fp_node.get("uuid")
        if uuid_node is not None and uuid_node.first_value == uuid:
            return fp_node
    return None


def deep_copy_doc(doc: Document) -> Document:
    """Create a deep copy of a Document for working changes.

    Args:
        doc: The document to copy.

    Returns:
        A new Document with the same content.
    """
    new_root = sexp_parse(doc._raw_text)
    return Document(path=doc.path, root=new_root, raw_text=doc._raw_text)
