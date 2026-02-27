"""Tests for the S-expression parser."""

from __future__ import annotations

# Default to the synthetic fixture; override with KICAD_TEST_BOARD env var
import os
from pathlib import Path

import pytest

from kicad_mcp.sexp import Document, parse, parse_all

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "minimal_board.kicad_pcb"
BOARD_PATH = Path(os.environ.get("KICAD_TEST_BOARD", str(FIXTURE_PATH)))


class TestParseAtoms:
    def test_unquoted_atom(self) -> None:
        node = parse("hello")
        assert node.is_atom
        assert node.value == "hello"

    def test_quoted_string(self) -> None:
        node = parse('"hello world"')
        assert node.is_atom
        assert node.value == "hello world"

    def test_quoted_with_escapes(self) -> None:
        node = parse(r'"say \"hi\""')
        assert node.value == 'say "hi"'

    def test_number_atom(self) -> None:
        node = parse("42")
        assert node.is_atom
        assert node.value == "42"

    def test_float_atom(self) -> None:
        node = parse("3.14159")
        assert node.value == "3.14159"


class TestParseExpressions:
    def test_simple_pair(self) -> None:
        node = parse("(version 20241229)")
        assert node.is_list
        assert node.name == "version"
        assert node.first_value == "20241229"

    def test_nested_expression(self) -> None:
        node = parse("(a (b c) (d e))")
        assert node.name == "a"
        assert len(node.children) == 2
        assert node.children[0].name == "b"
        assert node.children[0].first_value == "c"
        assert node.children[1].name == "d"
        assert node.children[1].first_value == "e"

    def test_deeply_nested(self) -> None:
        node = parse("(a (b (c (d value))))")
        assert node.name == "a"
        inner = node["b"]["c"]["d"]
        assert inner.first_value == "value"

    def test_multiple_values(self) -> None:
        node = parse("(at 14 5.5)")
        assert node.name == "at"
        assert node.atom_values == ["14", "5.5"]

    def test_empty_quoted_string_value(self) -> None:
        node = parse('(net 0 "")')
        assert node.name == "net"
        assert node.atom_values == ["0", ""]

    def test_mixed_children(self) -> None:
        node = parse('(footprint "Capacitor_SMD:C_0805" (layer "F.Cu") (at 14 5.5))')
        assert node.name == "footprint"
        assert node.first_value == "Capacitor_SMD:C_0805"
        assert node["layer"].first_value == "F.Cu"
        assert node["at"].atom_values == ["14", "5.5"]


class TestQueryAPI:
    def test_getitem_found(self) -> None:
        node = parse("(root (child1 a) (child2 b))")
        assert node["child1"].first_value == "a"

    def test_getitem_not_found(self) -> None:
        node = parse("(root (child1 a))")
        with pytest.raises(KeyError):
            _ = node["missing"]

    def test_get_found(self) -> None:
        node = parse("(root (child1 a))")
        assert node.get("child1") is not None

    def test_get_not_found(self) -> None:
        node = parse("(root (child1 a))")
        assert node.get("missing") is None

    def test_find(self) -> None:
        node = parse("(root (child1 a) (child2 b))")
        found = node.find("child2")
        assert found is not None
        assert found.first_value == "b"

    def test_find_all(self) -> None:
        node = parse("(root (item a) (item b) (item c))")
        items = node.find_all("item")
        assert len(items) == 3
        assert [i.first_value for i in items] == ["a", "b", "c"]

    def test_find_recursive(self) -> None:
        node = parse("(root (a (pad 1)) (b (pad 2)) (pad 3))")
        pads = list(node.find_recursive("pad"))
        assert len(pads) == 3

    def test_atom_values(self) -> None:
        node = parse("(size 1 1.45)")
        assert node.atom_values == ["1", "1.45"]


class TestRoundTrip:
    def test_simple_round_trip(self) -> None:
        original = "(version 20241229)"
        tree = parse(original)
        assert tree.to_string() == original

    def test_nested_round_trip(self) -> None:
        original = "(a (b c) (d e))"
        tree = parse(original)
        # Now multi-line because of nested list children
        expected = "(a\n  (b c)\n  (d e))"
        assert tree.to_string() == expected

    def test_quoted_string_round_trip(self) -> None:
        original = '(generator "pcbnew")'
        tree = parse(original)
        assert tree.to_string() == original

    def test_number_formatting_preserved(self) -> None:
        original = "(at 14 5.5)"
        tree = parse(original)
        assert tree.to_string() == original

    def test_float_formatting_preserved(self) -> None:
        original = "(thickness 0.15)"
        tree = parse(original)
        assert tree.to_string() == original

    def test_complex_round_trip(self) -> None:
        original = (
            '(pad "1" smd roundrect (at -0.95 0) (size 1 1.45)'
            ' (layers "F.Cu" "F.Mask" "F.Paste") (roundrect_rratio 0.25))'
        )
        tree = parse(original)
        # Now multi-line because of nested list children
        expected = (
            '(pad "1" smd roundrect\n'
            "  (at -0.95 0)\n"
            "  (size 1 1.45)\n"
            '  (layers "F.Cu" "F.Mask" "F.Paste")\n'
            "  (roundrect_rratio 0.25))"
        )
        assert tree.to_string() == expected

    def test_flat_stays_single_line(self) -> None:
        """Nodes with only atom children stay on one line."""
        tree = parse("(size 1 1.45)")
        assert tree.to_string() == "(size 1 1.45)"

    def test_indented_output(self) -> None:
        """Verify multi-level indentation."""
        tree = parse("(root (child (grandchild val)))")
        expected = "(root\n  (child\n    (grandchild val)))"
        assert tree.to_string() == expected

    def test_deeply_nested_indentation(self) -> None:
        """Verify 3+ levels of indentation."""
        tree = parse("(a (b (c (d value))))")
        expected = "(a\n  (b\n    (c\n      (d value))))"
        assert tree.to_string() == expected


class TestParseAll:
    def test_multiple_expressions(self) -> None:
        text = "(a 1) (b 2) (c 3)"
        nodes = parse_all(text)
        assert len(nodes) == 3
        assert nodes[0].name == "a"
        assert nodes[2].name == "c"


@pytest.mark.skipif(not BOARD_PATH.exists(), reason="Test fixture not available")
class TestBoardFixture:
    """Integration tests using the board fixture."""

    @pytest.fixture()
    def doc(self) -> Document:
        return Document.load(BOARD_PATH)

    def test_load_succeeds(self, doc: Document) -> None:
        assert doc.root.name == "kicad_pcb"

    def test_version(self, doc: Document) -> None:
        assert doc.root["version"].first_value == "20241229"

    def test_generator(self, doc: Document) -> None:
        assert doc.root["generator"].first_value == "pcbnew"

    def test_layers(self, doc: Document) -> None:
        layers_node = doc.root["layers"]
        layer_nodes = [c for c in layers_node.children if c.is_list]
        assert len(layer_nodes) >= 12

    def test_nets(self, doc: Document) -> None:
        nets = doc.root.find_all("net")
        assert len(nets) >= 3

    def test_net_names(self, doc: Document) -> None:
        nets = doc.root.find_all("net")
        net_names = []
        for net in nets:
            vals = net.atom_values
            if len(vals) >= 2:
                net_names.append(vals[1])
        assert "VCC" in net_names
        assert "GND" in net_names

    def test_footprints(self, doc: Document) -> None:
        footprints = doc.root.find_all("footprint")
        assert len(footprints) >= 3

    def test_footprint_reference(self, doc: Document) -> None:
        footprints = doc.root.find_all("footprint")
        fp = footprints[0]
        ref_prop = None
        for prop in fp.find_all("property"):
            if prop.first_value == "Reference":
                ref_prop = prop
                break
        assert ref_prop is not None

    def test_footprint_query(self, doc: Document) -> None:
        footprints = doc.root.find_all("footprint")
        fp_names = [fp.first_value for fp in footprints]
        assert "Capacitor_SMD:C_0805_2012Metric" in fp_names

    def test_title_block(self, doc: Document) -> None:
        title_block = doc.root["title_block"]
        assert title_block["title"].first_value == "minimal_board"

    def test_document_file_type(self, doc: Document) -> None:
        assert doc.file_type == "kicad_pcb"

    def test_document_repr(self, doc: Document) -> None:
        r = repr(doc)
        assert "minimal_board" in r
        assert "kicad_pcb" in r
