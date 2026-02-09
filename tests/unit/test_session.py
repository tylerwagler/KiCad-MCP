"""Tests for the session/transaction model."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.session import SessionManager, SessionState
from kicad_mcp.sexp import Document

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")


@pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
class TestSessionManager:
    @pytest.fixture()
    def doc(self) -> Document:
        return Document.load(BLINKY_PATH)

    @pytest.fixture()
    def mgr(self) -> SessionManager:
        return SessionManager()

    def test_start_session(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        assert session.state == SessionState.ACTIVE
        assert session.session_id
        assert len(session.changes) == 0

    def test_query_move(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        preview = mgr.query_move(session, "C7", x=20.0, y=10.0)
        assert preview["operation"] == "move_component"
        assert preview["preview"] is True
        assert preview["current_position"]["x"] == 14.0
        assert preview["new_position"]["x"] == 20.0

    def test_query_move_not_found(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        result = mgr.query_move(session, "Z99", x=0, y=0)
        assert "error" in result

    def test_apply_move(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        record = mgr.apply_move(session, "C7", x=20.0, y=10.0)
        assert record.applied is True
        assert record.operation == "move_component"
        assert record.target == "C7"
        assert len(session.changes) == 1

    def test_undo_move(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        mgr.apply_move(session, "C7", x=20.0, y=10.0)

        # Verify the move was applied
        preview_after = mgr.query_move(session, "C7", x=0, y=0)
        assert preview_after["current_position"]["x"] == 20.0

        # Undo
        undone = mgr.undo(session)
        assert undone is not None
        assert undone.applied is False

        # Verify the position is restored
        preview_restored = mgr.query_move(session, "C7", x=0, y=0)
        assert preview_restored["current_position"]["x"] == 14.0

    def test_undo_nothing(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        result = mgr.undo(session)
        assert result is None

    def test_multiple_moves_and_undo(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        mgr.apply_move(session, "C7", x=20.0, y=10.0)
        mgr.apply_move(session, "C7", x=30.0, y=15.0)
        assert len(session.changes) == 2

        # Undo last move
        mgr.undo(session)
        preview = mgr.query_move(session, "C7", x=0, y=0)
        assert preview["current_position"]["x"] == 20.0

    def test_rollback(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        mgr.apply_move(session, "C7", x=20.0, y=10.0)
        result = mgr.rollback(session)
        assert result["status"] == "rolled_back"
        assert session.state == SessionState.ROLLED_BACK

    def test_commit_no_changes(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        result = mgr.commit(session)
        assert result["status"] == "committed"
        assert result["changes_written"] == 0
        assert session.state == SessionState.COMMITTED

    def test_cannot_modify_after_commit(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        mgr.commit(session)
        with pytest.raises(RuntimeError, match="not active"):
            mgr.apply_move(session, "C7", x=0, y=0)

    def test_cannot_modify_after_rollback(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        mgr.rollback(session)
        with pytest.raises(RuntimeError, match="not active"):
            mgr.apply_move(session, "C7", x=0, y=0)

    def test_session_to_dict(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        mgr.apply_move(session, "C7", x=20.0, y=10.0)
        d = session.to_dict()
        assert d["state"] == "active"
        assert d["change_count"] == 1
        assert len(d["changes"]) == 1

    def test_get_session(self, mgr: SessionManager, doc: Document) -> None:
        session = mgr.start_session(doc)
        retrieved = mgr.get_session(session.session_id)
        assert retrieved is session

    def test_get_session_not_found(self, mgr: SessionManager) -> None:
        with pytest.raises(KeyError):
            mgr.get_session("nonexistent")


@pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
class TestMutationToolHandlers:
    """Test the registered mutation tool handlers."""

    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_start_and_query_flow(self) -> None:
        # Reset module-level manager
        import kicad_mcp.tools.mutation as mod
        from kicad_mcp.tools import TOOL_REGISTRY

        mod._session_manager = None

        # Start session
        result = TOOL_REGISTRY["start_session"].handler()
        assert result["status"] == "session_started"
        sid = result["session_id"]

        # Query move
        preview = TOOL_REGISTRY["query_move"].handler(
            session_id=sid, reference="C7", x=25.0, y=12.0
        )
        assert preview["preview"] is True

        # Apply move
        applied = TOOL_REGISTRY["apply_move"].handler(
            session_id=sid, reference="C7", x=25.0, y=12.0
        )
        assert applied["status"] == "applied"

        # Get status
        status = TOOL_REGISTRY["get_session_status"].handler(session_id=sid)
        assert status["change_count"] == 1

        # Undo
        undone = TOOL_REGISTRY["undo_change"].handler(session_id=sid)
        assert undone["status"] == "undone"

        # Rollback
        rolled = TOOL_REGISTRY["rollback_session"].handler(session_id=sid)
        assert rolled["status"] == "rolled_back"
