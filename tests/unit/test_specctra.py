"""Tests for Specctra DSN export and SES import (Freerouting interchange)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kicad_mcp.backends import freerouting
from kicad_mcp.sexp import Document
from kicad_mcp.specctra import (
    DsnExportError,
    DsnOptions,
    SesParseError,
    board_to_dsn,
    infer_units_per_mm,
    parse_ses,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
BOARD_PATH = Path(os.environ.get("KICAD_TEST_BOARD", str(FIXTURES / "minimal_board.kicad_pcb")))
SES_PATH = FIXTURES / "minimal_board.ses"

pytestmark = pytest.mark.skipif(not BOARD_PATH.exists(), reason="Board fixture not available")


@pytest.fixture()
def doc() -> Document:
    return Document.load(BOARD_PATH)


# ── DSN export ─────────────────────────────────────────────────────


class TestDsnExport:
    def test_basic_structure(self, doc: Document) -> None:
        dsn = board_to_dsn(doc, DsnOptions(), name="minimal")
        assert dsn.startswith("(pcb minimal")
        assert "(resolution um 10)" in dsn
        assert "(layer F.Cu (type signal)" in dsn
        assert "(layer B.Cu (type signal)" in dsn
        assert "(boundary (path pcb 0" in dsn
        assert "(via Via_default)" in dsn

    def test_nets_and_pins(self, doc: Document) -> None:
        dsn = board_to_dsn(doc)
        # VCC connects R1-1, C1-1, U1-1, U1-8; GND connects R1-2, C1-2, U1-4.
        assert "(net VCC" in dsn
        assert "R1-1" in dsn and "U1-8" in dsn
        assert "(net GND" in dsn
        assert "(class kicad_default VCC GND" in dsn

    def test_pad_coordinates_relative_and_scaled(self, doc: Document) -> None:
        dsn = board_to_dsn(doc)
        # R1 pads at +/-0.5mm -> +/-5000 units, relative to component origin.
        assert "(pin PS_rect_6000x5000_FCu 1 -5000 0)" in dsn
        assert "(pin PS_rect_6000x5000_FCu 2 5000 0)" in dsn

    def test_y_axis_negated(self, doc: Document) -> None:
        dsn = board_to_dsn(doc)
        # Board spans y 0..30mm; negated boundary should carry a -300000 unit.
        assert "-300000" in dsn

    def test_rule_widths_scale_with_options(self, doc: Document) -> None:
        dsn = board_to_dsn(doc, DsnOptions(trace_width=0.3, clearance=0.25))
        assert "(rule (width 3000) (clearance 2500))" in dsn

    def test_no_outline_raises(self) -> None:
        # A board with no Edge.Cuts cannot define a routing boundary.
        from kicad_mcp.sexp.parser import parse as sexp_parse

        text = (
            '(kicad_pcb (version 20241229) (generator "x")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (net 0 "")\n)'
        )
        doc = Document(path=Path("/tmp/no_outline.kicad_pcb"), root=sexp_parse(text), raw_text=text)
        with pytest.raises(DsnExportError, match="outline"):
            board_to_dsn(doc)


# ── SES import ─────────────────────────────────────────────────────


@pytest.mark.skipif(not SES_PATH.exists(), reason="SES fixture not available")
class TestSesParse:
    def _known(self, doc: Document) -> dict[str, tuple[float, float]]:
        from kicad_mcp.schema.extract import extract_footprints

        return {fp.reference: (fp.position.x, fp.position.y) for fp in extract_footprints(doc)}

    def test_calibration(self, doc: Document) -> None:
        text = SES_PATH.read_text()
        scale = infer_units_per_mm(text, self._known(doc))
        assert scale == 100000.0

    def test_parse_calibrated_coords(self, doc: Document) -> None:
        text = SES_PATH.read_text()
        scale = infer_units_per_mm(text, self._known(doc))
        route = parse_ses(text, units_per_mm=scale)
        assert len(route.wires) > 0
        assert route.segment_count >= len(route.wires)
        # First VCC wire starts at R1 pad1 ~ (9.5, 10.0)mm, width 0.25.
        first = route.wires[0]
        assert first.net_name == "VCC"
        assert first.layer == "F.Cu"
        assert abs(first.width - 0.25) < 1e-6
        x, y = first.points[0]
        assert abs(x - 9.5) < 0.01
        assert abs(y - 10.0) < 0.01

    def test_parse_without_calibration_still_parses(self) -> None:
        # Falls back to the declared resolution (10x off, but must not error).
        route = parse_ses(SES_PATH.read_text())
        assert len(route.wires) > 0

    def test_garbage_raises(self) -> None:
        with pytest.raises(SesParseError):
            parse_ses("(session x (placement)) trailing junk (((")

    def test_no_routes_block(self) -> None:
        with pytest.raises(SesParseError, match="routes"):
            parse_ses("(session x (placement))")


# ── Freerouting backend ────────────────────────────────────────────


class TestFreeroutingBackend:
    def test_jar_version_from_filename(self) -> None:
        assert freerouting._jar_version("/x/freerouting-2.2.4.jar") == "2.2.4"
        assert freerouting._jar_version("/x/freerouting.jar") == "unknown"

    def test_runtime_from_env_jar(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        jar = tmp_path / "freerouting-2.2.4.jar"
        jar.write_text("not really a jar")
        monkeypatch.setenv("FREEROUTING_JAR", str(jar))
        monkeypatch.delenv("FREEROUTING_CMD", raising=False)
        monkeypatch.setattr(freerouting.shutil, "which", lambda name: "/usr/bin/java")
        rt = freerouting.find_runtime()
        assert rt is not None
        assert rt.kind == "jar"
        assert rt.detail == str(jar)
        assert freerouting.is_available()

    def test_runtime_info_hint_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FREEROUTING_JAR", raising=False)
        monkeypatch.delenv("FREEROUTING_CMD", raising=False)
        monkeypatch.setattr(freerouting, "_find_jar", lambda: None)
        monkeypatch.setattr(freerouting.shutil, "which", lambda name: None)
        info = freerouting.runtime_info()
        assert info["available"] is False
        assert "hint" in info

    def test_build_command_jar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(freerouting.shutil, "which", lambda name: "/usr/bin/java")
        rt = freerouting.FreeroutingRuntime(kind="jar", detail="/x/fr.jar")
        cmd = freerouting._build_command(rt, "in.dsn", "out.ses", 7, 2)
        assert "-jar" in cmd and "/x/fr.jar" in cmd
        assert cmd[cmd.index("-de") + 1] == "in.dsn"
        assert cmd[cmd.index("-do") + 1] == "out.ses"
        assert cmd[cmd.index("-mp") + 1] == "7"
        assert "--gui.enabled=false" in cmd
        assert "-da" in cmd

    def test_route_raises_without_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(freerouting, "find_runtime", lambda: None)
        with pytest.raises(freerouting.FreeroutingNotFound):
            freerouting.route("in.dsn", "out.ses")
