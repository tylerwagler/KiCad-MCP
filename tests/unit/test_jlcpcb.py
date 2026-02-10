"""Tests for JLCPCB parts catalog — models, package extraction, API client, tool handlers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kicad_mcp.manufacturers.jlcpcb import (
    JlcpcbApiError,
    JlcpcbAssignment,
    JlcpcbSearchResult,
    _extract_lowest_price,
    _parse_part,
    extract_package_from_library,
    get_part_details,
    search_parts,
)

# ── Test Data ───────────────────────────────────────────────────────

SAMPLE_API_COMPONENT = {
    "lcsc": 123456,
    "mfr": "GRM155R71C104KA88D",
    "package": "0402",
    "description": "100nF ±10% 16V X7R 0402",
    "stock": 50000,
    "price": 0.0045,
    "basic": True,
    "extra": {
        "manufacturer": "Murata",
        "datasheet": "https://example.com/ds.pdf",
        "moq": 100,
        "category": "Capacitors",
        "description": "MLCC",
    },
}

SAMPLE_API_COMPONENT_MINIMAL = {
    "lcsc": 789,
    "mfr": "PART-X",
    "package": "0805",
    "description": "Resistor",
    "stock": 0,
    "price": "0.01",
    "basic": False,
}


# ── TestParsePartData ───────────────────────────────────────────────


class TestParsePartData:
    def test_parse_full_component(self) -> None:
        part = _parse_part(SAMPLE_API_COMPONENT)
        assert part.lcsc == 123456
        assert part.mfr == "GRM155R71C104KA88D"
        assert part.package == "0402"
        assert part.stock == 50000
        assert part.price == 0.0045
        assert part.basic is True
        assert part.manufacturer == "Murata"
        assert part.datasheet_url == "https://example.com/ds.pdf"
        assert part.moq == 100
        assert part.category == "Capacitors"

    def test_parse_minimal_component(self) -> None:
        part = _parse_part(SAMPLE_API_COMPONENT_MINIMAL)
        assert part.lcsc == 789
        assert part.basic is False
        assert part.manufacturer == ""
        assert part.moq == 1

    def test_lcsc_code_property(self) -> None:
        part = _parse_part(SAMPLE_API_COMPONENT)
        assert part.lcsc_code == "C123456"

    def test_to_dict(self) -> None:
        part = _parse_part(SAMPLE_API_COMPONENT)
        d = part.to_dict()
        assert d["lcsc"] == "C123456"
        assert d["price_usd"] == 0.0045
        assert d["basic"] is True
        assert d["manufacturer"] == "Murata"

    def test_price_from_string(self) -> None:
        assert _extract_lowest_price("$0.005") == 0.005
        assert _extract_lowest_price("0.01") == 0.01

    def test_price_from_list(self) -> None:
        breaks = [{"qty": 1, "price": 0.01}, {"qty": 100, "price": 0.005}]
        assert _extract_lowest_price(breaks) == 0.01

    def test_price_from_invalid(self) -> None:
        assert _extract_lowest_price("not-a-number") == 0.0
        assert _extract_lowest_price(None) == 0.0
        assert _extract_lowest_price([]) == 0.0


class TestSearchResult:
    def test_to_dict(self) -> None:
        part = _parse_part(SAMPLE_API_COMPONENT)
        sr = JlcpcbSearchResult(query="100nF", count=1, parts=[part])
        d = sr.to_dict()
        assert d["query"] == "100nF"
        assert d["count"] == 1
        assert len(d["parts"]) == 1


class TestAssignment:
    def test_to_dict(self) -> None:
        a = JlcpcbAssignment(
            reference="C1",
            value="100nF",
            footprint="Capacitor_SMD:C_0402_1005Metric",
            lcsc="C123456",
            mfr="GRM155",
            description="100nF cap",
            basic=True,
            confidence="high",
            alternatives=[],
        )
        d = a.to_dict()
        assert d["reference"] == "C1"
        assert d["lcsc"] == "C123456"
        assert d["confidence"] == "high"


# ── TestPackageExtraction ───────────────────────────────────────────


class TestPackageExtraction:
    def test_0805(self) -> None:
        assert extract_package_from_library("Capacitor_SMD:C_0805_2012Metric") == "0805"

    def test_0402(self) -> None:
        assert extract_package_from_library("Resistor_SMD:R_0402_1005Metric") == "0402"

    def test_soic8(self) -> None:
        assert extract_package_from_library("Package_SO:SOIC-8_3.9x4.9mm_P1.27mm") == "SOIC-8"

    def test_sot23(self) -> None:
        assert extract_package_from_library("Package_TO_SOT_SMD:SOT-23") == "SOT-23"

    def test_qfn32(self) -> None:
        assert extract_package_from_library("Package_DFN_QFN:QFN-32-1EP_5x5mm") == "QFN-32"

    def test_tssop(self) -> None:
        assert extract_package_from_library("Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm") == "TSSOP-20"

    def test_lqfp(self) -> None:
        assert extract_package_from_library("Package_QFP:LQFP-48_7x7mm") == "LQFP-48"

    def test_unknown(self) -> None:
        assert extract_package_from_library("Custom:MyWeirdPackage") is None

    def test_to252(self) -> None:
        assert extract_package_from_library("Package_TO_SOT_SMD:TO-252-2") == "TO-252"


# ── TestSearchParts (mocked HTTP) ───────────────────────────────────


def _mock_response(components: list[dict], status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"components": components}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx

        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestSearchParts:
    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_search_success(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response([SAMPLE_API_COMPONENT])
        result = search_parts("100nF")
        assert result.count == 1
        assert result.parts[0].lcsc == 123456
        mock_get.assert_called_once()

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_search_with_package(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response([SAMPLE_API_COMPONENT])
        search_parts("100nF", package="0402")
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["package"] == "0402"

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_search_empty(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response([])
        result = search_parts("xyznonexistent")
        assert result.count == 0
        assert result.parts == []

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_search_timeout(self, mock_get: MagicMock) -> None:
        import httpx

        mock_get.side_effect = httpx.TimeoutException("timed out")
        with pytest.raises(JlcpcbApiError, match="timed out"):
            search_parts("100nF")

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_search_http_error(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response([], status_code=500)
        with pytest.raises(JlcpcbApiError, match="HTTP 500"):
            search_parts("100nF")


# ── TestGetPartDetails ──────────────────────────────────────────────


class TestGetPartDetails:
    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_found(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response([SAMPLE_API_COMPONENT])
        part = get_part_details("C123456")
        assert part is not None
        assert part.lcsc == 123456

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_not_found(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response([])
        part = get_part_details("C999999")
        assert part is None

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_strips_c_prefix(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response([SAMPLE_API_COMPONENT])
        get_part_details("C123456")
        call_kwargs = mock_get.call_args
        assert "C123456" in call_kwargs[1]["params"]["search"]


# ── TestToolHandlers ────────────────────────────────────────────────


class TestJlcpcbToolHandlers:
    def test_tools_registered(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        assert "jlcpcb_search_parts" in TOOL_REGISTRY
        assert "jlcpcb_check_availability" in TOOL_REGISTRY
        assert "jlcpcb_auto_assign" in TOOL_REGISTRY
        assert "jlcpcb_export_bom_cpl" in TOOL_REGISTRY

    def test_tools_in_jlcpcb_category(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        for name in [
            "jlcpcb_search_parts",
            "jlcpcb_check_availability",
            "jlcpcb_auto_assign",
            "jlcpcb_export_bom_cpl",
        ]:
            assert TOOL_REGISTRY[name].category == "jlcpcb"

    def test_tools_are_routed(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        for name in [
            "jlcpcb_search_parts",
            "jlcpcb_check_availability",
            "jlcpcb_auto_assign",
            "jlcpcb_export_bom_cpl",
        ]:
            assert TOOL_REGISTRY[name].direct is False

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_search_handler(self, mock_get: MagicMock) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        mock_get.return_value = _mock_response([SAMPLE_API_COMPONENT])
        result = TOOL_REGISTRY["jlcpcb_search_parts"].handler(query="100nF")
        assert result["count"] == 1
        assert result["parts"][0]["lcsc"] == "C123456"

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_search_handler_api_error(self, mock_get: MagicMock) -> None:
        import httpx

        from kicad_mcp.tools import TOOL_REGISTRY

        mock_get.side_effect = httpx.TimeoutException("timeout")
        result = TOOL_REGISTRY["jlcpcb_search_parts"].handler(query="100nF")
        assert "error" in result

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_availability_found(self, mock_get: MagicMock) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        mock_get.return_value = _mock_response([SAMPLE_API_COMPONENT])
        result = TOOL_REGISTRY["jlcpcb_check_availability"].handler(lcsc_code="C123456")
        assert result["found"] is True
        assert result["in_stock"] is True

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_availability_not_found(self, mock_get: MagicMock) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        mock_get.return_value = _mock_response([])
        result = TOOL_REGISTRY["jlcpcb_check_availability"].handler(lcsc_code="C999999")
        assert result["found"] is False

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_auto_assign_basic_pref(self, mock_get: MagicMock) -> None:
        from kicad_mcp.schema.board import Footprint
        from kicad_mcp.schema.common import Position
        from kicad_mcp.tools import TOOL_REGISTRY

        mock_get.return_value = _mock_response(
            [
                SAMPLE_API_COMPONENT,
                {**SAMPLE_API_COMPONENT_MINIMAL, "lcsc": 999, "basic": False, "stock": 100000},
            ]
        )

        fps = [
            Footprint(
                library="Capacitor_SMD:C_0402_1005Metric",
                reference="C1",
                value="100nF",
                position=Position(x=10.0, y=20.0),
                layer="F.Cu",
            ),
        ]

        with patch("kicad_mcp.tools.jlcpcb.state") as mock_state:
            mock_state.get_footprints.return_value = fps
            result = TOOL_REGISTRY["jlcpcb_auto_assign"].handler(prefer_basic=True)

        assert result["assigned"] == 1
        assert result["assignments"][0]["basic"] is True

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_auto_assign_specific_refs(self, mock_get: MagicMock) -> None:
        from kicad_mcp.schema.board import Footprint
        from kicad_mcp.schema.common import Position
        from kicad_mcp.tools import TOOL_REGISTRY

        mock_get.return_value = _mock_response([SAMPLE_API_COMPONENT])

        fps = [
            Footprint(
                library="Capacitor_SMD:C_0402_1005Metric",
                reference="C1",
                value="100nF",
                position=Position(x=10.0, y=20.0),
                layer="F.Cu",
            ),
            Footprint(
                library="Resistor_SMD:R_0402_1005Metric",
                reference="R1",
                value="10k",
                position=Position(x=30.0, y=40.0),
                layer="F.Cu",
            ),
        ]

        with patch("kicad_mcp.tools.jlcpcb.state") as mock_state:
            mock_state.get_footprints.return_value = fps
            result = TOOL_REGISTRY["jlcpcb_auto_assign"].handler(references="C1")

        # Only C1 should be assigned, R1 should be skipped (not in filter)
        assert result["assigned"] == 1
        assert result["assignments"][0]["reference"] == "C1"

    @patch("kicad_mcp.manufacturers.jlcpcb.httpx.get")
    def test_auto_assign_no_match(self, mock_get: MagicMock) -> None:
        from kicad_mcp.schema.board import Footprint
        from kicad_mcp.schema.common import Position
        from kicad_mcp.tools import TOOL_REGISTRY

        mock_get.return_value = _mock_response([])

        fps = [
            Footprint(
                library="Custom:UnknownPart",
                reference="U1",
                value="MYSTERY_IC",
                position=Position(x=0.0, y=0.0),
                layer="F.Cu",
            ),
        ]

        with patch("kicad_mcp.tools.jlcpcb.state") as mock_state:
            mock_state.get_footprints.return_value = fps
            result = TOOL_REGISTRY["jlcpcb_auto_assign"].handler()

        assert result["assigned"] == 0
        assert result["skipped"] == 1

    def test_export_bom_cpl(self) -> None:
        from kicad_mcp.schema.board import Footprint
        from kicad_mcp.schema.common import Position
        from kicad_mcp.tools import TOOL_REGISTRY

        fps = [
            Footprint(
                library="Capacitor_SMD:C_0402_1005Metric",
                reference="C1",
                value="100nF",
                position=Position(x=10.0, y=20.0),
                layer="F.Cu",
            ),
            Footprint(
                library="Capacitor_SMD:C_0402_1005Metric",
                reference="C2",
                value="100nF",
                position=Position(x=15.0, y=25.0),
                layer="F.Cu",
            ),
            Footprint(
                library="Resistor_SMD:R_0402_1005Metric",
                reference="R1",
                value="10k",
                position=Position(x=30.0, y=40.0),
                layer="B.Cu",
            ),
        ]

        with patch("kicad_mcp.tools.jlcpcb.state") as mock_state:
            mock_state.get_footprints.return_value = fps
            result = TOOL_REGISTRY["jlcpcb_export_bom_cpl"].handler(
                assignments='{"C1": "C123456", "C2": "C123456"}'
            )

        assert result["bom_rows"] == 2  # 2 groups: 100nF caps + 10k resistor
        assert result["cpl_rows"] == 3
        assert "C1,C2" in result["bom_csv"]
        assert "C123456" in result["bom_csv"]
        assert "Top" in result["cpl_csv"]
        assert "Bottom" in result["cpl_csv"]

    def test_export_bom_cpl_grouping(self) -> None:
        """Same value+footprint should be grouped in BOM."""
        from kicad_mcp.schema.board import Footprint
        from kicad_mcp.schema.common import Position
        from kicad_mcp.tools import TOOL_REGISTRY

        fps = [
            Footprint(
                library="Resistor_SMD:R_0402_1005Metric",
                reference="R1",
                value="10k",
                position=Position(x=0.0, y=0.0),
                layer="F.Cu",
            ),
            Footprint(
                library="Resistor_SMD:R_0402_1005Metric",
                reference="R2",
                value="10k",
                position=Position(x=5.0, y=0.0),
                layer="F.Cu",
            ),
        ]

        with patch("kicad_mcp.tools.jlcpcb.state") as mock_state:
            mock_state.get_footprints.return_value = fps
            result = TOOL_REGISTRY["jlcpcb_export_bom_cpl"].handler()

        assert result["bom_rows"] == 1  # Same value+footprint grouped

    def test_export_bom_cpl_to_files(self, tmp_path) -> None:
        from kicad_mcp.schema.board import Footprint
        from kicad_mcp.schema.common import Position
        from kicad_mcp.tools import TOOL_REGISTRY

        fps = [
            Footprint(
                library="Resistor_SMD:R_0402_1005Metric",
                reference="R1",
                value="10k",
                position=Position(x=0.0, y=0.0),
                layer="F.Cu",
            ),
        ]

        with patch("kicad_mcp.tools.jlcpcb.state") as mock_state:
            mock_state.get_footprints.return_value = fps
            result = TOOL_REGISTRY["jlcpcb_export_bom_cpl"].handler(output_dir=str(tmp_path))

        assert "bom_path" in result
        assert "cpl_path" in result
        from pathlib import Path

        assert Path(result["bom_path"]).exists()
        assert Path(result["cpl_path"]).exists()

    def test_export_bom_cpl_invalid_json(self) -> None:
        from kicad_mcp.schema.board import Footprint
        from kicad_mcp.schema.common import Position
        from kicad_mcp.tools import TOOL_REGISTRY

        fps = [
            Footprint(
                library="Resistor_SMD:R_0402_1005Metric",
                reference="R1",
                value="10k",
                position=Position(x=0.0, y=0.0),
                layer="F.Cu",
            ),
        ]

        with patch("kicad_mcp.tools.jlcpcb.state") as mock_state:
            mock_state.get_footprints.return_value = fps
            result = TOOL_REGISTRY["jlcpcb_export_bom_cpl"].handler(assignments="not-valid-json")

        assert "error" in result

    def test_export_layer_mapping(self) -> None:
        """F.Cu maps to Top, B.Cu maps to Bottom in CPL."""
        from kicad_mcp.schema.board import Footprint
        from kicad_mcp.schema.common import Position
        from kicad_mcp.tools import TOOL_REGISTRY

        fps = [
            Footprint(
                library="Resistor_SMD:R_0402_1005Metric",
                reference="R1",
                value="10k",
                position=Position(x=0.0, y=0.0, angle=90.0),
                layer="F.Cu",
            ),
            Footprint(
                library="Resistor_SMD:R_0402_1005Metric",
                reference="R2",
                value="10k",
                position=Position(x=5.0, y=0.0, angle=45.0),
                layer="B.Cu",
            ),
        ]

        with patch("kicad_mcp.tools.jlcpcb.state") as mock_state:
            mock_state.get_footprints.return_value = fps
            result = TOOL_REGISTRY["jlcpcb_export_bom_cpl"].handler()

        lines = result["cpl_csv"].strip().split("\n")
        # Header + 2 data rows
        assert len(lines) == 3
        assert "Top" in lines[1]  # R1 on F.Cu
        assert "Bottom" in lines[2]  # R2 on B.Cu
        assert "90.0" in lines[1]
        assert "45.0" in lines[2]
