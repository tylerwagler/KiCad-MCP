"""Shared helper functions for session operations."""

from __future__ import annotations

from ..sexp import Document, SExp
from ..sexp.parser import parse as sexp_parse


def find_footprint(doc: Document, reference: str) -> SExp | None:
    """Find a footprint node by reference designator."""
    for fp_node in doc.root.find_all("footprint"):
        for prop in fp_node.find_all("property"):
            if prop.first_value == "Reference":
                vals = prop.atom_values
                if len(vals) > 1 and vals[1] == reference:
                    return fp_node
    return None


def find_footprint_by_uuid(doc: Document, uuid: str) -> SExp | None:
    """Find a footprint node by UUID."""
    for fp_node in doc.root.find_all("footprint"):
        fp_uuid = fp_node.get("uuid")
        if fp_uuid and fp_uuid.first_value == uuid:
            return fp_node
    return None


def find_module_by_uuid(doc: Document, uuid: str) -> SExp | None:
    """Find a module (footprint instance) by UUID in older KiCad format."""
    for mod_node in doc.root.find_all("module"):
        mod_uuid = mod_node.get("uuid")
        if mod_uuid and mod_uuid.first_value == uuid:
            return mod_node
    return None


def deep_copy_doc(doc: Document) -> Document:
    """Create a deep copy of a Document for working changes."""
    new_root = sexp_parse(doc._raw_text)
    return Document(path=doc.path, root=new_root, raw_text=doc._raw_text)
