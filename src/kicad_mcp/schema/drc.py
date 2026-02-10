"""Typed data models for DRC results and export operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DrcViolation:
    """A single DRC violation."""

    type: str
    severity: str  # "error", "warning"
    description: str
    position: dict[str, float] | None = None
    items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": self.type,
            "severity": self.severity,
            "description": self.description,
        }
        if self.position:
            d["position"] = self.position
        if self.items:
            d["items"] = self.items
        return d


@dataclass
class DrcResult:
    """Result of running DRC on a board."""

    passed: bool
    error_count: int
    warning_count: int
    violations: list[DrcViolation] = field(default_factory=list)
    report_path: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "violations": [v.to_dict() for v in self.violations],
            "report_path": self.report_path,
        }
        if self.message:
            d["message"] = self.message
        return d


@dataclass
class ExportResult:
    """Result of an export operation."""

    success: bool
    output_path: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output_path": self.output_path,
            "message": self.message,
        }
