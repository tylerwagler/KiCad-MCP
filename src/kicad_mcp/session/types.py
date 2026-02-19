"""Core types and utilities for the session model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..sexp import SExp

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

# Display name → internal name mapping for KiCad layers.
_LAYER_ALIASES: dict[str, str] = {
    "F.Silkscreen": "F.SilkS",
    "B.Silkscreen": "B.SilkS",
    "F.Adhesive": "F.Adhes",
    "B.Adhesive": "B.Adhes",
    "F.Courtyard": "F.CrtYd",
    "B.Courtyard": "B.CrtYd",
    "User.Drawings": "Dwgs.User",
    "User.Comments": "Cmts.User",
    "User.Eco1": "Eco1.User",
    "User.Eco2": "Eco2.User",
}


def _normalize_layer(name: str) -> str:
    """Map display-name layer aliases to internal KiCad names."""
    return _LAYER_ALIASES.get(name, name)


class SessionState(Enum):
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ChangeRecord:
    """A single recorded change in a session."""

    change_id: str
    operation: str
    description: str
    target: str
    before_snapshot: str
    after_snapshot: str
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
    _original_doc: Any | None = field(default=None, repr=False)
    _working_doc: Any | None = field(default=None, repr=False)

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


def require_active(session: Session) -> None:
    """Raise if session is not active."""
    if session.state != SessionState.ACTIVE:
        raise RuntimeError(f"Session {session.session_id} is {session.state.value}, not active")
