"""Unit tests for KiCad format-version detection.

Verifies that file-format version stamps are detected from kicad-cli when
available and fall back to constants when it is not — so file creation never
hard-depends on KiCad being installed.
"""

from __future__ import annotations

import re

import pytest

import kicad_mcp.backends.format_version as fv
from kicad_mcp.backends.kicad_cli import KiCadCli, KiCadCliNotFound

_YYYYMMDD = re.compile(r"^\d{8}$")


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts and ends with a clean detection cache."""
    fv.detect_format_stamps.cache_clear()
    yield
    fv.detect_format_stamps.cache_clear()


class TestGeneratorVersionParsing:
    def test_full_semver(self):
        assert fv._parse_generator_version("10.0.0") == "10.0"

    def test_two_component(self):
        assert fv._parse_generator_version("9.1") == "9.1"

    def test_with_suffix(self):
        assert fv._parse_generator_version("9.0.2-rc1") == "9.0"

    def test_with_surrounding_text(self):
        assert fv._parse_generator_version("KiCad 10.0.0 release") == "10.0"

    def test_unparseable(self):
        assert fv._parse_generator_version("garbage") is None


class TestFallback:
    def test_returns_fallback_when_cli_missing(self, monkeypatch):
        def boom(self, *a, **k):
            raise KiCadCliNotFound("simulated")

        monkeypatch.setattr(KiCadCli, "__init__", boom)
        stamps = fv.detect_format_stamps()

        assert stamps is fv._FALLBACK_STAMPS
        assert stamps.detected is False
        assert stamps.pcb_version == fv._FALLBACK_PCB_VERSION
        assert stamps.sch_version == fv._FALLBACK_SCH_VERSION
        assert stamps.footprint_version == fv._FALLBACK_FP_VERSION
        assert stamps.symbol_version == fv._FALLBACK_SYM_VERSION
        assert stamps.generator_version == fv._FALLBACK_GENERATOR_VERSION

    def test_per_field_fallback_when_probe_fails(self, monkeypatch):
        # CLI exists and reports a version, but every upgrade probe fails.
        monkeypatch.setattr(KiCadCli, "__init__", lambda self, *a, **k: None)
        monkeypatch.setattr(KiCadCli, "version", lambda self: "11.5.0")

        def fail_upgrade(self, *a, **k):
            raise RuntimeError("probe failed")

        monkeypatch.setattr(KiCadCli, "upgrade", fail_upgrade)
        stamps = fv.detect_format_stamps()

        # generator_version comes from `version()`, format epochs fall back.
        assert stamps.generator_version == "11.5"
        assert stamps.detected is False
        assert stamps.pcb_version == fv._FALLBACK_PCB_VERSION
        assert stamps.symbol_version == fv._FALLBACK_SYM_VERSION

    def test_result_is_cached(self, monkeypatch):
        calls = {"n": 0}

        def counting_init(self, *a, **k):
            calls["n"] += 1
            raise KiCadCliNotFound("simulated")

        monkeypatch.setattr(KiCadCli, "__init__", counting_init)
        fv.detect_format_stamps()
        fv.detect_format_stamps()
        assert calls["n"] == 1


@pytest.mark.skipif(not KiCadCli.is_available(), reason="kicad-cli not installed")
class TestLiveDetection:
    def test_detects_valid_stamps(self):
        stamps = fv.detect_format_stamps()
        assert stamps.detected is True
        for v in (
            stamps.pcb_version,
            stamps.sch_version,
            stamps.footprint_version,
            stamps.symbol_version,
        ):
            assert _YYYYMMDD.match(v), f"not a YYYYMMDD stamp: {v!r}"
        assert re.match(r"^\d+\.\d+$", stamps.generator_version)

    def test_created_files_need_no_upgrade(self, tmp_path):
        """Files we create are already at the installed format (no upgrade)."""
        from kicad_mcp.tools.project import _minimal_kicad_pcb, _minimal_kicad_sch

        cli = KiCadCli()
        pcb = tmp_path / "t.kicad_pcb"
        pcb.write_text(_minimal_kicad_pcb(50, 30))
        sch = tmp_path / "t.kicad_sch"
        sch.write_text(_minimal_kicad_sch())

        # `upgrade` without --force is a no-op when already current; we assert
        # the stamp the generator wrote matches what a forced upgrade produces.
        cli.upgrade("pcb", "./t.kicad_pcb", cwd=str(tmp_path))
        cli.upgrade("sch", "./t.kicad_sch", cwd=str(tmp_path))
        stamps = fv.detect_format_stamps()
        assert f"(version {stamps.pcb_version})" in pcb.read_text()
        assert f"(version {stamps.sch_version})" in sch.read_text()
