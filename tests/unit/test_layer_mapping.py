"""Tests for layer name normalization (display names → internal names)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kicad_mcp.session.manager import SessionManager
from kicad_mcp.session.types import _LAYER_ALIASES, _normalize_layer
from kicad_mcp.sexp import Document

BOARD_PATH = Path(
    os.environ.get(
        "KICAD_TEST_BOARD",
        str(Path(__file__).parent.parent / "fixtures" / "minimal_board.kicad_pcb"),
    )
)

skip_no_board = pytest.mark.skipif(not BOARD_PATH.exists(), reason="Test fixture not available")


class TestNormalizeLayer:
    """Unit tests for _normalize_layer helper."""

    def test_internal_name_unchanged(self) -> None:
        assert _normalize_layer("F.SilkS") == "F.SilkS"
        assert _normalize_layer("B.CrtYd") == "B.CrtYd"
        assert _normalize_layer("F.Cu") == "F.Cu"

    @pytest.mark.parametrize(
        "display,internal",
        list(_LAYER_ALIASES.items()),
        ids=list(_LAYER_ALIASES.keys()),
    )
    def test_all_aliases_mapped(self, display: str, internal: str) -> None:
        assert _normalize_layer(display) == internal

    def test_unknown_name_passthrough(self) -> None:
        assert _normalize_layer("Edge.Cuts") == "Edge.Cuts"
        assert _normalize_layer("In1.Cu") == "In1.Cu"
        assert _normalize_layer("MyCustomLayer") == "MyCustomLayer"


@skip_no_board
class TestLayerMappingIntegration:
    """Integration tests: display-name layers produce correct S-expression."""

    def _make_session(self):
        doc = Document.load(str(BOARD_PATH))
        mgr = SessionManager()
        return mgr, mgr.start_session(doc)

    def test_add_board_text_normalizes_layer(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_add_board_text(session, text="Hello", x=10, y=20, layer="F.Silkscreen")
        assert record.applied
        # The S-expression should contain the internal name, not the display name
        assert '"F.SilkS"' in record.after_snapshot
        assert "F.Silkscreen" not in record.after_snapshot

    def test_add_board_text_internal_name_still_works(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_add_board_text(session, text="Test", x=5, y=5, layer="F.SilkS")
        assert record.applied
        assert '"F.SilkS"' in record.after_snapshot

    def test_route_trace_normalizes_layer(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_route_trace(
            session,
            start_x=0,
            start_y=0,
            end_x=10,
            end_y=0,
            width=0.25,
            layer="F.Silkscreen",
            net_number=0,
        )
        assert record.applied
        assert '"F.SilkS"' in record.after_snapshot

    def test_add_via_normalizes_layers(self) -> None:
        mgr, session = self._make_session()
        record = mgr.apply_add_via(
            session,
            x=5,
            y=5,
            net_number=0,
            layers=("F.Silkscreen", "B.Silkscreen"),
        )
        assert record.applied
        assert '"F.SilkS"' in record.after_snapshot
        assert '"B.SilkS"' in record.after_snapshot
        assert "Silkscreen" not in record.after_snapshot
