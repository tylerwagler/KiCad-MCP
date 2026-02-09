"""Extract typed schema models from parsed schematic S-expression trees."""

from __future__ import annotations

from ..sexp import Document, SExp
from .common import Position
from .schematic import Label, PowerPort, SchematicSummary, SchPin, SchSymbol, Wire


def _float(val: str | None, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _extract_position(node: SExp | None) -> Position:
    if node is None:
        return Position(0, 0)
    vals = node.atom_values
    x = _float(vals[0]) if len(vals) > 0 else 0.0
    y = _float(vals[1]) if len(vals) > 1 else 0.0
    angle = _float(vals[2]) if len(vals) > 2 else 0.0
    return Position(x, y, angle)


def _bool_val(node: SExp | None, default: bool = True) -> bool:
    if node is None:
        return default
    val = node.first_value
    if val == "no":
        return False
    if val == "yes":
        return True
    return default


def extract_symbols(doc: Document) -> list[SchSymbol]:
    """Extract all placed symbol instances from a schematic."""
    symbols: list[SchSymbol] = []
    for sym_node in doc.root.find_all("symbol"):
        lib_id_node = sym_node.get("lib_id")
        if lib_id_node is None:
            continue  # Skip lib_symbols definitions

        lib_id = lib_id_node.first_value or ""
        position = _extract_position(sym_node.get("at"))

        unit_node = sym_node.get("unit")
        unit = int(unit_node.first_value) if unit_node and unit_node.first_value else 1

        uuid_node = sym_node.get("uuid")
        sym_uuid = uuid_node.first_value if uuid_node else ""

        in_bom = _bool_val(sym_node.get("in_bom"))
        on_board = _bool_val(sym_node.get("on_board"))

        # Extract properties
        reference = ""
        value = ""
        properties: dict[str, str] = {}
        for prop in sym_node.find_all("property"):
            prop_name = prop.first_value
            prop_vals = prop.atom_values
            prop_val = prop_vals[1] if len(prop_vals) > 1 else ""
            if prop_name:
                properties[prop_name] = prop_val
                if prop_name == "Reference":
                    reference = prop_val
                elif prop_name == "Value":
                    value = prop_val

        # Extract pins
        pins: list[SchPin] = []
        for pin_node in sym_node.find_all("pin"):
            pin_num = pin_node.first_value or ""
            pin_uuid_node = pin_node.get("uuid")
            pin_uuid = pin_uuid_node.first_value if pin_uuid_node else ""
            pins.append(SchPin(number=pin_num, uuid=pin_uuid))

        symbols.append(
            SchSymbol(
                lib_id=lib_id,
                reference=reference,
                value=value,
                position=position,
                unit=unit,
                uuid=sym_uuid or "",
                in_bom=in_bom,
                on_board=on_board,
                pins=pins,
                properties=properties,
            )
        )
    return symbols


def extract_wires(doc: Document) -> list[Wire]:
    """Extract all wires from a schematic."""
    wires: list[Wire] = []
    for wire_node in doc.root.find_all("wire"):
        pts_node = wire_node.get("pts")
        if pts_node is None:
            continue
        xy_nodes = pts_node.find_all("xy")
        if len(xy_nodes) >= 2:
            start_vals = xy_nodes[0].atom_values
            end_vals = xy_nodes[1].atom_values
            start = Position(
                _float(start_vals[0]) if start_vals else 0,
                _float(start_vals[1]) if len(start_vals) > 1 else 0,
            )
            end = Position(
                _float(end_vals[0]) if end_vals else 0,
                _float(end_vals[1]) if len(end_vals) > 1 else 0,
            )
            uuid_node = wire_node.get("uuid")
            wire_uuid = uuid_node.first_value if uuid_node else ""
            wires.append(Wire(start=start, end=end, uuid=wire_uuid))
    return wires


def extract_labels(doc: Document) -> list[Label]:
    """Extract all net labels from a schematic."""
    labels: list[Label] = []
    for label_node in doc.root.find_all("label"):
        name = label_node.first_value or ""
        position = _extract_position(label_node.get("at"))
        uuid_node = label_node.get("uuid")
        label_uuid = uuid_node.first_value if uuid_node else ""
        labels.append(Label(name=name, position=position, uuid=label_uuid))
    # Also check global_label
    for gl_node in doc.root.find_all("global_label"):
        name = gl_node.first_value or ""
        position = _extract_position(gl_node.get("at"))
        uuid_node = gl_node.get("uuid")
        gl_uuid = uuid_node.first_value if uuid_node else ""
        labels.append(Label(name=name, position=position, uuid=gl_uuid))
    return labels


def extract_power_ports(doc: Document) -> list[PowerPort]:
    """Extract all power port symbols from a schematic."""
    ports: list[PowerPort] = []
    for pp_node in doc.root.find_all("power_port"):
        name = pp_node.first_value or ""
        position = _extract_position(pp_node.get("at"))
        uuid_node = pp_node.get("uuid")
        pp_uuid = uuid_node.first_value if uuid_node else ""
        ports.append(PowerPort(name=name, position=position, uuid=pp_uuid))
    return ports


def extract_schematic_summary(doc: Document) -> SchematicSummary:
    """Extract a complete schematic summary."""
    version_node = doc.root.get("version")
    version = version_node.first_value if version_node else ""

    gen_node = doc.root.get("generator")
    generator = gen_node.first_value if gen_node else ""

    uuid_node = doc.root.get("uuid")
    sch_uuid = uuid_node.first_value if uuid_node else ""

    paper_node = doc.root.get("paper")
    paper = paper_node.first_value if paper_node else ""

    lib_symbols_node = doc.root.get("lib_symbols")
    lib_symbol_count = 0
    if lib_symbols_node:
        lib_symbol_count = len(lib_symbols_node.find_all("symbol"))

    symbols = extract_symbols(doc)
    wires = extract_wires(doc)
    labels = extract_labels(doc)
    power_ports = extract_power_ports(doc)

    return SchematicSummary(
        version=version or "",
        generator=generator or "",
        uuid=sch_uuid or "",
        paper=paper or "",
        symbol_count=len(symbols),
        wire_count=len(wires),
        label_count=len(labels),
        power_port_count=len(power_ports),
        lib_symbol_count=lib_symbol_count,
        symbols=symbols,
        wires=wires,
        labels=labels,
        power_ports=power_ports,
    )
