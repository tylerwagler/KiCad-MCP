"""Session and transaction model for safe board mutations.

Provides a query-before-commit pattern:
  start_session → query_move (preview) → apply_move → undo → commit/rollback

The LLM can preview changes before writing to disk, and undo individual
operations or rollback the entire session.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..sexp import Document, SExp
from ..sexp.parser import parse as sexp_parse

# Layer flip mapping for component flipping
_LAYER_FLIP: dict[str, str] = {
    "F.Cu": "B.Cu",
    "B.Cu": "F.Cu",
    "F.SilkS": "B.SilkS",
    "B.SilkS": "F.SilkS",
    "F.Fab": "B.Fab",
    "B.Fab": "F.Fab",
    "F.CrtYd": "B.CrtYd",
    "B.CrtYd": "F.CrtYd",
    "F.Mask": "B.Mask",
    "B.Mask": "F.Mask",
    "F.Paste": "B.Paste",
    "B.Paste": "F.Paste",
    "F.Adhes": "B.Adhes",
    "B.Adhes": "F.Adhes",
}


class SessionState(Enum):
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ChangeRecord:
    """A single recorded change in a session."""

    change_id: str
    operation: str  # e.g., "move_component", "delete_component", "place_component"
    description: str
    target: str  # e.g., reference designator or node path
    before_snapshot: str  # Serialized S-expression of the affected node before change
    after_snapshot: str  # Serialized S-expression after change
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "operation": self.operation,
            "description": self.description,
            "target": self.target,
            "applied": self.applied,
        }


@dataclass
class Session:
    """A mutation session with tracked changes and undo capability."""

    session_id: str
    board_path: str
    state: SessionState = SessionState.ACTIVE
    changes: list[ChangeRecord] = field(default_factory=list)
    _original_doc: Document | None = field(default=None, repr=False)
    _working_doc: Document | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "board_path": self.board_path,
            "state": self.state.value,
            "change_count": len(self.changes),
            "changes": [c.to_dict() for c in self.changes],
        }


def _make_atom(val: str) -> SExp:
    """Create an atom SExp with original string preserved."""
    return SExp(value=val, _original_str=val)


def _make_quoted(val: str) -> SExp:
    """Create a quoted-string atom SExp."""
    return SExp(value=val, _original_str=f'"{val}"')


def _make_node(name: str, children: list[SExp] | None = None) -> SExp:
    """Create a named SExp node."""
    return SExp(name=name, children=children or [])


class SessionManager:
    """Manages mutation sessions for board modifications.

    Usage::

        mgr = SessionManager()
        session = mgr.start_session(doc)

        # Preview a move
        preview = mgr.query_move(session, "C7", x=20, y=10)

        # Apply the move
        mgr.apply_move(session, "C7", x=20, y=10)

        # Undo if needed
        mgr.undo(session)

        # Commit writes to disk, rollback discards all changes
        mgr.commit(session)  # or mgr.rollback(session)
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def start_session(self, doc: Document) -> Session:
        """Start a new mutation session for the given document."""
        session_id = str(uuid.uuid4())[:8]
        session = Session(
            session_id=session_id,
            board_path=str(doc.path),
            _original_doc=doc,
            _working_doc=self._deep_copy_doc(doc),
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session:
        """Get a session by ID."""
        if session_id not in self._sessions:
            raise KeyError(f"No session with ID {session_id!r}")
        return self._sessions[session_id]

    def _require_active(self, session: Session) -> None:
        if session.state != SessionState.ACTIVE:
            raise RuntimeError(f"Session {session.session_id} is {session.state.value}, not active")

    # ── Move ────────────────────────────────────────────────────────

    def query_move(
        self,
        session: Session,
        reference: str,
        x: float,
        y: float,
    ) -> dict[str, Any]:
        """Preview moving a component without applying the change."""
        self._require_active(session)
        assert session._working_doc is not None

        fp_node = self._find_footprint(session._working_doc, reference)
        if fp_node is None:
            return {"error": f"Component {reference!r} not found"}

        at_node = fp_node.get("at")
        current_x = float(at_node.atom_values[0]) if at_node and len(at_node.atom_values) > 0 else 0
        current_y = float(at_node.atom_values[1]) if at_node and len(at_node.atom_values) > 1 else 0

        return {
            "operation": "move_component",
            "target": reference,
            "current_position": {"x": current_x, "y": current_y},
            "new_position": {"x": x, "y": y},
            "preview": True,
        }

    def apply_move(
        self,
        session: Session,
        reference: str,
        x: float,
        y: float,
    ) -> ChangeRecord:
        """Apply a component move and record the change."""
        self._require_active(session)
        assert session._working_doc is not None

        fp_node = self._find_footprint(session._working_doc, reference)
        if fp_node is None:
            raise ValueError(f"Component {reference!r} not found")

        at_node = fp_node.get("at")
        before = at_node.to_string() if at_node else "(at 0 0)"

        if at_node is not None and len(at_node.children) >= 2:
            at_node.children[0] = _make_atom(str(x))
            at_node.children[1] = _make_atom(str(y))

        after = at_node.to_string() if at_node else f"(at {x} {y})"

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="move_component",
            description=f"Move {reference} to ({x}, {y})",
            target=reference,
            before_snapshot=before,
            after_snapshot=after,
            applied=True,
        )
        session.changes.append(record)
        return record

    # ── Rotate ──────────────────────────────────────────────────────

    def apply_rotate(
        self,
        session: Session,
        reference: str,
        angle: float,
    ) -> ChangeRecord:
        """Rotate a component to a given angle (degrees)."""
        self._require_active(session)
        assert session._working_doc is not None

        fp_node = self._find_footprint(session._working_doc, reference)
        if fp_node is None:
            raise ValueError(f"Component {reference!r} not found")

        at_node = fp_node.get("at")
        before = at_node.to_string() if at_node else "(at 0 0)"

        if at_node is not None:
            vals = at_node.atom_values
            if len(vals) >= 3:
                # Replace existing angle
                at_node.children[2] = _make_atom(str(angle))
            elif len(vals) >= 2:
                # Add angle as third child
                at_node.children.append(_make_atom(str(angle)))

        after = at_node.to_string() if at_node else f"(at 0 0 {angle})"

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="rotate_component",
            description=f"Rotate {reference} to {angle} degrees",
            target=reference,
            before_snapshot=before,
            after_snapshot=after,
            applied=True,
        )
        session.changes.append(record)
        return record

    # ── Flip ────────────────────────────────────────────────────────

    def apply_flip(self, session: Session, reference: str) -> ChangeRecord:
        """Flip a component to the opposite side of the board."""
        self._require_active(session)
        assert session._working_doc is not None

        fp_node = self._find_footprint(session._working_doc, reference)
        if fp_node is None:
            raise ValueError(f"Component {reference!r} not found")

        before = fp_node.to_string()

        # Flip the footprint layer
        layer_node = fp_node.get("layer")
        if layer_node and layer_node.children:
            old_layer = layer_node.children[0].value or ""
            new_layer = _LAYER_FLIP.get(old_layer, old_layer)
            layer_node.children[0] = _make_quoted(new_layer)

        # Flip layers in all pads
        for pad_node in fp_node.find_all("pad"):
            layers_node = pad_node.get("layers")
            if layers_node:
                for i, child in enumerate(layers_node.children):
                    if child.is_atom and child.value:
                        flipped = _LAYER_FLIP.get(child.value, child.value)
                        if flipped != child.value:
                            layers_node.children[i] = _make_quoted(flipped)

        # Flip layers on graphic items (fp_line, fp_rect, fp_circle, fp_arc, fp_text)
        for gfx_name in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_text"):
            for gfx in fp_node.find_all(gfx_name):
                gfx_layer = gfx.get("layer")
                if gfx_layer and gfx_layer.children:
                    old_val = gfx_layer.children[0].value or ""
                    new_val = _LAYER_FLIP.get(old_val, old_val)
                    if new_val != old_val:
                        gfx_layer.children[0] = _make_quoted(new_val)

        # Flip layers on properties
        for prop in fp_node.find_all("property"):
            prop_layer = prop.get("layer")
            if prop_layer and prop_layer.children:
                old_val = prop_layer.children[0].value or ""
                new_val = _LAYER_FLIP.get(old_val, old_val)
                if new_val != old_val:
                    prop_layer.children[0] = _make_quoted(new_val)

        after = fp_node.to_string()

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="flip_component",
            description=f"Flip {reference} to opposite side",
            target=reference,
            before_snapshot=before,
            after_snapshot=after,
            applied=True,
        )
        session.changes.append(record)
        return record

    # ── Delete ──────────────────────────────────────────────────────

    def apply_delete(self, session: Session, reference: str) -> ChangeRecord:
        """Delete a component from the board."""
        self._require_active(session)
        assert session._working_doc is not None

        fp_node = self._find_footprint(session._working_doc, reference)
        if fp_node is None:
            raise ValueError(f"Component {reference!r} not found")

        before = fp_node.to_string()

        # Remove the footprint node from the board root
        session._working_doc.root.children.remove(fp_node)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="delete_component",
            description=f"Delete component {reference}",
            target=reference,
            before_snapshot=before,
            after_snapshot="",
            applied=True,
        )
        session.changes.append(record)
        return record

    # ── Place ───────────────────────────────────────────────────────

    def apply_place(
        self,
        session: Session,
        footprint_library: str,
        reference: str,
        value: str,
        x: float,
        y: float,
        layer: str = "F.Cu",
    ) -> ChangeRecord:
        """Place a new component on the board.

        Args:
            session: Active session.
            footprint_library: Library identifier (e.g., "Resistor_SMD:R_0402_1005Metric").
            reference: Reference designator (e.g., "R1").
            value: Component value (e.g., "10k").
            x: X position in mm.
            y: Y position in mm.
            layer: Target layer ("F.Cu" or "B.Cu").
        """
        self._require_active(session)
        assert session._working_doc is not None

        # Check reference doesn't already exist
        existing = self._find_footprint(session._working_doc, reference)
        if existing is not None:
            raise ValueError(f"Component {reference!r} already exists on the board")

        # Try to resolve the full footprint from installed KiCad libraries
        mod_path = self._resolve_kicad_mod_path(footprint_library)
        if mod_path is not None:
            return self.place_from_kicad_mod(session, mod_path, reference, value, x, y, layer)

        # Fallback: create a skeleton footprint (no pads)
        fp_node = self._build_footprint_node(footprint_library, reference, value, x, y, layer)

        # Append to the board root children
        session._working_doc.root.children.append(fp_node)

        after = fp_node.to_string()

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="place_component",
            description=f"Place {reference} ({footprint_library}) at ({x}, {y}) on {layer}",
            target=reference,
            before_snapshot="",
            after_snapshot=after,
            applied=True,
        )
        session.changes.append(record)
        return record

    def place_from_kicad_mod(
        self,
        session: Session,
        kicad_mod_path: str,
        reference: str,
        value: str,
        x: float,
        y: float,
        layer: str = "F.Cu",
    ) -> ChangeRecord:
        """Place a component by reading its footprint from a .kicad_mod file.

        Args:
            session: Active session.
            kicad_mod_path: Path to a .kicad_mod file.
            reference: Reference designator.
            value: Component value.
            x: X position in mm.
            y: Y position in mm.
            layer: Target layer.
        """
        self._require_active(session)
        assert session._working_doc is not None

        existing = self._find_footprint(session._working_doc, reference)
        if existing is not None:
            raise ValueError(f"Component {reference!r} already exists on the board")

        from pathlib import Path

        mod_path = Path(kicad_mod_path)
        if not mod_path.exists():
            raise FileNotFoundError(f"Footprint file not found: {kicad_mod_path}")

        raw = mod_path.read_text(encoding="utf-8")
        fp_node = sexp_parse(raw)

        # Update position — insert after the library name atom (first child),
        # not at position 0 which would break KiCad's expected ordering:
        # (footprint "LibName" (layer ...) ... (at X Y) ...)
        at_node = fp_node.get("at")
        if at_node is None:
            at_node = _make_node("at", [_make_atom(str(x)), _make_atom(str(y))])
            # Find insertion point: after all leading atom children
            insert_idx = 0
            for i, child in enumerate(fp_node.children):
                if child.is_atom:
                    insert_idx = i + 1
                else:
                    break
            fp_node.children.insert(insert_idx, at_node)
        else:
            at_node.children = [_make_atom(str(x)), _make_atom(str(y))]

        # Update layer
        layer_node = fp_node.get("layer")
        if layer_node and layer_node.children:
            layer_node.children[0] = _make_quoted(layer)

        # Update Reference property
        for prop in fp_node.find_all("property"):
            if prop.first_value == "Reference":
                vals = prop.atom_values
                if len(vals) > 1:
                    # Replace the second atom child (the value)
                    atom_idx = 0
                    for i, child in enumerate(prop.children):
                        if child.is_atom:
                            atom_idx += 1
                            if atom_idx == 2:
                                prop.children[i] = _make_quoted(reference)
                                break
            elif prop.first_value == "Value":
                vals = prop.atom_values
                if len(vals) > 1:
                    atom_idx = 0
                    for i, child in enumerate(prop.children):
                        if child.is_atom:
                            atom_idx += 1
                            if atom_idx == 2:
                                prop.children[i] = _make_quoted(value)
                                break

        # Generate a fresh UUID
        uuid_node = fp_node.get("uuid")
        new_uuid = str(uuid.uuid4())
        if uuid_node and uuid_node.children:
            uuid_node.children[0] = _make_quoted(new_uuid)

        session._working_doc.root.children.append(fp_node)

        after = fp_node.to_string()
        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="place_component",
            description=f"Place {reference} from {mod_path.name} at ({x}, {y}) on {layer}",
            target=reference,
            before_snapshot="",
            after_snapshot=after,
            applied=True,
        )
        session.changes.append(record)
        return record

    @staticmethod
    def _resolve_kicad_mod_path(footprint_library: str) -> str | None:
        """Try to resolve a library:footprint identifier to a .kicad_mod path.

        Args:
            footprint_library: e.g., "Resistor_SMD:R_0402_1005Metric"

        Returns:
            Path string to .kicad_mod file if found, None otherwise.
        """
        if ":" not in footprint_library:
            return None

        lib_name, fp_name = footprint_library.split(":", 1)

        try:
            from ..library import discover_lib_tables
        except Exception:
            return None

        try:
            tables = discover_lib_tables()
        except Exception:
            return None

        from pathlib import Path

        for entry in tables.get("footprint_libraries", []):
            if entry.name == lib_name:
                lib_dir = Path(entry.uri)
                mod_path = lib_dir / f"{fp_name}.kicad_mod"
                if mod_path.exists():
                    return str(mod_path)
        return None

    @staticmethod
    def _build_footprint_node(
        library: str,
        reference: str,
        value: str,
        x: float,
        y: float,
        layer: str,
    ) -> SExp:
        """Build a minimal footprint S-expression node (skeleton fallback)."""
        new_uuid = str(uuid.uuid4())
        sexp_text = (
            f'(footprint "{library}"'
            f' (layer "{layer}")'
            f' (uuid "{new_uuid}")'
            f" (at {x} {y})"
            f' (property "Reference" "{reference}"'
            f' (at 0 -1.5 0) (layer "{layer}") (uuid "{uuid.uuid4()}")'
            f" (effects (font (size 1 1) (thickness 0.15))))"
            f' (property "Value" "{value}"'
            f' (at 0 1.5 0) (layer "F.Fab") (uuid "{uuid.uuid4()}")'
            f" (effects (font (size 1 1) (thickness 0.15))))"
            f" (attr smd) (embedded_fonts no))"
        )
        return sexp_parse(sexp_text)

    # ── Net management ──────────────────────────────────────────────

    def apply_create_net(
        self,
        session: Session,
        net_name: str,
    ) -> ChangeRecord:
        """Add a new net to the board.

        Automatically assigns the next available net number.
        """
        self._require_active(session)
        assert session._working_doc is not None

        # Check for duplicate name
        for net_node in session._working_doc.root.find_all("net"):
            vals = net_node.atom_values
            if len(vals) >= 2 and vals[1] == net_name:
                raise ValueError(f"Net {net_name!r} already exists")

        # Find max net number
        max_num = 0
        for net_node in session._working_doc.root.find_all("net"):
            vals = net_node.atom_values
            if vals:
                with contextlib.suppress(ValueError):
                    max_num = max(max_num, int(vals[0]))

        new_num = max_num + 1
        net_sexp = sexp_parse(f'(net {new_num} "{net_name}")')

        # Insert after the last existing net node
        insert_idx = 0
        for i, child in enumerate(session._working_doc.root.children):
            if child.name == "net":
                insert_idx = i + 1
        if insert_idx == 0:
            # No nets exist, insert after layers
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "layers":
                    insert_idx = i + 1
                    break

        session._working_doc.root.children.insert(insert_idx, net_sexp)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="create_net",
            description=f"Create net {new_num} '{net_name}'",
            target=net_name,
            before_snapshot="",
            after_snapshot=net_sexp.to_string(),
            applied=True,
        )
        session.changes.append(record)
        return record

    def apply_delete_net(
        self,
        session: Session,
        net_name: str,
    ) -> ChangeRecord:
        """Remove a net declaration from the board."""
        self._require_active(session)
        assert session._working_doc is not None

        target_node = None
        for net_node in session._working_doc.root.find_all("net"):
            vals = net_node.atom_values
            if len(vals) >= 2 and vals[1] == net_name:
                target_node = net_node
                break

        if target_node is None:
            raise ValueError(f"Net {net_name!r} not found")

        before = target_node.to_string()
        session._working_doc.root.children.remove(target_node)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="delete_net",
            description=f"Delete net '{net_name}'",
            target=net_name,
            before_snapshot=before,
            after_snapshot="",
            applied=True,
        )
        session.changes.append(record)
        return record

    def apply_assign_net(
        self,
        session: Session,
        reference: str,
        pad_number: str,
        net_name: str,
    ) -> ChangeRecord:
        """Assign a net to a specific pad on a component.

        Args:
            session: Active session.
            reference: Component reference designator.
            pad_number: Pad number string (e.g., "1", "2").
            net_name: Net name to assign. Must already exist on the board.
        """
        self._require_active(session)
        assert session._working_doc is not None

        # Find the net number for the name
        net_num = None
        for net_node in session._working_doc.root.find_all("net"):
            vals = net_node.atom_values
            if len(vals) >= 2 and vals[1] == net_name:
                net_num = int(vals[0])
                break
        if net_num is None:
            raise ValueError(f"Net {net_name!r} not found on the board")

        fp_node = self._find_footprint(session._working_doc, reference)
        if fp_node is None:
            raise ValueError(f"Component {reference!r} not found")

        # Find the target pad
        target_pad = None
        for pad_node in fp_node.find_all("pad"):
            vals = pad_node.atom_values
            if vals and vals[0] == pad_number:
                target_pad = pad_node
                break
        if target_pad is None:
            raise ValueError(f"Pad {pad_number!r} not found on {reference}")

        # Snapshot before
        before = target_pad.to_string()

        # Update or create net node on pad
        existing_net = target_pad.get("net")
        if existing_net is not None:
            target_pad.children.remove(existing_net)

        net_child = sexp_parse(f'(net {net_num} "{net_name}")')
        target_pad.children.append(net_child)

        after = target_pad.to_string()

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="assign_net",
            description=f"Assign net '{net_name}' to {reference} pad {pad_number}",
            target=f"{reference}:{pad_number}",
            before_snapshot=before,
            after_snapshot=after,
            applied=True,
        )
        session.changes.append(record)
        return record

    # ── Zone management ─────────────────────────────────────────────

    def apply_create_zone(
        self,
        session: Session,
        net_name: str,
        layer: str,
        points: list[tuple[float, float]],
        min_thickness: float = 0.25,
        priority: int = 0,
    ) -> ChangeRecord:
        """Create a copper zone (pour) on the board.

        Args:
            session: Active session.
            net_name: Net to fill the zone with (e.g., "GND").
            layer: Copper layer (e.g., "F.Cu").
            points: List of (x, y) tuples defining the zone polygon outline.
            min_thickness: Minimum trace width in zone fill (mm).
            priority: Zone fill priority (higher = filled first).
        """
        self._require_active(session)
        assert session._working_doc is not None

        if len(points) < 3:
            raise ValueError("Zone polygon requires at least 3 points")

        # Find the net number
        net_num = None
        for net_node in session._working_doc.root.find_all("net"):
            vals = net_node.atom_values
            if len(vals) >= 2 and vals[1] == net_name:
                net_num = int(vals[0])
                break
        if net_num is None:
            raise ValueError(f"Net {net_name!r} not found on the board")

        zone_uuid = str(uuid.uuid4())

        # Build polygon points string
        pts_strs = " ".join(f"(xy {x} {y})" for x, y in points)

        zone_sexp_text = (
            f'(zone (net {net_num}) (net_name "{net_name}") (layer "{layer}")'
            f' (uuid "{zone_uuid}")'
            f" (hatch edge 0.5)"
            f" (priority {priority})"
            f" (connect_pads (clearance 0.5))"
            f" (min_thickness {min_thickness})"
            f" (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))"
            f" (polygon (pts {pts_strs})))"
        )
        zone_node = sexp_parse(zone_sexp_text)

        session._working_doc.root.children.append(zone_node)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="create_zone",
            description=f"Create {net_name} zone on {layer} ({len(points)} points)",
            target=f"zone:{zone_uuid[:8]}",
            before_snapshot="",
            after_snapshot=zone_node.to_string(),
            applied=True,
        )
        session.changes.append(record)
        return record

    # ── Trace routing ─────────────────────────────────────────────

    def apply_route_trace(
        self,
        session: Session,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        width: float,
        layer: str,
        net_number: int,
    ) -> ChangeRecord:
        """Add a trace segment between two points.

        Args:
            session: Active session.
            start_x: Start X coordinate (mm).
            start_y: Start Y coordinate (mm).
            end_x: End X coordinate (mm).
            end_y: End Y coordinate (mm).
            width: Trace width (mm).
            layer: Copper layer (e.g., "F.Cu").
            net_number: Net number for the trace.
        """
        self._require_active(session)
        assert session._working_doc is not None

        seg_uuid = str(uuid.uuid4())
        seg_text = (
            f"(segment (start {start_x} {start_y}) (end {end_x} {end_y})"
            f' (width {width}) (layer "{layer}") (net {net_number})'
            f' (uuid "{seg_uuid}"))'
        )
        seg_node = sexp_parse(seg_text)
        session._working_doc.root.children.append(seg_node)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="route_trace",
            description=(
                f"Route trace ({start_x},{start_y})->({end_x},{end_y})"
                f" w={width} on {layer} net {net_number}"
            ),
            target=f"segment:{seg_uuid}",
            before_snapshot="",
            after_snapshot=seg_node.to_string(),
            applied=True,
        )
        session.changes.append(record)
        return record

    def apply_add_via(
        self,
        session: Session,
        x: float,
        y: float,
        net_number: int,
        size: float = 0.8,
        drill: float = 0.4,
        layers: tuple[str, str] = ("F.Cu", "B.Cu"),
    ) -> ChangeRecord:
        """Add a via at a specific point.

        Args:
            session: Active session.
            x: X coordinate (mm).
            y: Y coordinate (mm).
            net_number: Net number.
            size: Via pad size (mm).
            drill: Via drill diameter (mm).
            layers: Tuple of (start_layer, end_layer).
        """
        self._require_active(session)
        assert session._working_doc is not None

        via_uuid = str(uuid.uuid4())
        via_text = (
            f"(via (at {x} {y}) (size {size}) (drill {drill})"
            f' (layers "{layers[0]}" "{layers[1]}") (net {net_number})'
            f' (uuid "{via_uuid}"))'
        )
        via_node = sexp_parse(via_text)
        session._working_doc.root.children.append(via_node)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="add_via",
            description=f"Add via at ({x},{y}) net {net_number} {layers[0]}->{layers[1]}",
            target=f"via:{via_uuid}",
            before_snapshot="",
            after_snapshot=via_node.to_string(),
            applied=True,
        )
        session.changes.append(record)
        return record

    def apply_delete_trace(
        self,
        session: Session,
        segment_uuid: str,
    ) -> ChangeRecord:
        """Delete a trace segment by UUID.

        Args:
            session: Active session.
            segment_uuid: UUID of the segment to delete.
        """
        self._require_active(session)
        assert session._working_doc is not None

        target = None
        for child in session._working_doc.root.children:
            if child.name == "segment":
                uuid_node = child.get("uuid")
                if uuid_node and uuid_node.first_value == segment_uuid:
                    target = child
                    break

        if target is None:
            raise ValueError(f"Segment with UUID {segment_uuid!r} not found")

        before = target.to_string()
        session._working_doc.root.children.remove(target)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="delete_trace",
            description=f"Delete segment {segment_uuid[:8]}",
            target=f"segment:{segment_uuid}",
            before_snapshot=before,
            after_snapshot="",
            applied=True,
        )
        session.changes.append(record)
        return record

    def apply_delete_via(
        self,
        session: Session,
        via_uuid: str,
    ) -> ChangeRecord:
        """Delete a via by UUID.

        Args:
            session: Active session.
            via_uuid: UUID of the via to delete.
        """
        self._require_active(session)
        assert session._working_doc is not None

        target = None
        for child in session._working_doc.root.children:
            if child.name == "via":
                uuid_node = child.get("uuid")
                if uuid_node and uuid_node.first_value == via_uuid:
                    target = child
                    break

        if target is None:
            raise ValueError(f"Via with UUID {via_uuid!r} not found")

        before = target.to_string()
        session._working_doc.root.children.remove(target)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="delete_via",
            description=f"Delete via {via_uuid[:8]}",
            target=f"via:{via_uuid}",
            before_snapshot=before,
            after_snapshot="",
            applied=True,
        )
        session.changes.append(record)
        return record

    def get_ratsnest(self, session: Session) -> list[dict[str, Any]]:
        """Get unrouted connections (ratsnest) for the board.

        Finds pads with net assignments that lack trace connections.
        Returns a list of net-grouped unrouted pairs.
        """
        self._require_active(session)
        assert session._working_doc is not None
        doc = session._working_doc

        # Collect all pad positions by net
        net_pads: dict[int, list[dict[str, Any]]] = {}
        for fp_node in doc.root.find_all("footprint"):
            ref = ""
            for prop in fp_node.find_all("property"):
                if prop.first_value == "Reference":
                    vals = prop.atom_values
                    if len(vals) > 1:
                        ref = vals[1]

            fp_at = fp_node.get("at")
            fp_x = float(fp_at.atom_values[0]) if fp_at and fp_at.atom_values else 0
            fp_y = float(fp_at.atom_values[1]) if fp_at and len(fp_at.atom_values) > 1 else 0

            for pad_node in fp_node.find_all("pad"):
                net_node = pad_node.get("net")
                if net_node:
                    net_vals = net_node.atom_values
                    if net_vals:
                        net_num = int(net_vals[0])
                        if net_num == 0:
                            continue
                        pad_at = pad_node.get("at")
                        pad_x = float(pad_at.atom_values[0]) if pad_at else 0
                        pad_y = (
                            float(pad_at.atom_values[1])
                            if pad_at and len(pad_at.atom_values) > 1
                            else 0
                        )
                        pad_vals = pad_node.atom_values
                        net_pads.setdefault(net_num, []).append(
                            {
                                "reference": ref,
                                "pad": pad_vals[0] if pad_vals else "",
                                "x": fp_x + pad_x,
                                "y": fp_y + pad_y,
                            }
                        )

        # Collect routed segment endpoints by net
        routed_nets: set[int] = set()
        for seg in doc.root.find_all("segment"):
            net_node = seg.get("net")
            if net_node and net_node.first_value:
                routed_nets.add(int(net_node.first_value))

        # Nets with pads but no segments are unrouted
        unrouted: list[dict[str, Any]] = []
        for net_num, pads in sorted(net_pads.items()):
            if net_num not in routed_nets and len(pads) >= 2:
                # Get net name
                net_name = ""
                for net_node in doc.root.find_all("net"):
                    vals = net_node.atom_values
                    if vals and int(vals[0]) == net_num:
                        net_name = vals[1] if len(vals) > 1 else ""
                        break
                unrouted.append(
                    {
                        "net_number": net_num,
                        "net_name": net_name,
                        "pad_count": len(pads),
                        "pads": pads,
                    }
                )

        return unrouted

    # ── Board Setup ─────────────────────────────────────────────────

    def apply_set_board_size(
        self,
        session: Session,
        width: float,
        height: float,
    ) -> ChangeRecord:
        """Set the board size by creating/replacing Edge.Cuts outline as a rectangle.

        Args:
            session: Active session.
            width: Board width in mm.
            height: Board height in mm.
        """
        self._require_active(session)
        assert session._working_doc is not None

        # Remove existing Edge.Cuts gr_line/gr_rect nodes
        before_lines = []
        to_remove = []
        for child in session._working_doc.root.children:
            if child.name in ("gr_line", "gr_rect"):
                layer_node = child.get("layer")
                if layer_node and layer_node.first_value == "Edge.Cuts":
                    before_lines.append(child.to_string())
                    to_remove.append(child)
        for node in to_remove:
            session._working_doc.root.children.remove(node)

        # Create 4 gr_line segments forming a rectangle at origin
        lines = [
            (0, 0, width, 0),
            (width, 0, width, height),
            (width, height, 0, height),
            (0, height, 0, 0),
        ]
        after_lines = []
        for x1, y1, x2, y2 in lines:
            line_uuid = str(uuid.uuid4())
            line_text = (
                f"(gr_line (start {x1} {y1}) (end {x2} {y2})"
                f" (stroke (width 0.05) (type default))"
                f' (layer "Edge.Cuts") (uuid "{line_uuid}"))'
            )
            line_node = sexp_parse(line_text)
            session._working_doc.root.children.append(line_node)
            after_lines.append(line_node.to_string())

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="set_board_size",
            description=f"Set board size to {width}x{height}mm",
            target="Edge.Cuts",
            before_snapshot="\n".join(before_lines),
            after_snapshot="\n".join(after_lines),
            applied=True,
        )
        session.changes.append(record)
        return record

    def apply_add_board_outline(
        self,
        session: Session,
        points: list[tuple[float, float]],
    ) -> ChangeRecord:
        """Replace board outline with segments on Edge.Cuts layer.

        Removes any existing Edge.Cuts gr_line/gr_rect nodes first to avoid
        duplicate outlines, then creates new line segments.

        Args:
            session: Active session.
            points: List of (x, y) tuples. Lines are drawn between consecutive
                    points, and the last point is connected back to the first.
        """
        self._require_active(session)
        assert session._working_doc is not None

        if len(points) < 3:
            raise ValueError("Board outline requires at least 3 points")

        # Remove existing Edge.Cuts gr_line/gr_rect nodes
        before_lines: list[str] = []
        to_remove = []
        for child in session._working_doc.root.children:
            if child.name in ("gr_line", "gr_rect"):
                layer_node = child.get("layer")
                if layer_node and layer_node.first_value == "Edge.Cuts":
                    before_lines.append(child.to_string())
                    to_remove.append(child)
        for node in to_remove:
            session._working_doc.root.children.remove(node)

        after_lines = []
        for i in range(len(points)):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % len(points)]
            line_uuid = str(uuid.uuid4())
            line_text = (
                f"(gr_line (start {x1} {y1}) (end {x2} {y2})"
                f" (stroke (width 0.05) (type default))"
                f' (layer "Edge.Cuts") (uuid "{line_uuid}"))'
            )
            line_node = sexp_parse(line_text)
            session._working_doc.root.children.append(line_node)
            after_lines.append(line_node.to_string())

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="add_board_outline",
            description=f"Set board outline with {len(points)} points",
            target="Edge.Cuts",
            before_snapshot="\n".join(before_lines),
            after_snapshot="\n".join(after_lines),
            applied=True,
        )
        session.changes.append(record)
        return record

    def apply_add_mounting_hole(
        self,
        session: Session,
        x: float,
        y: float,
        drill: float = 3.2,
        pad_dia: float = 6.0,
    ) -> ChangeRecord:
        """Insert a mounting hole footprint at the given position.

        Args:
            session: Active session.
            x: X position in mm.
            y: Y position in mm.
            drill: Drill diameter in mm.
            pad_dia: Pad diameter in mm.
        """
        self._require_active(session)
        assert session._working_doc is not None

        hole_uuid = str(uuid.uuid4())
        ref_uuid = str(uuid.uuid4())
        val_uuid = str(uuid.uuid4())
        fp_text = (
            f'(footprint "MountingHole:MountingHole_{drill}mm"'
            f' (layer "F.Cu") (uuid "{hole_uuid}") (at {x} {y})'
            f' (property "Reference" "H1"'
            f' (at 0 -{pad_dia / 2 + 1} 0) (layer "F.SilkS") (uuid "{ref_uuid}")'
            f" (effects (font (size 1 1) (thickness 0.15))))"
            f' (property "Value" "MountingHole"'
            f' (at 0 {pad_dia / 2 + 1} 0) (layer "F.Fab") (uuid "{val_uuid}")'
            f" (effects (font (size 1 1) (thickness 0.15))))"
            f' (pad "" np_thru_hole circle (at 0 0)'
            f" (size {pad_dia} {pad_dia}) (drill {drill})"
            f' (layers "*.Cu" "*.Mask")))'
        )
        fp_node = sexp_parse(fp_text)
        session._working_doc.root.children.append(fp_node)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="add_mounting_hole",
            description=f"Add mounting hole at ({x}, {y}) drill={drill}mm",
            target=f"mounting_hole:{hole_uuid[:8]}",
            before_snapshot="",
            after_snapshot=fp_node.to_string(),
            applied=True,
        )
        session.changes.append(record)
        return record

    def apply_add_board_text(
        self,
        session: Session,
        text: str,
        x: float,
        y: float,
        layer: str = "F.SilkS",
        size: float = 1.0,
        angle: float = 0,
    ) -> ChangeRecord:
        """Add a text element to the board.

        Args:
            session: Active session.
            text: The text string to add.
            x: X position in mm.
            y: Y position in mm.
            layer: Target layer. Defaults to "F.SilkS".
            size: Text height in mm. Defaults to 1.0.
            angle: Rotation angle in degrees. Defaults to 0.
        """
        self._require_active(session)
        assert session._working_doc is not None

        text_uuid = str(uuid.uuid4())
        angle_str = f" {angle}" if angle != 0 else ""
        thickness = size * 0.15
        text_sexp = (
            f'(gr_text "{text}" (at {x} {y}{angle_str})'
            f' (layer "{layer}") (uuid "{text_uuid}")'
            f" (effects (font (size {size} {size}) (thickness {thickness}))))"
        )
        text_node = sexp_parse(text_sexp)
        session._working_doc.root.children.append(text_node)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="add_board_text",
            description=f"Add text '{text}' at ({x}, {y}) on {layer}",
            target=f"text:{text_uuid[:8]}",
            before_snapshot="",
            after_snapshot=text_node.to_string(),
            applied=True,
        )
        session.changes.append(record)
        return record

    # Valid KiCad 9 setup keys that accept numeric design-rule values.
    # Rules like min_track_width, min_via_diameter, etc. belong in the
    # separate .kicad_dru (design rules) file, NOT in setup.
    _VALID_SETUP_RULES: frozenset[str] = frozenset(
        {
            "pad_to_mask_clearance",
            "solder_mask_min_width",
            "pad_to_paste_clearance",
            "pad_to_paste_clearance_ratio",
        }
    )

    # Friendly aliases for the valid setup keys.
    _RULE_ALIASES: dict[str, str] = {
        "min_clearance": "pad_to_mask_clearance",
        "mask_clearance": "pad_to_mask_clearance",
        "mask_min_width": "solder_mask_min_width",
        "paste_clearance": "pad_to_paste_clearance",
        "paste_clearance_ratio": "pad_to_paste_clearance_ratio",
    }

    # Rules that callers commonly attempt but belong in .kicad_dru.
    _DRU_ONLY_RULES: frozenset[str] = frozenset(
        {
            "min_track_width",
            "min_via_diameter",
            "min_via_drill",
            "min_microvia_diameter",
            "min_microvia_drill",
            "min_through_hole_diameter",
            "clearance",
        }
    )

    def apply_set_design_rules(
        self,
        session: Session,
        rules: dict[str, float],
    ) -> ChangeRecord:
        """Modify design rules in the board setup section.

        Only keys that KiCad 9 accepts in the (setup ...) section are
        allowed: pad_to_mask_clearance, solder_mask_min_width,
        pad_to_paste_clearance, pad_to_paste_clearance_ratio.

        Rules like min_track_width, min_via_diameter, etc. belong in the
        .kicad_dru (design rules) file and are rejected with a clear error.

        Args:
            session: Active session.
            rules: Dict of rule name to value, e.g.:
                {"pad_to_mask_clearance": 0.1, "solder_mask_min_width": 0.05}
        """
        self._require_active(session)
        assert session._working_doc is not None

        setup_node = session._working_doc.root.get("setup")
        if setup_node is None:
            raise ValueError("Board has no setup section")

        # Validate all keys before modifying anything.
        resolved: list[tuple[str, float]] = []
        for rule_name, value in rules.items():
            sexp_name = self._RULE_ALIASES.get(rule_name, rule_name)
            if sexp_name in self._DRU_ONLY_RULES:
                raise ValueError(
                    f"'{rule_name}' cannot be set in the board setup section. "
                    f"In KiCad 9 this rule belongs in the .kicad_dru "
                    f"(design rules) file. Valid setup keys: "
                    f"{sorted(self._VALID_SETUP_RULES)}"
                )
            if sexp_name not in self._VALID_SETUP_RULES:
                raise ValueError(
                    f"Unknown design rule '{rule_name}'. "
                    f"Valid setup keys: {sorted(self._VALID_SETUP_RULES)}. "
                    f"Aliases: {sorted(self._RULE_ALIASES.keys())}"
                )
            resolved.append((sexp_name, value))

        before = setup_node.to_string()

        for sexp_name, value in resolved:
            existing = setup_node.get(sexp_name)
            if existing is not None and existing.children:
                existing.children[0] = _make_atom(str(value))
            else:
                new_node = sexp_parse(f"({sexp_name} {value})")
                setup_node.children.append(new_node)

        after = setup_node.to_string()

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="set_design_rules",
            description=f"Set design rules: {list(rules.keys())}",
            target="setup",
            before_snapshot=before,
            after_snapshot=after,
            applied=True,
        )
        session.changes.append(record)
        return record

    # ── Component Edit/Replace ───────────────────────────────────────

    def apply_edit_component(
        self,
        session: Session,
        reference: str,
        properties: dict[str, str],
    ) -> ChangeRecord:
        """Update property values on an existing footprint.

        Args:
            session: Active session.
            reference: Component reference designator.
            properties: Dict of property name to new value, e.g.
                        {"Value": "22k", "Footprint": "Resistor_SMD:R_0805"}.
        """
        self._require_active(session)
        assert session._working_doc is not None

        fp_node = self._find_footprint(session._working_doc, reference)
        if fp_node is None:
            raise ValueError(f"Component {reference!r} not found")

        before = fp_node.to_string()

        for prop_name, prop_value in properties.items():
            found = False
            for prop in fp_node.find_all("property"):
                if prop.first_value == prop_name:
                    # Replace the second atom child (the value)
                    atom_idx = 0
                    for i, child in enumerate(prop.children):
                        if child.is_atom:
                            atom_idx += 1
                            if atom_idx == 2:
                                prop.children[i] = _make_quoted(prop_value)
                                found = True
                                break
                    break
            if not found:
                # Add new property
                prop_uuid = str(uuid.uuid4())
                prop_text = (
                    f'(property "{prop_name}" "{prop_value}"'
                    f' (at 0 0 0) (layer "F.Fab") (uuid "{prop_uuid}")'
                    f" (effects (font (size 1 1) (thickness 0.15)) hide))"
                )
                fp_node.children.append(sexp_parse(prop_text))

        after = fp_node.to_string()

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="edit_component",
            description=f"Edit {reference} properties: {list(properties.keys())}",
            target=reference,
            before_snapshot=before,
            after_snapshot=after,
            applied=True,
        )
        session.changes.append(record)
        return record

    def apply_replace_component(
        self,
        session: Session,
        reference: str,
        new_library: str,
        new_value: str,
    ) -> ChangeRecord:
        """Replace a component with a different footprint, keeping position.

        Args:
            session: Active session.
            reference: Reference designator of component to replace.
            new_library: New library:footprint identifier.
            new_value: New component value.
        """
        self._require_active(session)
        assert session._working_doc is not None

        fp_node = self._find_footprint(session._working_doc, reference)
        if fp_node is None:
            raise ValueError(f"Component {reference!r} not found")

        # Preserve position and layer
        at_node = fp_node.get("at")
        x = float(at_node.atom_values[0]) if at_node and at_node.atom_values else 0
        y = float(at_node.atom_values[1]) if at_node and len(at_node.atom_values) > 1 else 0
        layer_node = fp_node.get("layer")
        layer = layer_node.first_value if layer_node else "F.Cu"

        before = fp_node.to_string()

        # Remove old footprint
        session._working_doc.root.children.remove(fp_node)

        # Try to resolve the full footprint from installed KiCad libraries
        mod_path = self._resolve_kicad_mod_path(new_library)
        if mod_path is not None:
            from pathlib import Path

            raw = Path(mod_path).read_text(encoding="utf-8")
            new_fp = sexp_parse(raw)

            # Update position
            at_node = new_fp.get("at")
            if at_node is None:
                at_node = _make_node("at", [_make_atom(str(x)), _make_atom(str(y))])
                new_fp.children.insert(0, at_node)
            else:
                at_node.children = [_make_atom(str(x)), _make_atom(str(y))]

            # Update layer
            layer_nd = new_fp.get("layer")
            if layer_nd and layer_nd.children:
                layer_nd.children[0] = _make_quoted(layer)

            # Update Reference property
            for prop in new_fp.find_all("property"):
                if prop.first_value == "Reference":
                    atom_idx = 0
                    for i, child in enumerate(prop.children):
                        if child.is_atom:
                            atom_idx += 1
                            if atom_idx == 2:
                                prop.children[i] = _make_quoted(reference)
                                break
                elif prop.first_value == "Value":
                    atom_idx = 0
                    for i, child in enumerate(prop.children):
                        if child.is_atom:
                            atom_idx += 1
                            if atom_idx == 2:
                                prop.children[i] = _make_quoted(new_value)
                                break

            # Generate a fresh UUID
            uuid_node = new_fp.get("uuid")
            new_uuid = str(uuid.uuid4())
            if uuid_node and uuid_node.children:
                uuid_node.children[0] = _make_quoted(new_uuid)
        else:
            # Fallback: skeleton footprint
            new_fp = self._build_footprint_node(new_library, reference, new_value, x, y, layer)

        session._working_doc.root.children.append(new_fp)

        after = new_fp.to_string()

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="replace_component",
            description=f"Replace {reference} with {new_library} ({new_value})",
            target=reference,
            before_snapshot=before,
            after_snapshot=after,
            applied=True,
        )
        session.changes.append(record)
        return record

    # ── Net class / layer constraints ────────────────────────────────

    def apply_add_net_class(
        self,
        session: Session,
        name: str,
        clearance: float = 0.2,
        trace_width: float = 0.25,
        via_dia: float = 0.8,
        via_drill: float = 0.4,
        nets: list[str] | None = None,
    ) -> ChangeRecord:
        """Add a net class definition to the board.

        Args:
            session: Active session.
            name: Net class name (e.g., "Power", "Signal").
            clearance: Minimum clearance in mm.
            trace_width: Default trace width in mm.
            via_dia: Via diameter in mm.
            via_drill: Via drill in mm.
            nets: List of net names to assign to this class.
        """
        self._require_active(session)
        assert session._working_doc is not None

        nets_str = ""
        if nets:
            nets_str = " ".join(f'(add_net "{n}")' for n in nets)
            nets_str = " " + nets_str

        nc_uuid = str(uuid.uuid4())
        nc_text = (
            f'(net_class "{name}" ""'
            f" (clearance {clearance}) (trace_width {trace_width})"
            f" (via_dia {via_dia}) (via_drill {via_drill})"
            f' (uuid "{nc_uuid}"){nets_str})'
        )
        nc_node = sexp_parse(nc_text)

        # Insert in setup section if it exists, otherwise at board root
        setup_node = session._working_doc.root.get("setup")
        if setup_node is not None:
            setup_node.children.append(nc_node)
        else:
            session._working_doc.root.children.append(nc_node)

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="add_net_class",
            description=f"Add net class '{name}'",
            target=f"net_class:{name}",
            before_snapshot="",
            after_snapshot=nc_node.to_string(),
            applied=True,
        )
        session.changes.append(record)
        return record

    def apply_set_layer_constraints(
        self,
        session: Session,
        layer: str,
        min_width: float | None = None,
        min_clearance: float | None = None,
    ) -> ChangeRecord:
        """Set per-layer constraints in the board setup.

        Args:
            session: Active session.
            layer: Layer name (e.g., "F.Cu").
            min_width: Minimum trace width on this layer (mm).
            min_clearance: Minimum clearance on this layer (mm).
        """
        self._require_active(session)
        assert session._working_doc is not None

        setup_node = session._working_doc.root.get("setup")
        if setup_node is None:
            raise ValueError("Board has no setup section")

        before = setup_node.to_string()

        # Find or create layer_constraints for this layer
        constraint_node = None
        for child in setup_node.children:
            if child.name == "layer_constraints":
                layer_child = child.get("layer")
                if layer_child and layer_child.first_value == layer:
                    constraint_node = child
                    break

        if constraint_node is None:
            parts = [f'(layer "{layer}")']
            if min_width is not None:
                parts.append(f"(min_width {min_width})")
            if min_clearance is not None:
                parts.append(f"(min_clearance {min_clearance})")
            constraint_text = f"(layer_constraints {' '.join(parts)})"
            constraint_node = sexp_parse(constraint_text)
            setup_node.children.append(constraint_node)
        else:
            if min_width is not None:
                existing = constraint_node.get("min_width")
                if existing and existing.children:
                    existing.children[0] = _make_atom(str(min_width))
                else:
                    constraint_node.children.append(sexp_parse(f"(min_width {min_width})"))
            if min_clearance is not None:
                existing = constraint_node.get("min_clearance")
                if existing and existing.children:
                    existing.children[0] = _make_atom(str(min_clearance))
                else:
                    constraint_node.children.append(sexp_parse(f"(min_clearance {min_clearance})"))

        after = setup_node.to_string()

        record = ChangeRecord(
            change_id=str(uuid.uuid4())[:8],
            operation="set_layer_constraints",
            description=f"Set constraints for {layer}",
            target=f"layer:{layer}",
            before_snapshot=before,
            after_snapshot=after,
            applied=True,
        )
        session.changes.append(record)
        return record

    # ── Undo ────────────────────────────────────────────────────────

    def undo(self, session: Session) -> ChangeRecord | None:
        """Undo the last applied change in the session."""
        self._require_active(session)
        assert session._working_doc is not None

        for record in reversed(session.changes):
            if record.applied:
                self._undo_record(session, record)
                record.applied = False
                return record
        return None

    def _undo_record(self, session: Session, record: ChangeRecord) -> None:
        """Reverse a single change record."""
        assert session._working_doc is not None

        if record.operation in ("move_component", "rotate_component"):
            fp_node = self._find_footprint(session._working_doc, record.target)
            if fp_node is not None:
                before_node = sexp_parse(record.before_snapshot)
                at_node = fp_node.get("at")
                if at_node and before_node:
                    at_node.children = before_node.children[:]

        elif record.operation == "flip_component":
            fp_node = self._find_footprint(session._working_doc, record.target)
            if fp_node is not None:
                # Replace the entire footprint with the before snapshot
                before_node = sexp_parse(record.before_snapshot)
                idx = session._working_doc.root.children.index(fp_node)
                session._working_doc.root.children[idx] = before_node

        elif record.operation == "delete_component":
            # Re-insert the deleted footprint
            if record.before_snapshot:
                restored = sexp_parse(record.before_snapshot)
                session._working_doc.root.children.append(restored)

        elif record.operation == "place_component":
            # Remove the placed footprint
            fp_node = self._find_footprint(session._working_doc, record.target)
            if fp_node is not None:
                session._working_doc.root.children.remove(fp_node)

        elif record.operation == "create_net":
            # Remove the created net node
            net_name = record.target
            for net_node in session._working_doc.root.find_all("net"):
                vals = net_node.atom_values
                if len(vals) >= 2 and vals[1] == net_name:
                    session._working_doc.root.children.remove(net_node)
                    break

        elif record.operation == "delete_net":
            # Re-insert the deleted net
            if record.before_snapshot:
                restored = sexp_parse(record.before_snapshot)
                # Insert after last net
                insert_idx = 0
                for i, child in enumerate(session._working_doc.root.children):
                    if child.name == "net":
                        insert_idx = i + 1
                session._working_doc.root.children.insert(insert_idx, restored)

        elif record.operation == "assign_net":
            # Restore the pad to its before state
            ref, pad_num = record.target.split(":", 1)
            fp_node = self._find_footprint(session._working_doc, ref)
            if fp_node is not None:
                for pad_node in fp_node.find_all("pad"):
                    vals = pad_node.atom_values
                    if vals and vals[0] == pad_num:
                        before_pad = sexp_parse(record.before_snapshot)
                        idx = fp_node.children.index(pad_node)
                        fp_node.children[idx] = before_pad
                        break

        elif record.operation == "create_zone":
            # Remove the created zone by matching the after_snapshot
            after_str = record.after_snapshot
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "zone" and child.to_string() == after_str:
                    session._working_doc.root.children.pop(i)
                    break

        elif record.operation == "route_trace":
            # Remove the added segment by matching after_snapshot
            after_str = record.after_snapshot
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "segment" and child.to_string() == after_str:
                    session._working_doc.root.children.pop(i)
                    break

        elif record.operation == "add_via":
            # Remove the added via by matching after_snapshot
            after_str = record.after_snapshot
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "via" and child.to_string() == after_str:
                    session._working_doc.root.children.pop(i)
                    break

        elif record.operation in ("delete_trace", "delete_via"):
            # Re-insert the deleted segment/via
            if record.before_snapshot:
                restored = sexp_parse(record.before_snapshot)
                session._working_doc.root.children.append(restored)

        elif record.operation == "set_board_size":
            # Remove the new gr_lines and restore old ones
            to_remove = []
            for child in session._working_doc.root.children:
                if child.name == "gr_line":
                    layer_node = child.get("layer")
                    if layer_node and layer_node.first_value == "Edge.Cuts":
                        to_remove.append(child)
            for node in to_remove:
                session._working_doc.root.children.remove(node)
            if record.before_snapshot:
                for line_str in record.before_snapshot.split("\n"):
                    if line_str.strip():
                        session._working_doc.root.children.append(sexp_parse(line_str))

        elif record.operation == "add_board_outline":
            # Remove added outline segments by matching after_snapshot
            for line_str in record.after_snapshot.split("\n"):
                if line_str.strip():
                    for i, child in enumerate(session._working_doc.root.children):
                        if child.name == "gr_line" and child.to_string() == line_str:
                            session._working_doc.root.children.pop(i)
                            break
            # Restore previous Edge.Cuts lines if any
            if record.before_snapshot:
                for line_str in record.before_snapshot.split("\n"):
                    if line_str.strip():
                        session._working_doc.root.children.append(sexp_parse(line_str))

        elif record.operation == "add_mounting_hole":
            # Remove the added mounting hole footprint
            after_str = record.after_snapshot
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "footprint" and child.to_string() == after_str:
                    session._working_doc.root.children.pop(i)
                    break

        elif record.operation == "add_board_text":
            # Remove the added text
            after_str = record.after_snapshot
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "gr_text" and child.to_string() == after_str:
                    session._working_doc.root.children.pop(i)
                    break

        elif record.operation == "set_design_rules":
            # Restore setup section from before snapshot
            setup_node = session._working_doc.root.get("setup")
            if setup_node is not None and record.before_snapshot:
                before_node = sexp_parse(record.before_snapshot)
                idx = session._working_doc.root.children.index(setup_node)
                session._working_doc.root.children[idx] = before_node

        elif record.operation == "edit_component":
            # Replace entire footprint with before snapshot
            fp_node = self._find_footprint(session._working_doc, record.target)
            if fp_node is not None and record.before_snapshot:
                before_node = sexp_parse(record.before_snapshot)
                idx = session._working_doc.root.children.index(fp_node)
                session._working_doc.root.children[idx] = before_node

        elif record.operation == "replace_component":
            # Remove new footprint, restore old one
            fp_node = self._find_footprint(session._working_doc, record.target)
            if fp_node is not None:
                session._working_doc.root.children.remove(fp_node)
            if record.before_snapshot:
                session._working_doc.root.children.append(sexp_parse(record.before_snapshot))

        elif record.operation == "add_net_class":
            # Remove the added net class node
            after_str = record.after_snapshot
            # Check setup section first
            setup_node = session._working_doc.root.get("setup")
            removed = False
            if setup_node is not None:
                for i, child in enumerate(setup_node.children):
                    if child.name == "net_class" and child.to_string() == after_str:
                        setup_node.children.pop(i)
                        removed = True
                        break
            if not removed:
                for i, child in enumerate(session._working_doc.root.children):
                    if child.name == "net_class" and child.to_string() == after_str:
                        session._working_doc.root.children.pop(i)
                        break

        elif record.operation == "set_layer_constraints":
            # Restore setup section from before snapshot
            setup_node = session._working_doc.root.get("setup")
            if setup_node is not None and record.before_snapshot:
                before_node = sexp_parse(record.before_snapshot)
                idx = session._working_doc.root.children.index(setup_node)
                session._working_doc.root.children[idx] = before_node

    # ── Commit / Rollback ───────────────────────────────────────────

    def commit(self, session: Session) -> dict[str, Any]:
        """Commit all applied changes — write the modified board to disk.

        If the IPC backend is connected, changes are also pushed to KiCad
        GUI for instant visual feedback. The file write always happens
        regardless of IPC status (file is the source of truth).
        """
        self._require_active(session)
        assert session._working_doc is not None
        assert session._original_doc is not None

        applied = [c for c in session.changes if c.applied]
        if not applied:
            session.state = SessionState.COMMITTED
            return {"status": "committed", "changes_written": 0}

        # Try IPC push for live UI feedback (additive, not replacing file write)
        ipc_pushed = self._try_ipc_push(applied)

        # Always write to disk as the source of truth
        session._working_doc.save()
        session._original_doc.root = session._working_doc.root

        session.state = SessionState.COMMITTED
        result: dict[str, Any] = {
            "status": "committed",
            "changes_written": len(applied),
            "board_path": session.board_path,
        }
        if ipc_pushed > 0:
            result["ipc_pushed"] = ipc_pushed
        return result

    @staticmethod
    def _try_ipc_push(applied: list[ChangeRecord]) -> int:
        """Attempt to push applied changes to KiCad via IPC.

        Returns the number of changes successfully pushed, or 0 if IPC
        is not available.
        """
        try:
            from ..backends.ipc_api import IpcBackend
        except Exception:
            return 0

        ipc = IpcBackend.get()
        if not ipc.is_connected():
            return 0

        pushed = 0
        for change in applied:
            try:
                SessionManager._push_change_to_ipc(ipc, change)
                pushed += 1
            except Exception:
                pass  # IPC push is best-effort

        if pushed > 0:
            with contextlib.suppress(Exception):
                ipc.commit_to_undo()

        return pushed

    @staticmethod
    def _push_change_to_ipc(ipc: Any, change: ChangeRecord) -> None:
        """Push a single change to KiCad via IPC."""
        op = change.operation
        if op == "move_component":
            x, y = SessionManager._parse_at_coords(change.after_snapshot)
            if x is not None and y is not None:
                ipc.move_footprint(change.target, x, y)
        elif op == "rotate_component":
            parts = change.after_snapshot.strip("()").split()
            if len(parts) >= 4:
                angle = float(parts[3])
                ipc.rotate_footprint(change.target, angle)
        elif op == "delete_component":
            ipc.delete_footprint(change.target)

    @staticmethod
    def _parse_at_coords(snapshot: str) -> tuple[float | None, float | None]:
        """Extract x, y from an ``(at X Y ...)`` S-expression string."""
        stripped = snapshot.strip()
        if stripped.startswith("(at "):
            parts = stripped[1:-1].split()
            if len(parts) >= 3:
                try:
                    return float(parts[1]), float(parts[2])
                except ValueError:
                    pass
        return None, None

    def rollback(self, session: Session) -> dict[str, Any]:
        """Rollback all changes — discard the working copy."""
        self._require_active(session)
        session._working_doc = None
        session.state = SessionState.ROLLED_BACK
        return {
            "status": "rolled_back",
            "discarded_changes": len(session.changes),
        }

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _find_footprint(doc: Document, reference: str) -> SExp | None:
        """Find a footprint node by reference designator."""
        for fp_node in doc.root.find_all("footprint"):
            for prop in fp_node.find_all("property"):
                if prop.first_value == "Reference":
                    vals = prop.atom_values
                    if len(vals) > 1 and vals[1] == reference:
                        return fp_node
        return None

    @staticmethod
    def _deep_copy_doc(doc: Document) -> Document:
        """Create a deep copy of a Document for working changes."""
        new_root = sexp_parse(doc._raw_text)
        return Document(path=doc.path, root=new_root, raw_text=doc._raw_text)
