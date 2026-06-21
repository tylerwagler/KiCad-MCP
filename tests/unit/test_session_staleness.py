"""Regression tests for session staleness clobbering prior commits (P2).

start_session used to snapshot the in-memory board, not disk. Committing, then
starting another session without re-opening, based the new session on the stale
pre-commit board — and its commit silently reverted the previous commit.
"""

from __future__ import annotations

from pathlib import Path

from kicad_mcp import state
from kicad_mcp.tools import TOOL_REGISTRY
from kicad_mcp.tools.project import _minimal_kicad_pcb


def _open_board(tmp_path: Path) -> Path:
    board = tmp_path / "b.kicad_pcb"
    board.write_text(_minimal_kicad_pcb(100, 80))
    state.load_board(str(board))
    return board


def _add_text(sid: str, text: str) -> dict:
    return TOOL_REGISTRY["add_board_text"].handler(session_id=sid, text=text, x=10, y=10)


def _start() -> str:
    return TOOL_REGISTRY["start_session"].handler()["session_id"]


def _commit(sid: str, force: bool = False) -> dict:
    return TOOL_REGISTRY["commit_session"].handler(session_id=sid, force=force)


class TestSequentialCommitsDoNotClobber:
    def test_second_session_sees_first_commit(self, tmp_path):
        board = _open_board(tmp_path)

        sid1 = _start()
        _add_text(sid1, "FIRST")
        assert _commit(sid1)["status"] == "committed"

        # New session WITHOUT re-opening — must build on the committed board.
        sid2 = _start()
        _add_text(sid2, "SECOND")
        assert _commit(sid2)["status"] == "committed"

        on_disk = board.read_text()
        assert "FIRST" in on_disk  # not reverted by the second commit
        assert "SECOND" in on_disk


class TestStaleGuard:
    def test_overlapping_session_commit_is_refused(self, tmp_path):
        _open_board(tmp_path)

        # Two sessions opened from the same base board.
        sid1 = _start()
        sid2 = _start()
        _add_text(sid1, "ALPHA")
        _add_text(sid2, "BETA")

        assert _commit(sid1)["status"] == "committed"
        # sid2's base board is now stale on disk — refuse rather than revert ALPHA.
        stale = _commit(sid2)
        assert stale["status"] == "stale"
        assert "force" in stale["error"]

    def test_force_overrides_stale_guard(self, tmp_path):
        board = _open_board(tmp_path)

        sid1 = _start()
        sid2 = _start()
        _add_text(sid1, "ALPHA")
        _add_text(sid2, "BETA")
        _commit(sid1)
        assert _commit(sid2, force=True)["status"] == "committed"
        # force overwrites: BETA lands (ALPHA is intentionally clobbered).
        assert "BETA" in board.read_text()

    def test_noop_commit_not_flagged_stale(self, tmp_path):
        _open_board(tmp_path)
        sid1 = _start()
        sid2 = _start()
        _add_text(sid1, "ALPHA")
        _commit(sid1)
        # sid2 made no changes — committing nothing can't clobber anything.
        assert _commit(sid2)["status"] == "committed"
