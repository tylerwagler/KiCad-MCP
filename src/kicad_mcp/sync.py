"""Schematic-PCB synchronization logic.

Provides cross-reference validation, forward annotation (sch→pcb),
and back annotation (pcb→sch) using pure S-expr manipulation.
"""

from __future__ import annotations

from typing import Any

from .schema.board import Footprint
from .schema.schematic import SchSymbol
from .sexp import Document
from .sexp.parser import SExp


def _make_quoted(val: str) -> SExp:
    """Create a quoted-string atom SExp."""
    return SExp(value=val, _original_str=f'"{val}"')


def _update_property(node: SExp, prop_name: str, new_value: str) -> bool:
    """Update a property value in an S-expr node.

    Finds ``(property "<prop_name>" "<old_value>" ...)`` among children
    and replaces the second atom (the value) with *new_value*.

    Returns True if the property was found and updated.
    """
    for prop in node.find_all("property"):
        if prop.first_value == prop_name:
            atom_idx = 0
            for i, child in enumerate(prop.children):
                if child.is_atom:
                    atom_idx += 1
                    if atom_idx == 2:
                        prop.children[i] = _make_quoted(new_value)
                        return True
    return False


def cross_reference(
    sch_symbols: list[SchSymbol],
    board_footprints: list[Footprint],
) -> dict[str, Any]:
    """Compare schematic symbols against board footprints.

    Only considers schematic symbols with ``on_board=True``.

    Returns a report dict with keys:
        missing_on_board, missing_in_schematic, value_mismatches,
        footprint_mismatches, matched, summary.
    """
    sch_by_ref: dict[str, SchSymbol] = {}
    for sym in sch_symbols:
        if sym.on_board:
            sch_by_ref[sym.reference] = sym

    board_by_ref: dict[str, Footprint] = {fp.reference: fp for fp in board_footprints}

    sch_refs = set(sch_by_ref.keys())
    board_refs = set(board_by_ref.keys())

    missing_on_board = sorted(sch_refs - board_refs)
    missing_in_schematic = sorted(board_refs - sch_refs)

    value_mismatches: list[dict[str, str]] = []
    footprint_mismatches: list[dict[str, str]] = []
    matched = 0

    for ref in sorted(sch_refs & board_refs):
        sym = sch_by_ref[ref]
        fp = board_by_ref[ref]

        value_ok = sym.value == fp.value
        fp_ok = True

        if not value_ok:
            value_mismatches.append(
                {
                    "reference": ref,
                    "schematic_value": sym.value,
                    "board_value": fp.value,
                }
            )

        sch_footprint = sym.properties.get("Footprint", "")
        if sch_footprint and sch_footprint != fp.library:
            fp_ok = False
            footprint_mismatches.append(
                {
                    "reference": ref,
                    "schematic_footprint": sch_footprint,
                    "board_footprint": fp.library,
                }
            )

        if value_ok and fp_ok:
            matched += 1

    total = len(sch_refs | board_refs)
    return {
        "missing_on_board": missing_on_board,
        "missing_in_schematic": missing_in_schematic,
        "value_mismatches": value_mismatches,
        "footprint_mismatches": footprint_mismatches,
        "matched": matched,
        "summary": (
            f"{matched}/{total} components in sync, "
            f"{len(missing_on_board)} missing on board, "
            f"{len(missing_in_schematic)} extra on board, "
            f"{len(value_mismatches)} value mismatches, "
            f"{len(footprint_mismatches)} footprint mismatches"
        ),
    }


def forward_annotate(
    sch_symbols: list[SchSymbol],
    board_doc: Document,
) -> dict[str, Any]:
    """Push schematic values onto the board (sch→pcb).

    For each schematic symbol with ``on_board=True``, finds the matching
    footprint node in the board S-expr tree by reference and updates its
    Value property to match the schematic.

    Returns ``{updated: [...], not_on_board: [...], errors: [...]}``.
    """
    updated: list[str] = []
    not_on_board: list[str] = []
    errors: list[str] = []

    # Index board footprint nodes by reference
    fp_nodes: dict[str, SExp] = {}
    for fp_node in board_doc.root.find_all("footprint"):
        for prop in fp_node.find_all("property"):
            if prop.first_value == "Reference":
                vals = prop.atom_values
                if len(vals) > 1:
                    fp_nodes[vals[1]] = fp_node
                    break

    for sym in sch_symbols:
        if not sym.on_board:
            continue

        fp_node = fp_nodes.get(sym.reference)  # type: ignore[assignment]
        if fp_node is None:
            not_on_board.append(sym.reference)
            continue

        # Check if value differs
        current_value = None
        for prop in fp_node.find_all("property"):
            if prop.first_value == "Value":
                vals = prop.atom_values
                if len(vals) > 1:
                    current_value = vals[1]
                break

        if current_value == sym.value:
            continue  # Already in sync

        if _update_property(fp_node, "Value", sym.value):
            updated.append(sym.reference)
        else:
            errors.append(f"{sym.reference}: failed to update Value property")

    return {
        "updated": updated,
        "not_on_board": not_on_board,
        "errors": errors,
    }


def back_annotate(
    board_footprints: list[Footprint],
    sch_doc: Document,
) -> dict[str, Any]:
    """Push board values back to the schematic (pcb→sch).

    For each board footprint, finds the matching schematic symbol node
    by reference and updates its Value property to match the board.

    Returns ``{updated: [...], not_in_schematic: [...], errors: [...]}``.
    """
    updated: list[str] = []
    not_in_schematic: list[str] = []
    errors: list[str] = []

    # Index schematic symbol nodes by reference
    sym_nodes: dict[str, SExp] = {}
    for sym_node in sch_doc.root.find_all("symbol"):
        lib_id_node = sym_node.get("lib_id")
        if lib_id_node is None:
            continue  # Skip lib_symbols definitions
        for prop in sym_node.find_all("property"):
            if prop.first_value == "Reference":
                vals = prop.atom_values
                if len(vals) > 1:
                    sym_nodes[vals[1]] = sym_node
                    break

    for fp in board_footprints:
        sym_node = sym_nodes.get(fp.reference)  # type: ignore[assignment]
        if sym_node is None:
            not_in_schematic.append(fp.reference)
            continue

        # Check if value differs
        current_value = None
        for prop in sym_node.find_all("property"):
            if prop.first_value == "Value":
                vals = prop.atom_values
                if len(vals) > 1:
                    current_value = vals[1]
                break

        if current_value == fp.value:
            continue  # Already in sync

        if _update_property(sym_node, "Value", fp.value):
            updated.append(fp.reference)
        else:
            errors.append(f"{fp.reference}: failed to update Value property")

    return {
        "updated": updated,
        "not_in_schematic": not_in_schematic,
        "errors": errors,
    }
