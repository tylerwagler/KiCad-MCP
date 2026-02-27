"""Extract typed schema models from parsed S-expression trees.

Converts raw SExp nodes into structured dataclasses for board analysis.
"""

from __future__ import annotations

from ..sexp import Document, SExp
from .board import BoardSummary, Footprint, Layer, Net, Pad, Segment
from .common import BoundingBox, Position


def _float(val: str | None, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _int(val: str | None, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _extract_position(node: SExp | None) -> Position:
    """Extract Position from an (at x y [angle]) node."""
    if node is None:
        return Position(0, 0)
    vals = node.atom_values
    x = _float(vals[0]) if len(vals) > 0 else 0.0
    y = _float(vals[1]) if len(vals) > 1 else 0.0
    angle = _float(vals[2]) if len(vals) > 2 else 0.0
    return Position(x, y, angle)


def extract_nets(doc: Document) -> list[Net]:
    """Extract all nets from a board document."""
    nets: list[Net] = []
    for node in doc.root.find_all("net"):
        vals = node.atom_values
        if len(vals) >= 2:
            nets.append(Net(number=_int(vals[0]), name=vals[1]))
        elif len(vals) == 1:
            nets.append(Net(number=_int(vals[0]), name=""))
    return nets


def extract_layers(doc: Document) -> list[Layer]:
    """Extract all layers from a board document."""
    layers_node = doc.root.get("layers")
    if layers_node is None:
        return []
    layers: list[Layer] = []
    for child in layers_node.children:
        if not child.is_list:
            continue
        # Layer format: (number "name" type ["user_name"])
        # The number is the name of the node, rest are atom children
        vals = child.atom_values
        layer_num = _int(child.name)
        if len(vals) >= 2:
            name = vals[0]
            layer_type = vals[1]
            user_name = vals[2] if len(vals) > 2 else None
            layers.append(
                Layer(
                    number=layer_num,
                    name=name,
                    layer_type=layer_type,
                    user_name=user_name,
                )
            )
    return layers


def extract_pad(pad_node: SExp) -> Pad:
    """Extract a Pad from a (pad ...) S-expression node."""
    vals = pad_node.atom_values
    number = vals[0] if len(vals) > 0 else ""
    pad_type = vals[1] if len(vals) > 1 else ""
    shape = vals[2] if len(vals) > 2 else ""

    position = _extract_position(pad_node.get("at"))

    size_node = pad_node.get("size")
    size = (0.0, 0.0)
    if size_node:
        size_vals = size_node.atom_values
        size = (
            _float(size_vals[0]) if len(size_vals) > 0 else 0.0,
            _float(size_vals[1]) if len(size_vals) > 1 else 0.0,
        )

    layers_node = pad_node.get("layers")
    layers = layers_node.atom_values if layers_node else []

    net_node = pad_node.get("net")
    net_number = None
    net_name = None
    if net_node:
        net_vals = net_node.atom_values
        net_number = _int(net_vals[0]) if len(net_vals) > 0 else None
        net_name = net_vals[1] if len(net_vals) > 1 else None

    return Pad(
        number=number,
        pad_type=pad_type,
        shape=shape,
        position=position,
        size=size,
        layers=layers,
        net_number=net_number,
        net_name=net_name,
    )


def extract_footprints(doc: Document) -> list[Footprint]:
    """Extract all footprints from a board document."""
    footprints: list[Footprint] = []
    for fp_node in doc.root.find_all("footprint"):
        library = fp_node.first_value or ""

        # Extract properties: Reference, Value
        reference = ""
        value = ""
        description = ""
        for prop in fp_node.find_all("property"):
            prop_name = prop.first_value
            prop_vals = prop.atom_values
            prop_val = prop_vals[1] if len(prop_vals) > 1 else ""
            if prop_name == "Reference":
                reference = prop_val
            elif prop_name == "Value":
                value = prop_val
            elif prop_name == "Description":
                description = prop_val

        position = _extract_position(fp_node.get("at"))

        layer_node = fp_node.get("layer")
        layer = layer_node.first_value if layer_node else ""

        uuid_node = fp_node.get("uuid")
        uuid = uuid_node.first_value if uuid_node else ""

        # Extract pads
        pads = [extract_pad(p) for p in fp_node.find_all("pad")]

        footprints.append(
            Footprint(
                library=library,
                reference=reference,
                value=value,
                position=position,
                layer=layer or "",
                pads=pads,
                uuid=uuid or "",
                description=description,
            )
        )
    return footprints


def extract_segments(doc: Document) -> list[Segment]:
    """Extract all track segments from a board document."""
    segments: list[Segment] = []
    for seg_node in doc.root.find_all("segment"):
        start = _extract_position(seg_node.get("start"))
        end = _extract_position(seg_node.get("end"))

        width_node = seg_node.get("width")
        width = _float(width_node.first_value if width_node else None)

        layer_node = seg_node.get("layer")
        layer = layer_node.first_value if layer_node else ""

        net_node = seg_node.get("net")
        net_number = _int(net_node.first_value if net_node else None)

        segments.append(
            Segment(
                start=start,
                end=end,
                width=width,
                layer=layer or "",
                net_number=net_number,
            )
        )
    return segments


def extract_board_outline(doc: Document) -> BoundingBox | None:
    """Extract the board bounding box from Edge.Cuts graphics.

    Scans gr_line, gr_rect, gr_arc elements on Edge.Cuts to compute
    the overall board outline bounding box.
    """
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    found = False

    for node_name in ("gr_line", "gr_rect", "gr_arc", "gr_circle"):
        for node in doc.root.find_all(node_name):
            layer_node = node.get("layer")
            if layer_node and layer_node.first_value == "Edge.Cuts":
                found = True
                # Check start/end/center points
                for pt_name in ("start", "end", "center"):
                    pt = node.get(pt_name)
                    if pt:
                        vals = pt.atom_values
                        if len(vals) >= 2:
                            x, y = _float(vals[0]), _float(vals[1])
                            min_x = min(min_x, x)
                            min_y = min(min_y, y)
                            max_x = max(max_x, x)
                            max_y = max(max_y, y)

    if not found:
        return None

    return BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def extract_board_summary(doc: Document) -> BoardSummary:
    """Extract a complete board summary from a document."""
    nets = extract_nets(doc)
    layers = extract_layers(doc)
    footprints = extract_footprints(doc)
    segments = extract_segments(doc)
    bounding_box = extract_board_outline(doc)

    copper_layers = [lyr.name for lyr in layers if lyr.layer_type == "signal"]

    # Title
    title_block = doc.root.get("title_block")
    title = ""
    if title_block:
        title_node = title_block.get("title")
        title = title_node.first_value if title_node and title_node.first_value else ""

    # Version
    version_node = doc.root.get("version")
    version = version_node.first_value if version_node and version_node.first_value else ""

    # Generator
    gen_node = doc.root.get("generator")
    generator = gen_node.first_value if gen_node and gen_node.first_value else ""

    # Thickness
    general = doc.root.get("general")
    thickness = 1.6  # default
    if general:
        t_node = general.get("thickness")
        if t_node:
            thickness = _float(t_node.first_value, 1.6)

    return BoardSummary(
        title=title or "",
        version=version or "",
        generator=generator or "",
        thickness=thickness,
        layer_count=len(layers),
        copper_layers=copper_layers,
        net_count=len(nets),
        footprint_count=len(footprints),
        segment_count=len(segments),
        nets=nets,
        layers=layers,
        bounding_box=bounding_box,
    )
