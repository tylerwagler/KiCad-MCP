"""Integration tests for session-based mutation workflows.

These tests exercise the full flow through tool handlers:
  open_project -> start_session -> mutate -> commit_session -> verify on disk

Tests that need the blinky board fixture are skipped in CI.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from kicad_mcp.sexp import Document

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")

skip_no_board = pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")

# Check for KiCad libraries (needed for library-resolved placement)
_RESISTOR_MOD = Path(
    r"C:\Program Files\KiCad\9.0\share\kicad\footprints"
    r"\Resistor_SMD.pretty\R_0402_1005Metric.kicad_mod"
)
skip_no_libs = pytest.mark.skipif(
    not _RESISTOR_MOD.exists(), reason="KiCad footprint libraries not installed"
)


def _copy_board_to_tmp(tmpdir: str) -> str:
    """Copy the blinky board to a temp directory for safe mutation."""
    dest = str(Path(tmpdir) / "blinky.kicad_pcb")
    shutil.copy2(str(BLINKY_PATH), dest)
    return dest


@skip_no_board
class TestMoveCommitWorkflow:
    """Open board -> start session -> move component -> commit -> verify file."""

    def test_move_and_commit_persists(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            # Start session
            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            # Move C7
            TOOL_REGISTRY["apply_move"].handler(session_id=sid, reference="C7", x=99.0, y=88.0)

            # Commit
            result = TOOL_REGISTRY["commit_session"].handler(session_id=sid)
            assert result["status"] == "committed"

            # Re-read from disk and verify
            doc = Document.load(board_path)
            for fp in doc.root.find_all("footprint"):
                for prop in fp.find_all("property"):
                    if prop.first_value == "Reference" and prop.atom_values[1] == "C7":
                        at = fp.get("at")
                        assert float(at.atom_values[0]) == 99.0
                        assert float(at.atom_values[1]) == 88.0
                        return
            pytest.fail("C7 not found after commit")


@skip_no_board
class TestRollbackWorkflow:
    """Verify rollback discards changes — file remains unchanged."""

    def test_rollback_preserves_original(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            original_text = Path(board_path).read_text(encoding="utf-8")
            state.load_board(board_path)

            # Start session and make a change
            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]
            TOOL_REGISTRY["apply_move"].handler(session_id=sid, reference="C7", x=999.0, y=999.0)

            # Rollback
            result = TOOL_REGISTRY["rollback_session"].handler(session_id=sid)
            assert result["status"] == "rolled_back"

            # File should be unchanged
            after_text = Path(board_path).read_text(encoding="utf-8")
            assert after_text == original_text


@skip_no_board
class TestMultiOperationSession:
    """Multiple operations in a single session, then commit."""

    def test_place_move_rotate_commit(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            # Place a new component
            TOOL_REGISTRY["place_component"].handler(
                session_id=sid,
                footprint_library="Custom:TestPart",
                reference="X99",
                value="test",
                x=10,
                y=10,
            )

            # Move an existing component
            TOOL_REGISTRY["apply_move"].handler(session_id=sid, reference="C7", x=50.0, y=50.0)

            # Rotate another
            TOOL_REGISTRY["rotate_component"].handler(session_id=sid, reference="R2", angle=45.0)

            # Commit all three
            result = TOOL_REGISTRY["commit_session"].handler(session_id=sid)
            assert result["status"] == "committed"
            assert result["changes_written"] == 3

            # Verify on disk
            doc = Document.load(board_path)
            refs = []
            for fp in doc.root.find_all("footprint"):
                for prop in fp.find_all("property"):
                    if prop.first_value == "Reference":
                        refs.append(prop.atom_values[1])
            assert "X99" in refs


@skip_no_board
class TestUndoCommitWorkflow:
    """Undo within a session, then commit the remaining changes."""

    def test_undo_then_commit(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            # Get original C7 position
            doc_before = Document.load(board_path)
            for fp in doc_before.root.find_all("footprint"):
                for prop in fp.find_all("property"):
                    if prop.first_value == "Reference" and prop.atom_values[1] == "C7":
                        pass  # Just verifying C7 exists

            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            # Move C7 to new position
            TOOL_REGISTRY["apply_move"].handler(session_id=sid, reference="C7", x=99.0, y=88.0)

            # Move R2 to new position
            TOOL_REGISTRY["apply_move"].handler(session_id=sid, reference="R2", x=77.0, y=66.0)

            # Undo the R2 move (last operation)
            TOOL_REGISTRY["undo_change"].handler(session_id=sid)

            # Commit — only the C7 move should persist
            TOOL_REGISTRY["commit_session"].handler(session_id=sid)

            doc_after = Document.load(board_path)
            for fp in doc_after.root.find_all("footprint"):
                for prop in fp.find_all("property"):
                    if prop.first_value == "Reference" and prop.atom_values[1] == "C7":
                        at = fp.get("at")
                        assert float(at.atom_values[0]) == 99.0
                        assert float(at.atom_values[1]) == 88.0
                    elif prop.first_value == "Reference" and prop.atom_values[1] == "R2":
                        # R2 should NOT be at 77, 66 (that was undone)
                        at = fp.get("at")
                        assert float(at.atom_values[0]) != 77.0


@skip_no_board
class TestBoardSetupIntegration:
    """Integration tests for board setup operations through tool handlers."""

    def test_set_board_size_commit(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            TOOL_REGISTRY["set_board_size"].handler(session_id=sid, width=120.0, height=80.0)
            TOOL_REGISTRY["commit_session"].handler(session_id=sid)

            # Verify Edge.Cuts lines on disk
            doc = Document.load(board_path)
            edge_lines = [
                c
                for c in doc.root.children
                if c.name == "gr_line"
                and c.get("layer")
                and c.get("layer").first_value == "Edge.Cuts"
            ]
            assert len(edge_lines) == 4

    def test_add_text_commit(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            TOOL_REGISTRY["add_board_text"].handler(session_id=sid, text="Rev 1.0", x=5.0, y=5.0)
            TOOL_REGISTRY["commit_session"].handler(session_id=sid)

            doc = Document.load(board_path)
            texts = doc.root.find_all("gr_text")
            found = any(t.first_value == "Rev 1.0" for t in texts)
            assert found

    def test_set_design_rules_commit(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            TOOL_REGISTRY["set_design_rules"].handler(
                session_id=sid,
                rules={"min_track_width": 0.2},
            )
            TOOL_REGISTRY["commit_session"].handler(session_id=sid)

            doc = Document.load(board_path)
            setup = doc.root.get("setup")
            assert setup is not None


@skip_no_board
class TestNetZoneIntegration:
    """Integration tests for net/zone operations."""

    def test_create_net_and_zone_commit(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            # Create a net
            TOOL_REGISTRY["create_net"].handler(session_id=sid, net_name="TEST_NET")

            # Create a zone on that net
            TOOL_REGISTRY["create_zone"].handler(
                session_id=sid,
                net_name="TEST_NET",
                layer="F.Cu",
                points=[[0, 0], [10, 0], [10, 10], [0, 10]],
            )

            TOOL_REGISTRY["commit_session"].handler(session_id=sid)

            doc = Document.load(board_path)
            # Verify net exists
            net_names = []
            for net in doc.root.find_all("net"):
                vals = net.atom_values
                if len(vals) >= 2:
                    net_names.append(vals[1])
            assert "TEST_NET" in net_names

            # Verify zone exists
            zones = doc.root.find_all("zone")
            assert len(zones) > 0


@skip_no_board
class TestRoutingIntegration:
    """Integration tests for trace routing operations."""

    def test_route_trace_and_via_commit(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            # Count existing segments
            doc_before = Document.load(board_path)
            seg_before = len(doc_before.root.find_all("segment"))

            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            TOOL_REGISTRY["route_trace"].handler(
                session_id=sid,
                start_x=10.0,
                start_y=10.0,
                end_x=20.0,
                end_y=10.0,
                width=0.25,
                layer="F.Cu",
                net_number=1,
            )

            TOOL_REGISTRY["add_via"].handler(
                session_id=sid,
                x=20.0,
                y=10.0,
                net_number=1,
            )

            TOOL_REGISTRY["commit_session"].handler(session_id=sid)

            doc_after = Document.load(board_path)
            seg_after = len(doc_after.root.find_all("segment"))
            via_count = len(doc_after.root.find_all("via"))

            assert seg_after == seg_before + 1
            assert via_count >= 1


@skip_no_board
@skip_no_libs
class TestPlaceWithLibraryIntegration:
    """Integration test: place from library, commit, verify pads on disk."""

    def test_place_from_library_commit_has_pads(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            TOOL_REGISTRY["place_component"].handler(
                session_id=sid,
                footprint_library="Resistor_SMD:R_0402_1005Metric",
                reference="R99",
                value="10k",
                x=30.0,
                y=30.0,
            )

            TOOL_REGISTRY["commit_session"].handler(session_id=sid)

            # Re-read from disk and verify pads exist
            doc = Document.load(board_path)
            for fp in doc.root.find_all("footprint"):
                for prop in fp.find_all("property"):
                    if prop.first_value == "Reference" and prop.atom_values[1] == "R99":
                        pads = fp.find_all("pad")
                        assert len(pads) >= 2, f"Expected pads on R99, got {len(pads)}"
                        return
            pytest.fail("R99 not found on disk after commit")


@skip_no_board
class TestEditReplaceIntegration:
    """Integration tests for edit/replace component operations."""

    def test_edit_component_commit(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            TOOL_REGISTRY["edit_component"].handler(
                session_id=sid,
                reference="C7",
                properties={"Value": "22uF"},
            )

            TOOL_REGISTRY["commit_session"].handler(session_id=sid)

            doc = Document.load(board_path)
            for fp in doc.root.find_all("footprint"):
                for prop in fp.find_all("property"):
                    if prop.first_value == "Reference" and prop.atom_values[1] == "C7":
                        for vp in fp.find_all("property"):
                            if vp.first_value == "Value":
                                assert vp.atom_values[1] == "22uF"
                                return
            pytest.fail("C7 value not updated on disk")

    def test_delete_component_commit(self) -> None:
        from kicad_mcp import state
        from kicad_mcp.tools import TOOL_REGISTRY

        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = _copy_board_to_tmp(tmpdir)
            state.load_board(board_path)

            start = TOOL_REGISTRY["start_session"].handler()
            sid = start["session_id"]

            TOOL_REGISTRY["delete_component"].handler(session_id=sid, reference="C7")
            TOOL_REGISTRY["commit_session"].handler(session_id=sid)

            doc = Document.load(board_path)
            refs = []
            for fp in doc.root.find_all("footprint"):
                for prop in fp.find_all("property"):
                    if prop.first_value == "Reference":
                        refs.append(prop.atom_values[1])
            assert "C7" not in refs
