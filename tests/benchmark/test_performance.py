"""Performance benchmarks for S-expr parsing and board operations.

Run with: uv run pytest tests/benchmark/ -v -s
The -s flag shows the timing output.

These generate synthetic boards of various sizes to test scalability.
No external fixtures required.
"""

from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path

import pytest

from kicad_mcp.session.manager import SessionManager
from kicad_mcp.sexp import Document
from kicad_mcp.sexp.parser import parse as sexp_parse


def _generate_board(num_components: int, num_traces: int = 0) -> str:
    """Generate a synthetic .kicad_pcb file with N components and M traces."""
    lines = [
        '(kicad_pcb (version 20241229) (generator "benchmark")',
        "  (general (thickness 1.6) (legacy_teardrops no))",
        "  (paper A4)",
        "  (layers",
        '    (0 "F.Cu" signal)',
        '    (31 "B.Cu" signal)',
        '    (36 "B.SilkS" user "B.Silkscreen")',
        '    (37 "F.SilkS" user "F.Silkscreen")',
        '    (44 "Edge.Cuts" user)',
        "  )",
        "  (setup",
        "    (pad_to_mask_clearance 0)",
        "    (allow_soldermask_bridges_in_footprints no)",
        "    (pcbplotparams (layerselection 0x00010fc_ffffffff)"
        " (plot_on_all_layers_selection 0x0))",
        "  )",
        '  (net 0 "")',
        '  (net 1 "GND")',
        '  (net 2 "VCC")',
    ]

    # Add more nets for variety
    for i in range(3, min(num_components + 3, 100)):
        lines.append(f'  (net {i} "NET{i}")')

    # Generate footprints
    cols = max(int(num_components**0.5), 1)
    for i in range(num_components):
        x = (i % cols) * 5.0 + 10
        y = (i // cols) * 5.0 + 10
        ref = f"R{i + 1}"
        net_num = (i % 3) + 1
        fp_uuid = uuid.uuid4()
        ref_uuid = uuid.uuid4()
        val_uuid = uuid.uuid4()
        pad1_uuid = uuid.uuid4()
        pad2_uuid = uuid.uuid4()

        lines.append(
            f'  (footprint "Resistor_SMD:R_0402_1005Metric"'
            f' (layer "F.Cu") (uuid "{fp_uuid}") (at {x} {y})'
        )
        lines.append(
            f'    (property "Reference" "{ref}"'
            f' (at 0 -1.5 0) (layer "F.SilkS") (uuid "{ref_uuid}")'
            f"    (effects (font (size 1 1) (thickness 0.15))))"
        )
        lines.append(
            f'    (property "Value" "10k"'
            f' (at 0 1.5 0) (layer "F.Fab") (uuid "{val_uuid}")'
            f"    (effects (font (size 1 1) (thickness 0.15))))"
        )

        def _net_name(n: int) -> str:
            return "GND" if n == 1 else "VCC" if n == 2 else f"NET{n}"

        net1 = _net_name(net_num)
        net2_num = (net_num % 3) + 1
        net2 = _net_name(net2_num)
        lines.append(
            f'    (pad "1" smd roundrect (at -0.51 0)'
            f" (size 0.54 0.64)"
            f' (layers "F.Cu" "F.Paste" "F.Mask")'
            f" (roundrect_rratio 0.25)"
            f' (net {net_num} "{net1}")'
            f' (uuid "{pad1_uuid}"))'
        )
        lines.append(
            f'    (pad "2" smd roundrect (at 0.51 0)'
            f" (size 0.54 0.64)"
            f' (layers "F.Cu" "F.Paste" "F.Mask")'
            f" (roundrect_rratio 0.25)"
            f' (net {net2_num} "{net2}")'
            f' (uuid "{pad2_uuid}"))'
        )
        lines.append("  )")

    # Generate trace segments
    for i in range(num_traces):
        sx = (i % cols) * 5.0 + 10.51
        sy = (i // cols) * 5.0 + 10
        ex = sx + 4.0
        ey = sy
        net_num = (i % 3) + 1
        seg_uuid = uuid.uuid4()
        lines.append(
            f"  (segment (start {sx} {sy}) (end {ex} {ey})"
            f' (width 0.25) (layer "F.Cu") (net {net_num})'
            f' (uuid "{seg_uuid}"))'
        )

    lines.append(")")
    return "\n".join(lines)


class TestParsePerformance:
    """Benchmark S-expression parsing at various board sizes."""

    @pytest.mark.parametrize(
        "count", [50, 100, 250, 500], ids=["50comp", "100comp", "250comp", "500comp"]
    )
    def test_parse_speed(self, count: int) -> None:
        text = _generate_board(count)
        size_kb = len(text) / 1024

        start = time.perf_counter()
        node = sexp_parse(text)
        elapsed = time.perf_counter() - start

        fps = node.find_all("footprint")
        assert len(fps) == count

        print(
            f"\n  Parse {count} components ({size_kb:.0f} KB): "
            f"{elapsed:.3f}s ({count / elapsed:.0f} components/s)"
        )

    @pytest.mark.parametrize(
        "count", [50, 100, 250, 500], ids=["50comp", "100comp", "250comp", "500comp"]
    )
    def test_document_load_speed(self, count: int) -> None:
        text = _generate_board(count)

        with tempfile.NamedTemporaryFile(
            suffix=".kicad_pcb", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            path = f.name

        try:
            start = time.perf_counter()
            doc = Document.load(path)
            elapsed = time.perf_counter() - start

            assert len(doc.root.find_all("footprint")) == count
            print(f"\n  Document.load {count} components: {elapsed:.3f}s")
        finally:
            Path(path).unlink(missing_ok=True)


class TestSessionPerformance:
    """Benchmark session operations at various scales."""

    @pytest.mark.parametrize("count", [50, 100, 250], ids=["50comp", "100comp", "250comp"])
    def test_session_start_speed(self, count: int) -> None:
        text = _generate_board(count)
        with tempfile.NamedTemporaryFile(
            suffix=".kicad_pcb", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            path = f.name

        try:
            doc = Document.load(path)
            mgr = SessionManager()

            start = time.perf_counter()
            session = mgr.start_session(doc)
            elapsed = time.perf_counter() - start

            assert session is not None
            print(f"\n  start_session ({count} components): {elapsed:.3f}s")
        finally:
            Path(path).unlink(missing_ok=True)

    @pytest.mark.parametrize("count", [10, 50, 100], ids=["10moves", "50moves", "100moves"])
    def test_batch_move_speed(self, count: int) -> None:
        text = _generate_board(max(count, 100))
        with tempfile.NamedTemporaryFile(
            suffix=".kicad_pcb", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            path = f.name

        try:
            doc = Document.load(path)
            mgr = SessionManager()
            session = mgr.start_session(doc)

            start = time.perf_counter()
            for i in range(count):
                mgr.apply_move(session, f"R{i + 1}", x=float(i), y=float(i))
            elapsed = time.perf_counter() - start

            assert len(session.changes) == count
            print(
                f"\n  {count} apply_move operations: {elapsed:.3f}s ({count / elapsed:.0f} ops/s)"
            )
        finally:
            Path(path).unlink(missing_ok=True)

    @pytest.mark.parametrize("count", [10, 50, 100], ids=["10undos", "50undos", "100undos"])
    def test_batch_undo_speed(self, count: int) -> None:
        text = _generate_board(max(count, 100))
        with tempfile.NamedTemporaryFile(
            suffix=".kicad_pcb", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            path = f.name

        try:
            doc = Document.load(path)
            mgr = SessionManager()
            session = mgr.start_session(doc)

            for i in range(count):
                mgr.apply_move(session, f"R{i + 1}", x=float(i), y=float(i))

            start = time.perf_counter()
            for _ in range(count):
                mgr.undo(session)
            elapsed = time.perf_counter() - start

            applied = [c for c in session.changes if c.applied]
            assert len(applied) == 0
            print(f"\n  {count} undo operations: {elapsed:.3f}s ({count / elapsed:.0f} ops/s)")
        finally:
            Path(path).unlink(missing_ok=True)


class TestFindComponentPerformance:
    """Benchmark component lookup in boards of various sizes."""

    @pytest.mark.parametrize(
        "count", [50, 100, 250, 500], ids=["50comp", "100comp", "250comp", "500comp"]
    )
    def test_find_footprint_speed(self, count: int) -> None:
        text = _generate_board(count)
        with tempfile.NamedTemporaryFile(
            suffix=".kicad_pcb", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            path = f.name

        try:
            doc = Document.load(path)
            # Look up the last component (worst case — linear scan)
            target = f"R{count}"

            start = time.perf_counter()
            for _ in range(100):
                fp = SessionManager._find_footprint(doc, target)
            elapsed = time.perf_counter() - start

            assert fp is not None
            per_lookup_us = (elapsed / 100) * 1_000_000
            print(
                f"\n  find_footprint in {count}-component board: {per_lookup_us:.0f} \u00b5s/lookup"
            )
        finally:
            Path(path).unlink(missing_ok=True)


class TestCommitPerformance:
    """Benchmark commit (write to disk) at various sizes."""

    @pytest.mark.parametrize("count", [50, 100, 250], ids=["50comp", "100comp", "250comp"])
    def test_commit_speed(self, count: int) -> None:
        text = _generate_board(count, num_traces=count)
        with tempfile.NamedTemporaryFile(
            suffix=".kicad_pcb", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            path = f.name

        try:
            doc = Document.load(path)
            mgr = SessionManager()
            session = mgr.start_session(doc)

            # Make some changes
            for i in range(min(count, 20)):
                mgr.apply_move(session, f"R{i + 1}", x=99.0, y=99.0)

            start = time.perf_counter()
            mgr.commit(session)
            elapsed = time.perf_counter() - start

            # Verify file was written
            assert Path(path).stat().st_size > 0
            print(f"\n  commit {count}-component board (20 changes): {elapsed:.3f}s")
        finally:
            Path(path).unlink(missing_ok=True)
