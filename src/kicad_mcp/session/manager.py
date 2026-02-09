"""Session and transaction model for safe board mutations.

Provides a query-before-commit pattern:
  start_session → query_move (preview) → apply_move → undo → commit/rollback

The LLM can preview changes before writing to disk, and undo individual
operations or rollback the entire session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..sexp import Document, SExp


class SessionState(Enum):
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ChangeRecord:
    """A single recorded change in a session."""

    change_id: str
    operation: str  # e.g., "move_component", "delete_footprint", "add_trace"
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

    def query_move(
        self,
        session: Session,
        reference: str,
        x: float,
        y: float,
    ) -> dict[str, Any]:
        """Preview moving a component without applying the change.

        Returns a description of what would change.
        """
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

        # Apply the change
        if at_node is not None and len(at_node.children) >= 2:
            at_node.children[0] = SExp(value=str(x), _original_str=str(x))
            at_node.children[1] = SExp(value=str(y), _original_str=str(y))

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

    def undo(self, session: Session) -> ChangeRecord | None:
        """Undo the last applied change in the session."""
        self._require_active(session)
        assert session._working_doc is not None

        # Find the last applied change
        for record in reversed(session.changes):
            if record.applied:
                # Restore the before state
                if record.operation == "move_component":
                    fp_node = self._find_footprint(session._working_doc, record.target)
                    if fp_node is not None:
                        # Parse the before snapshot to get original position
                        from ..sexp.parser import parse

                        before_node = parse(record.before_snapshot)
                        at_node = fp_node.get("at")
                        if at_node and before_node:
                            at_node.children = before_node.children[:]

                record.applied = False
                return record
        return None

    def commit(self, session: Session) -> dict[str, Any]:
        """Commit all applied changes — write the modified board to disk."""
        self._require_active(session)
        assert session._working_doc is not None
        assert session._original_doc is not None

        applied = [c for c in session.changes if c.applied]
        if not applied:
            session.state = SessionState.COMMITTED
            return {"status": "committed", "changes_written": 0}

        # Write the working document to disk
        session._working_doc.save()

        # Update the original document reference
        session._original_doc.root = session._working_doc.root

        session.state = SessionState.COMMITTED
        return {
            "status": "committed",
            "changes_written": len(applied),
            "board_path": session.board_path,
        }

    def rollback(self, session: Session) -> dict[str, Any]:
        """Rollback all changes — discard the working copy."""
        self._require_active(session)
        session._working_doc = None
        session.state = SessionState.ROLLED_BACK
        return {
            "status": "rolled_back",
            "discarded_changes": len(session.changes),
        }

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
        # Re-parse from the original text to get a clean copy
        from ..sexp.parser import parse

        new_root = parse(doc._raw_text)
        return Document(path=doc.path, root=new_root, raw_text=doc._raw_text)
