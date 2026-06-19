"""Pure-Python cross-sheet connectivity analysis for a schematic hierarchy.

Full pin-level netlisting (which needs wire geometry) is delegated to
``kicad-cli sch export netlist``. This module provides the install-free,
structural view of how sheets connect, which is what hierarchy adds over a
flat design:

- **Global nets** — global labels and power symbols tie nets across every sheet
  that uses the name.
- **Hierarchical ports** — a parent's sheet pin connects to the same-named
  hierarchical label in the child placement. Name/shape mismatches between the
  two sides are surfaced as ERC-style findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..sexp import Document
from .extract_schematic import extract_hierarchical_labels, extract_symbols
from .hierarchy import Hierarchy, SheetTreeNode


@dataclass
class GlobalNet:
    """A net that spans sheets by name (global label or power symbol)."""

    name: str
    kind: str  # "global_label" | "power"
    sheets: list[str] = field(default_factory=list)  # placement instance paths

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "sheets": self.sheets,
            "sheet_count": len(self.sheets),
        }


@dataclass
class HierPort:
    """A parent sheet-pin / child hierarchical-label crossing at one placement."""

    name: str
    parent_path: str
    child_path: str
    status: str  # "matched" | "missing_child_label" | "missing_sheet_pin"
    parent_shape: str = ""
    child_shape: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parent_path": self.parent_path,
            "child_path": self.child_path,
            "status": self.status,
            "parent_shape": self.parent_shape,
            "child_shape": self.child_shape,
        }


def _global_label_names(doc: Document) -> list[str]:
    return [n.first_value or "" for n in doc.root.find_all("global_label")]


def _power_net_names(doc: Document) -> list[str]:
    """Power-symbol net names (lib_id ``power:*``); the Value is the net name."""
    names: list[str] = []
    for sym in extract_symbols(doc):
        if sym.lib_id.startswith("power:") and sym.value:
            names.append(sym.value)
    return names


def _sheet_pins(parent_doc: Document, sheet_uuid: str) -> list[tuple[str, str]]:
    """(name, shape) for the pins of the (sheet) block with ``sheet_uuid``."""
    for sheet_node in parent_doc.root.find_all("sheet"):
        uuid_node = sheet_node.get("uuid")
        if uuid_node and uuid_node.first_value == sheet_uuid:
            out: list[tuple[str, str]] = []
            for pin in sheet_node.find_all("pin"):
                vals = pin.atom_values
                out.append((vals[0] if vals else "", vals[1] if len(vals) > 1 else ""))
            return out
    return []


def analyze_cross_sheet(h: Hierarchy) -> dict[str, Any]:
    """Analyse cross-sheet connectivity for a resolved hierarchy."""
    global_index: dict[str, GlobalNet] = {}

    def _add_global(name: str, kind: str, path: str) -> None:
        if not name:
            return
        net = global_index.get(name)
        if net is None:
            net = GlobalNet(name=name, kind=kind)
            global_index[name] = net
        if path not in net.sheets:
            net.sheets.append(path)

    ports: list[HierPort] = []

    def _visit(node: SheetTreeNode, parent: SheetTreeNode | None) -> None:
        doc = h.docs.get(node.file)
        if doc is not None:
            for gl in _global_label_names(doc):
                _add_global(gl, "global_label", node.instance_path)
            for pw in _power_net_names(doc):
                _add_global(pw, "power", node.instance_path)

        if parent is not None:
            parent_doc = h.docs.get(parent.file)
            child_doc = h.docs.get(node.file)
            pins = _sheet_pins(parent_doc, node.sheet_uuid) if parent_doc else []
            child_labels = (
                {hl.name: hl.shape for hl in extract_hierarchical_labels(child_doc)}
                if child_doc
                else {}
            )
            seen: set[str] = set()
            for pname, pshape in pins:
                seen.add(pname)
                status = "matched" if pname in child_labels else "missing_child_label"
                ports.append(
                    HierPort(
                        name=pname,
                        parent_path=parent.instance_path,
                        child_path=node.instance_path,
                        status=status,
                        parent_shape=pshape,
                        child_shape=child_labels.get(pname, ""),
                    )
                )
            for lname, lshape in child_labels.items():
                if lname not in seen:
                    ports.append(
                        HierPort(
                            name=lname,
                            parent_path=parent.instance_path,
                            child_path=node.instance_path,
                            status="missing_sheet_pin",
                            parent_shape="",
                            child_shape=lshape,
                        )
                    )

        for child in node.children:
            if not child.is_cycle and not child.missing:
                _visit(child, node)

    _visit(h.root, None)

    global_nets = [g.to_dict() for g in global_index.values()]
    mismatches = [p.to_dict() for p in ports if p.status != "matched"]
    return {
        "global_nets": sorted(global_nets, key=lambda g: g["name"]),
        "global_net_count": len(global_nets),
        "cross_sheet_global_nets": [g for g in global_nets if g["sheet_count"] > 1],
        "hierarchical_ports": [p.to_dict() for p in ports],
        "port_mismatches": mismatches,
    }
