"""Shared helper functions for session operations."""

from __future__ import annotations

from ..sexp import Document, SExp
from ..sexp.parser import parse as sexp_parse


def find_footprint(doc: Document, reference: str) -> SExp | None:
    """Find a footprint node by reference designator.

    Args:
        doc: The Document to search.
        reference: Reference designator (e.g., "R1", "U1").

    Returns:
        The footprint SExp node if found, None otherwise.

    Raises:
        ValueError: If reference is empty or invalid.
    """
    if not reference:
        raise ValueError("Reference designator cannot be empty")
    if len(reference) > 32:
        raise ValueError(f"Reference designator too long: {reference!r}")

    for fp_node in doc.root.find_all("footprint"):
        for prop in fp_node.find_all("property"):
            if prop.first_value == "Reference":
                vals = prop.atom_values
                if len(vals) > 1 and vals[1] == reference:
                    return fp_node
    return None


def find_footprint_by_uuid(doc: Document, uuid: str) -> SExp | None:
    """Find a footprint node by UUID.

    Args:
        doc: The Document to search.
        uuid: The UUID to search for.

    Returns:
        The footprint SExp node if found, None otherwise.

    Raises:
        ValueError: If uuid is empty or invalid.
    """
    if not uuid:
        raise ValueError("UUID cannot be empty")
    if len(uuid) > 36:
        raise ValueError(f"UUID too long: {uuid!r}")

    for fp_node in doc.root.find_all("footprint"):
        fp_uuid = fp_node.get("uuid")
        if fp_uuid and fp_uuid.first_value == uuid:
            return fp_node
    return None


def find_module_by_uuid(doc: Document, uuid: str) -> SExp | None:
    """Find a module (footprint instance) by UUID in older KiCad format.

    Args:
        doc: The Document to search.
        uuid: The UUID to search for.

    Returns:
        The module SExp node if found, None otherwise.

    Raises:
        ValueError: If uuid is empty or invalid.
    """
    if not uuid:
        raise ValueError("UUID cannot be empty")
    if len(uuid) > 36:
        raise ValueError(f"UUID too long: {uuid!r}")

    for mod_node in doc.root.find_all("module"):
        mod_uuid = mod_node.get("uuid")
        if mod_uuid and mod_uuid.first_value == uuid:
            return mod_node
    return None


def deep_copy_doc(doc: Document) -> Document:
    """Create a deep copy of a Document for working changes.

    Args:
        doc: The Document to copy.

    Returns:
        A new Document with a fresh copy of the S-expression tree.

    Raises:
        ValueError: If the raw text cannot be parsed.
    """
    if not doc._raw_text:
        raise ValueError("Cannot copy empty Document")
    try:
        new_root = sexp_parse(doc._raw_text)
    except ValueError as e:
        raise ValueError(f"Failed to copy document: {e}") from e
    return Document(path=doc.path, root=new_root, raw_text=doc._raw_text)
