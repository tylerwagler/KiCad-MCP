"""Unit tests for DRC report parsing (no kicad-cli required)."""

from __future__ import annotations

from kicad_mcp.backends.kicad_cli import KiCadCli
from kicad_mcp.schema.drc import DrcResult


class TestParseDrcReport:
    def test_empty_report_passes(self) -> None:
        report = {"violations": [], "unconnected_items": []}
        result = KiCadCli._parse_drc_report(report, "/tmp/test.json")
        assert result.passed is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_violations_counted(self) -> None:
        report = {
            "violations": [
                {"type": "clearance", "severity": "error", "description": "Clearance violation"},
                {"type": "silk_overlap", "severity": "warning", "description": "Silk overlap"},
            ],
            "unconnected_items": [],
        }
        result = KiCadCli._parse_drc_report(report, "/tmp/test.json")
        assert result.passed is False
        assert result.error_count == 1
        assert result.warning_count == 1
        assert len(result.violations) == 2

    def test_warnings_only_still_passes(self) -> None:
        report = {
            "violations": [
                {"type": "silk_overlap", "severity": "warning", "description": "Silk overlap"},
            ],
            "unconnected_items": [],
        }
        result = KiCadCli._parse_drc_report(report, "/tmp/test.json")
        assert result.passed is True
        assert result.error_count == 0
        assert result.warning_count == 1

    def test_unconnected_items_are_errors(self) -> None:
        report = {
            "violations": [],
            "unconnected_items": [
                {"description": "Net GND not connected", "items": []},
            ],
        }
        result = KiCadCli._parse_drc_report(report, "/tmp/test.json")
        assert result.passed is False
        assert result.error_count == 1

    def test_stderr_included_when_no_errors(self) -> None:
        """When parsed report has no errors but kicad-cli had stderr, include it."""
        report = {"violations": [], "unconnected_items": []}
        result = KiCadCli._parse_drc_report(
            report, "/tmp/test.json", stderr="Board has no Edge.Cuts"
        )
        assert result.passed is True
        assert result.message == "Board has no Edge.Cuts"

    def test_stderr_not_included_when_errors_present(self) -> None:
        """When errors are present, the violations speak for themselves."""
        report = {
            "violations": [
                {"type": "clearance", "severity": "error", "description": "Clearance violation"},
            ],
            "unconnected_items": [],
        }
        result = KiCadCli._parse_drc_report(report, "/tmp/test.json", stderr="some stderr noise")
        assert result.message == ""


class TestDrcResultToDict:
    def test_message_included_when_set(self) -> None:
        result = DrcResult(
            passed=False,
            error_count=0,
            warning_count=0,
            message="DRC report unavailable: kicad-cli produced no DRC report",
        )
        d = result.to_dict()
        assert "message" in d
        assert "unavailable" in d["message"]

    def test_message_omitted_when_empty(self) -> None:
        result = DrcResult(passed=True, error_count=0, warning_count=0)
        d = result.to_dict()
        assert "message" not in d
