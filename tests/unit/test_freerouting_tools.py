"""Tests for the Freerouting tool handlers (check / export_dsn / import_ses / autoroute)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import kicad_mcp.tools  # noqa: F401 — registers tools
from kicad_mcp.backends import freerouting
from kicad_mcp.schema.extract import extract_segments
from kicad_mcp.sexp import Document
from kicad_mcp.tools.freerouting import (
    _autoroute_freerouting_handler,
    _check_freerouting_handler,
    _export_dsn_handler,
    _import_ses_handler,
)
from kicad_mcp.tools.mutation import _get_manager

FIXTURES = Path(__file__).parent.parent / "fixtures"
BOARD = FIXTURES / "minimal_board.kicad_pcb"
SES = FIXTURES / "minimal_board.ses"

pytestmark = pytest.mark.skipif(not BOARD.exists(), reason="Board fixture not available")

# Only run the live-router integration test against a locally runnable jar/native
# runtime — a mere `docker` binary can't pull the image offline, so don't gate on it.
_rt = freerouting.find_runtime()
_have_runnable_fr = _rt is not None and _rt.kind in ("jar", "native")
needs_freerouting = pytest.mark.skipif(
    not _have_runnable_fr, reason="No locally runnable Freerouting (jar/native)"
)


def _new_session(tmp_path: Path) -> tuple[str, object, Path]:
    board = tmp_path / "b.kicad_pcb"
    shutil.copy(BOARD, board)
    mgr = _get_manager()
    session = mgr.start_session(Document.load(board))
    return session.session_id, mgr, board


class TestCheckFreerouting:
    def test_returns_availability(self) -> None:
        out = _check_freerouting_handler()
        assert "available" in out
        assert isinstance(out["available"], bool)


class TestExportDsn:
    def test_export_from_session(self, tmp_path: Path) -> None:
        sid, _, _ = _new_session(tmp_path)
        out_path = tmp_path / "board.dsn"
        out = _export_dsn_handler(str(out_path), session_id=sid)
        assert out["status"] == "exported"
        assert out_path.exists()
        assert "(pcb" in out_path.read_text()

    def test_export_unknown_session(self, tmp_path: Path) -> None:
        out = _export_dsn_handler(str(tmp_path / "x.dsn"), session_id="nope")
        assert "error" in out


@pytest.mark.skipif(not SES.exists(), reason="SES fixture not available")
class TestImportSes:
    def test_import_applies_traces(self, tmp_path: Path) -> None:
        sid, mgr, board = _new_session(tmp_path)
        out = _import_ses_handler(sid, str(SES))
        assert out["status"] == "imported"
        assert out["traces_added"] == 16
        assert out["calibrated_units_per_mm"] == 100000.0
        assert out["skipped_nets"] == []

        # Commit and confirm the routed segments landed on disk.
        session = mgr.get_session(sid)
        mgr.commit(session)
        segs = extract_segments(Document.load(board))
        assert len(segs) >= 17  # 1 pre-existing + 16 routed

    def test_import_missing_file(self, tmp_path: Path) -> None:
        sid, _, _ = _new_session(tmp_path)
        out = _import_ses_handler(sid, str(tmp_path / "absent.ses"))
        assert "error" in out

    def test_import_is_undoable(self, tmp_path: Path) -> None:
        sid, mgr, _ = _new_session(tmp_path)
        _import_ses_handler(sid, str(SES))
        session = mgr.get_session(sid)
        before = len([c for c in session.changes if c.applied])
        mgr.undo(session)
        after = len([c for c in session.changes if c.applied])
        assert after == before - 1


class TestAutorouteFreerouting:
    def test_no_runtime_reports_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(freerouting, "is_available", lambda: False)
        monkeypatch.setattr(freerouting, "find_runtime", lambda: None)
        sid, _, _ = _new_session(tmp_path)
        out = _autoroute_freerouting_handler(sid)
        assert "error" in out
        assert "not available" in out["error"]

    @needs_freerouting
    def test_full_autoroute_apply(self, tmp_path: Path) -> None:
        sid, mgr, board = _new_session(tmp_path)
        out = _autoroute_freerouting_handler(sid, apply=True, max_passes=5, timeout=180)
        assert out["status"] == "applied"
        assert out["traces_added"] > 0
        session = mgr.get_session(sid)
        mgr.commit(session)
        assert len(extract_segments(Document.load(board))) > 1
