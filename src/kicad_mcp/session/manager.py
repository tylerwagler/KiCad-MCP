"""Session and transaction model for safe board mutations.

Provides a query-before-commit pattern:
  start_session → query_move (preview) → apply_move → undo → commit/rollback

The LLM can preview changes before writing to disk, and undo individual
operations or rollback the entire session.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from ..sexp import Document
from ..sexp.parser import parse as sexp_parse
from . import board_setup_ops, ipc_ops, net_zone_ops, placement_ops, routing_ops
from .helpers import deep_copy_doc, find_footprint
from .types import ChangeRecord, Session, SessionState, require_active

# Re-export public types
__all__ = ["ChangeRecord", "Session", "SessionManager", "SessionState"]


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
        self._lock = threading.Lock()

    def start_session(self, doc: Document) -> Session:
        """Start a new mutation session for the given document."""
        session_id = str(uuid.uuid4())[:8]
        session = Session(
            session_id=session_id,
            board_path=str(doc.path),
            _original_doc=doc,
            _working_doc=deep_copy_doc(doc),
        )
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session:
        """Get a session by ID."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"No session with ID {session_id!r}")
            return self._sessions[session_id]

    def _require_active(self, session: Session) -> None:
        require_active(session)

    # ── Placement delegates ────────────────────────────────────────

    def query_move(self, session: Session, reference: str, x: float, y: float) -> dict[str, Any]:
        return placement_ops.query_move(session, reference, x, y)

    def apply_move(self, session: Session, reference: str, x: float, y: float) -> ChangeRecord:
        return placement_ops.apply_move(session, reference, x, y)

    def apply_rotate(self, session: Session, reference: str, angle: float) -> ChangeRecord:
        return placement_ops.apply_rotate(session, reference, angle)

    def apply_flip(self, session: Session, reference: str) -> ChangeRecord:
        return placement_ops.apply_flip(session, reference)

    def apply_delete(self, session: Session, reference: str) -> ChangeRecord:
        return placement_ops.apply_delete(session, reference)

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
        return placement_ops.apply_place(session, footprint_library, reference, value, x, y, layer)

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
        return placement_ops.place_from_kicad_mod(
            session, kicad_mod_path, reference, value, x, y, layer
        )

    # ── Net/Zone delegates ─────────────────────────────────────────

    def apply_create_net(self, session: Session, net_name: str) -> ChangeRecord:
        return net_zone_ops.apply_create_net(session, net_name)

    def apply_delete_net(self, session: Session, net_name: str) -> ChangeRecord:
        return net_zone_ops.apply_delete_net(session, net_name)

    def apply_assign_net(
        self, session: Session, reference: str, pad_number: str, net_name: str
    ) -> ChangeRecord:
        return net_zone_ops.apply_assign_net(session, reference, pad_number, net_name)

    def apply_create_zone(
        self,
        session: Session,
        net_name: str,
        layer: str,
        points: list[tuple[float, float]],
        min_thickness: float = 0.25,
        priority: int = 0,
    ) -> ChangeRecord:
        return net_zone_ops.apply_create_zone(
            session, net_name, layer, points, min_thickness, priority
        )

    # ── Routing delegates ──────────────────────────────────────────

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
        return routing_ops.apply_route_trace(
            session, start_x, start_y, end_x, end_y, width, layer, net_number
        )

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
        return routing_ops.apply_add_via(session, x, y, net_number, size, drill, layers)

    def apply_delete_trace(self, session: Session, segment_uuid: str) -> ChangeRecord:
        return routing_ops.apply_delete_trace(session, segment_uuid)

    def apply_delete_via(self, session: Session, via_uuid: str) -> ChangeRecord:
        return routing_ops.apply_delete_via(session, via_uuid)

    def get_ratsnest(self, session: Session) -> list[dict[str, Any]]:
        return routing_ops.get_ratsnest(session)

    # ── Board setup delegates ──────────────────────────────────────

    def apply_set_board_size(self, session: Session, width: float, height: float) -> ChangeRecord:
        return board_setup_ops.apply_set_board_size(session, width, height)

    def apply_add_board_outline(
        self, session: Session, points: list[tuple[float, float]]
    ) -> ChangeRecord:
        return board_setup_ops.apply_add_board_outline(session, points)

    def apply_add_mounting_hole(
        self,
        session: Session,
        x: float,
        y: float,
        drill: float = 3.2,
        pad_dia: float = 6.0,
    ) -> ChangeRecord:
        return board_setup_ops.apply_add_mounting_hole(session, x, y, drill, pad_dia)

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
        return board_setup_ops.apply_add_board_text(session, text, x, y, layer, size, angle)

    def apply_set_design_rules(self, session: Session, rules: dict[str, float]) -> ChangeRecord:
        return board_setup_ops.apply_set_design_rules(session, rules)

    def apply_edit_component(
        self, session: Session, reference: str, properties: dict[str, str]
    ) -> ChangeRecord:
        return board_setup_ops.apply_edit_component(session, reference, properties)

    def apply_replace_component(
        self, session: Session, reference: str, new_library: str, new_value: str
    ) -> ChangeRecord:
        return board_setup_ops.apply_replace_component(session, reference, new_library, new_value)

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
        return board_setup_ops.apply_add_net_class(
            session, name, clearance, trace_width, via_dia, via_drill, nets
        )

    def apply_set_layer_constraints(
        self,
        session: Session,
        layer: str,
        min_width: float | None = None,
        min_clearance: float | None = None,
    ) -> ChangeRecord:
        return board_setup_ops.apply_set_layer_constraints(session, layer, min_width, min_clearance)

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

        # Reverse in IPC GUI first (best-effort)
        ipc_ops.reverse_ipc_changes([record])

        if record.operation in ("move_component", "rotate_component"):
            fp_node = find_footprint(session._working_doc, record.target)
            if fp_node is not None:
                before_node = sexp_parse(record.before_snapshot)
                at_node = fp_node.get("at")
                if at_node and before_node:
                    at_node.children = before_node.children[:]

        elif record.operation == "flip_component":
            fp_node = find_footprint(session._working_doc, record.target)
            if fp_node is not None:
                before_node = sexp_parse(record.before_snapshot)
                idx = session._working_doc.root.children.index(fp_node)
                session._working_doc.root.children[idx] = before_node

        elif record.operation == "delete_component":
            if record.before_snapshot:
                restored = sexp_parse(record.before_snapshot)
                session._working_doc.root.children.append(restored)

        elif record.operation == "place_component":
            fp_node = find_footprint(session._working_doc, record.target)
            if fp_node is not None:
                session._working_doc.root.children.remove(fp_node)

        elif record.operation == "create_net":
            net_name = record.target
            for net_node in session._working_doc.root.find_all("net"):
                vals = net_node.atom_values
                if len(vals) >= 2 and vals[1] == net_name:
                    session._working_doc.root.children.remove(net_node)
                    break

        elif record.operation == "delete_net":
            if record.before_snapshot:
                restored = sexp_parse(record.before_snapshot)
                insert_idx = 0
                for i, child in enumerate(session._working_doc.root.children):
                    if child.name == "net":
                        insert_idx = i + 1
                session._working_doc.root.children.insert(insert_idx, restored)

        elif record.operation == "assign_net":
            ref, pad_num = record.target.split(":", 1)
            fp_node = find_footprint(session._working_doc, ref)
            if fp_node is not None:
                for pad_node in fp_node.find_all("pad"):
                    vals = pad_node.atom_values
                    if vals and vals[0] == pad_num:
                        before_pad = sexp_parse(record.before_snapshot)
                        idx = fp_node.children.index(pad_node)
                        fp_node.children[idx] = before_pad
                        break

        elif record.operation == "create_zone":
            after_str = record.after_snapshot
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "zone" and child.to_string() == after_str:
                    session._working_doc.root.children.pop(i)
                    break

        elif record.operation == "route_trace":
            after_str = record.after_snapshot
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "segment" and child.to_string() == after_str:
                    session._working_doc.root.children.pop(i)
                    break

        elif record.operation == "add_via":
            after_str = record.after_snapshot
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "via" and child.to_string() == after_str:
                    session._working_doc.root.children.pop(i)
                    break

        elif record.operation in ("delete_trace", "delete_via"):
            if record.before_snapshot:
                restored = sexp_parse(record.before_snapshot)
                session._working_doc.root.children.append(restored)

        elif record.operation == "set_board_size":
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
            for line_str in record.after_snapshot.split("\n"):
                if line_str.strip():
                    for i, child in enumerate(session._working_doc.root.children):
                        if child.name == "gr_line" and child.to_string() == line_str:
                            session._working_doc.root.children.pop(i)
                            break
            if record.before_snapshot:
                for line_str in record.before_snapshot.split("\n"):
                    if line_str.strip():
                        session._working_doc.root.children.append(sexp_parse(line_str))

        elif record.operation == "add_mounting_hole":
            after_str = record.after_snapshot
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "footprint" and child.to_string() == after_str:
                    session._working_doc.root.children.pop(i)
                    break

        elif record.operation == "add_board_text":
            after_str = record.after_snapshot
            for i, child in enumerate(session._working_doc.root.children):
                if child.name == "gr_text" and child.to_string() == after_str:
                    session._working_doc.root.children.pop(i)
                    break

        elif record.operation == "set_design_rules":
            setup_node = session._working_doc.root.get("setup")
            if setup_node is not None and record.before_snapshot:
                before_node = sexp_parse(record.before_snapshot)
                idx = session._working_doc.root.children.index(setup_node)
                session._working_doc.root.children[idx] = before_node

        elif record.operation == "edit_component":
            fp_node = find_footprint(session._working_doc, record.target)
            if fp_node is not None and record.before_snapshot:
                before_node = sexp_parse(record.before_snapshot)
                idx = session._working_doc.root.children.index(fp_node)
                session._working_doc.root.children[idx] = before_node

        elif record.operation == "replace_component":
            fp_node = find_footprint(session._working_doc, record.target)
            if fp_node is not None:
                session._working_doc.root.children.remove(fp_node)
            if record.before_snapshot:
                session._working_doc.root.children.append(sexp_parse(record.before_snapshot))

        elif record.operation == "add_net_class":
            after_str = record.after_snapshot
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
            setup_node = session._working_doc.root.get("setup")
            if setup_node is not None and record.before_snapshot:
                before_node = sexp_parse(record.before_snapshot)
                idx = session._working_doc.root.children.index(setup_node)
                session._working_doc.root.children[idx] = before_node

    # ── Commit / Rollback ───────────────────────────────────────────

    def commit(self, session: Session) -> dict[str, Any]:
        """Commit all applied changes — write the modified board to disk."""
        self._require_active(session)
        assert session._working_doc is not None
        assert session._original_doc is not None

        with self._lock:
            applied = [c for c in session.changes if c.applied]
            if not applied:
                session.state = SessionState.COMMITTED
                return {"status": "committed", "changes_written": 0}

        ipc_pushed = ipc_ops.try_ipc_push(applied)

        session._working_doc.save()
        session._original_doc.root = session._working_doc.root

        with self._lock:
            session.state = SessionState.COMMITTED
            result: dict[str, Any] = {
                "status": "committed",
                "changes_written": len(applied),
                "board_path": session.board_path,
            }
            ipc_pushed_val = ipc_pushed
        if ipc_pushed_val > 0:
            result["ipc_pushed"] = ipc_pushed_val
        return result

    def rollback(self, session: Session) -> dict[str, Any]:
        """Rollback all changes — discard the working copy."""
        self._require_active(session)

        with self._lock:
            applied = [c for c in session.changes if c.applied]
            changes_len = len(session.changes)

        ipc_reversed = ipc_ops.reverse_ipc_changes(applied)

        session._working_doc = None
        with self._lock:
            session.state = SessionState.ROLLED_BACK
            result: dict[str, Any] = {
                "status": "rolled_back",
                "discarded_changes": changes_len,
            }
            ipc_rev = ipc_reversed
        if ipc_rev > 0:
            result["ipc_reversed"] = ipc_rev
        return result

    # ── Static helpers (kept for backward compat) ──────────────────

    @staticmethod
    def _find_footprint(doc: Document, reference: str) -> Any:
        return find_footprint(doc, reference)

    @staticmethod
    def _deep_copy_doc(doc: Document) -> Document:
        return deep_copy_doc(doc)
