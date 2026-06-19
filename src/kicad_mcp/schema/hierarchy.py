"""Resolve a KiCad schematic sheet hierarchy from a root .kicad_sch file.

KiCad represents a hierarchical schematic as a tree of ``.kicad_sch`` files. A
parent holds ``(sheet ...)`` blocks, each pointing at a child via the
``Sheetfile`` property and carrying its own ``(uuid)``. The hierarchical
*instance path* of everything inside a sheet is the chain of those UUIDs:

    root           -> /<root_uuid>
    a sub-sheet    -> /<root_uuid>/<sheet_uuid>
    nested deeper  -> /<root_uuid>/<sheet_uuid>/<sheet_uuid>/...

The same child file may be instantiated multiple times (sheet reuse); each
placement is a distinct path, and a symbol carries one ``(instances (path ...))``
entry per placement with its own reference designator. This module builds the
tree, resolving reuse, missing files, and cycles, and flattens it into the full
set of component instances with their correct per-path references.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..sexp import Document
from .extract_schematic import extract_sheets, extract_symbols


@dataclass
class SheetTreeNode:
    """One node in the resolved sheet hierarchy (a sheet *placement*)."""

    name: str  # sheet name (file stem for the root)
    file: str  # resolved absolute path to the .kicad_sch file
    sheet_uuid: str  # the (sheet) block's uuid; "" for the root
    instance_path: str  # full UUID path to this placement's contents
    page: str  # page number for this placement
    children: list[SheetTreeNode] = field(default_factory=list)
    is_cycle: bool = False  # file repeats an ancestor — recursion stopped here
    missing: bool = False  # Sheetfile could not be resolved on disk

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file": self.file,
            "sheet_uuid": self.sheet_uuid,
            "instance_path": self.instance_path,
            "page": self.page,
            "is_cycle": self.is_cycle,
            "missing": self.missing,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class ComponentInstance:
    """A single placed-and-annotated component, resolved within one sheet path."""

    reference: str
    value: str
    lib_id: str
    unit: int
    symbol_uuid: str
    sheet_path: str  # instance_path of the containing sheet node
    sheet_name: str
    file: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "value": self.value,
            "lib_id": self.lib_id,
            "unit": self.unit,
            "symbol_uuid": self.symbol_uuid,
            "sheet_path": self.sheet_path,
            "sheet_name": self.sheet_name,
            "file": self.file,
        }


class Hierarchy:
    """A resolved sheet hierarchy: the tree plus every sheet's parsed document."""

    def __init__(self, root: SheetTreeNode, docs: dict[str, Document]) -> None:
        self.root = root
        self.docs = docs  # resolved file path -> Document (one per unique file)

    def iter_nodes(self) -> Iterator[SheetTreeNode]:
        """Depth-first walk over every sheet placement in the hierarchy."""

        def _walk(node: SheetTreeNode) -> Iterator[SheetTreeNode]:
            yield node
            for child in node.children:
                yield from _walk(child)

        yield from _walk(self.root)

    def find_node(self, instance_path: str) -> SheetTreeNode | None:
        """Find the sheet placement with the given instance path."""
        for node in self.iter_nodes():
            if node.instance_path == instance_path:
                return node
        return None

    def enumerate_components(self) -> list[ComponentInstance]:
        """Flatten the hierarchy to every component instance with its true ref.

        For each sheet placement, the reference comes from the symbol's
        ``(instances)`` entry whose path matches that placement — so a reused
        sheet yields distinct references (e.g. R1 in one copy, R2 in another).
        """
        out: list[ComponentInstance] = []
        symbols_by_file: dict[str, list[Any]] = {}
        for node in self.iter_nodes():
            if node.is_cycle or node.missing:
                continue
            doc = self.docs.get(node.file)
            if doc is None:
                continue
            if node.file not in symbols_by_file:
                symbols_by_file[node.file] = extract_symbols(doc)
            for sym in symbols_by_file[node.file]:
                inst = next((i for i in sym.instances if i.path == node.instance_path), None)
                reference = inst.reference if inst else sym.reference
                unit = inst.unit if inst else sym.unit
                out.append(
                    ComponentInstance(
                        reference=reference,
                        value=sym.value,
                        lib_id=sym.lib_id,
                        unit=unit,
                        symbol_uuid=sym.uuid,
                        sheet_path=node.instance_path,
                        sheet_name=node.name,
                        file=node.file,
                    )
                )
        return out


def _root_uuid(doc: Document) -> str:
    node = doc.root.get("uuid")
    return node.first_value or "" if node else ""


def build_hierarchy(
    root_path: str,
    _loader: Callable[[str], Document] = Document.load,
) -> Hierarchy:
    """Build the resolved sheet hierarchy starting from ``root_path``.

    ``_loader`` is injectable for testing. Files are parsed once and shared
    across reused placements; missing Sheetfiles and reference cycles are
    flagged rather than raised.
    """
    docs: dict[str, Document] = {}

    def _load(path: str) -> Document:
        if path not in docs:
            docs[path] = _loader(path)
        return docs[path]

    root_abs = str(Path(root_path).resolve())
    root_doc = _load(root_abs)
    root_node = SheetTreeNode(
        name=Path(root_abs).stem,
        file=root_abs,
        sheet_uuid="",
        instance_path="/" + _root_uuid(root_doc),
        page="1",
    )

    def _expand(node: SheetTreeNode, ancestors: frozenset[str]) -> None:
        doc = docs[node.file]
        parent_dir = Path(node.file).parent
        for sheet in extract_sheets(doc):
            child_path = (parent_dir / sheet.file).resolve()
            child_abs = str(child_path)
            child = SheetTreeNode(
                name=sheet.name or sheet.file,
                file=child_abs,
                sheet_uuid=sheet.uuid,
                instance_path=f"{node.instance_path}/{sheet.uuid}",
                page=sheet.page,
            )
            node.children.append(child)
            if not child_path.exists():
                child.missing = True
                continue
            if child_abs in ancestors:
                child.is_cycle = True  # would recurse forever — stop
                continue
            _load(child_abs)
            _expand(child, ancestors | {child_abs})

    _expand(root_node, frozenset({root_abs}))
    return Hierarchy(root_node, docs)
