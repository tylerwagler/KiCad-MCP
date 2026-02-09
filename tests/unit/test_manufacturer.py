"""Tests for manufacturer DRC presets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.manufacturers import PRESETS

BLINKY_PATH = Path(r"C:\Users\tyler\Dev\repos\test_PCB\blinky.kicad_pcb")


class TestManufacturerPresets:
    def test_presets_loaded(self) -> None:
        assert len(PRESETS) == 6

    def test_jlcpcb_standard_exists(self) -> None:
        assert "jlcpcb_standard" in PRESETS

    def test_oshpark_2layer_exists(self) -> None:
        assert "oshpark_2layer" in PRESETS

    def test_pcbway_standard_exists(self) -> None:
        assert "pcbway_standard" in PRESETS

    def test_preset_to_dict_serializable(self) -> None:
        for name, preset in PRESETS.items():
            d = preset.to_dict()
            json_str = json.dumps(d)
            assert len(json_str) > 50, f"Preset {name} produced empty dict"

    def test_jlcpcb_standard_rules(self) -> None:
        p = PRESETS["jlcpcb_standard"]
        assert p.min_trace_width == 0.127
        assert p.min_clearance == 0.127
        assert p.max_layers == 2

    def test_pcbway_advanced_capabilities(self) -> None:
        p = PRESETS["pcbway_advanced"]
        assert p.supports_blind_vias is True
        assert p.supports_buried_vias is True
        assert p.supports_impedance_control is True
        assert p.max_layers == 14


class TestCheckViolations:
    def test_no_violations(self) -> None:
        p = PRESETS["jlcpcb_standard"]
        violations = p.check_violations(
            trace_width=0.2,
            clearance=0.2,
            via_diameter=0.6,
            via_drill=0.3,
            layer_count=2,
            board_thickness=1.6,
        )
        assert len(violations) == 0

    def test_trace_width_violation(self) -> None:
        p = PRESETS["jlcpcb_standard"]
        violations = p.check_violations(trace_width=0.05)  # Too thin
        assert len(violations) == 1
        assert violations[0]["rule"] == "min_trace_width"

    def test_clearance_violation(self) -> None:
        p = PRESETS["jlcpcb_standard"]
        violations = p.check_violations(clearance=0.05)
        assert len(violations) == 1
        assert violations[0]["rule"] == "min_clearance"

    def test_layer_count_violation(self) -> None:
        p = PRESETS["jlcpcb_standard"]
        violations = p.check_violations(layer_count=4)
        assert len(violations) == 1
        assert violations[0]["rule"] == "max_layers"

    def test_board_thickness_too_thin(self) -> None:
        p = PRESETS["jlcpcb_standard"]
        violations = p.check_violations(board_thickness=0.3)
        assert len(violations) == 1
        assert violations[0]["rule"] == "min_board_thickness"

    def test_board_thickness_too_thick(self) -> None:
        p = PRESETS["jlcpcb_standard"]
        violations = p.check_violations(board_thickness=3.0)
        assert len(violations) == 1
        assert violations[0]["rule"] == "max_board_thickness"

    def test_multiple_violations(self) -> None:
        p = PRESETS["jlcpcb_standard"]
        violations = p.check_violations(
            trace_width=0.01,
            clearance=0.01,
            via_drill=0.05,
        )
        assert len(violations) == 3


@pytest.mark.skipif(not BLINKY_PATH.exists(), reason="Test fixture not available")
class TestManufacturerToolHandlers:
    @pytest.fixture(autouse=True)
    def _load_board(self) -> None:
        from kicad_mcp import state

        state.load_board(str(BLINKY_PATH))

    def test_list_presets(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["list_manufacturer_presets"].handler()
        assert result["count"] == 6

    def test_get_preset_rules(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["get_preset_rules"].handler(preset_name="jlcpcb_standard")
        assert result["manufacturer"] == "JLCPCB"
        assert "rules" in result

    def test_get_unknown_preset(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["get_preset_rules"].handler(preset_name="nonexistent")
        assert "error" in result

    def test_check_manufacturability(self) -> None:
        from kicad_mcp.tools import TOOL_REGISTRY

        result = TOOL_REGISTRY["check_manufacturability"].handler(preset_name="jlcpcb_standard")
        assert result["manufacturer"] == "JLCPCB"
        assert result["board"] == "blinky"
        assert "passed" in result
        assert "violations" in result
