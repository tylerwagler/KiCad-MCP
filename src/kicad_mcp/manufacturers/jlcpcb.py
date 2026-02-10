"""JLCPCB parts catalog — API client, data models, and package extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

# ── Exceptions ──────────────────────────────────────────────────────


class JlcpcbApiError(Exception):
    """Raised when the JLCPCB parts API returns an error or is unreachable."""


# ── Data Models ─────────────────────────────────────────────────────

JLCSEARCH_BASE = "https://jlcsearch.tscircuit.com"


@dataclass(frozen=True)
class JlcpcbPart:
    """A single JLCPCB component from the parts catalog."""

    lcsc: int
    mfr: str
    package: str
    description: str
    stock: int
    price: float
    basic: bool
    manufacturer: str = ""
    datasheet_url: str = ""
    moq: int = 1
    category: str = ""

    @property
    def lcsc_code(self) -> str:
        return f"C{self.lcsc}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lcsc": self.lcsc_code,
            "mfr": self.mfr,
            "manufacturer": self.manufacturer,
            "package": self.package,
            "description": self.description,
            "stock": self.stock,
            "price_usd": self.price,
            "basic": self.basic,
            "datasheet_url": self.datasheet_url,
            "moq": self.moq,
            "category": self.category,
        }


@dataclass
class JlcpcbSearchResult:
    """Result of a JLCPCB parts search."""

    query: str
    count: int
    parts: list[JlcpcbPart] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "count": self.count,
            "parts": [p.to_dict() for p in self.parts],
        }


@dataclass
class JlcpcbAssignment:
    """A component-to-JLCPCB-part assignment."""

    reference: str
    value: str
    footprint: str
    lcsc: str
    mfr: str
    description: str
    basic: bool
    confidence: str  # "high", "medium", "low"
    alternatives: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "value": self.value,
            "footprint": self.footprint,
            "lcsc": self.lcsc,
            "mfr": self.mfr,
            "description": self.description,
            "basic": self.basic,
            "confidence": self.confidence,
            "alternatives": self.alternatives,
        }


# ── Package Extraction ──────────────────────────────────────────────

# Patterns: KiCad library id → JLCPCB-compatible package name
_PACKAGE_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    # Imperial sizes: 0402, 0603, 0805, 1206, etc.
    (re.compile(r"(\d{4})_\d{4}Metric"), 1),
    # SOT-23, SOT-223, etc.
    (re.compile(r"(SOT-\d+)"), 1),
    # SOIC-N
    (re.compile(r"(SOIC-\d+)"), 1),
    # TSSOP-N
    (re.compile(r"(TSSOP-\d+)"), 1),
    # QFN-N
    (re.compile(r"(QFN-\d+)"), 1),
    # QFP/LQFP/TQFP-N
    (re.compile(r"([LT]?QFP-\d+)"), 1),
    # DFN-N
    (re.compile(r"(DFN-\d+)"), 1),
    # BGA-N
    (re.compile(r"(BGA-\d+)"), 1),
    # SMA, SMB, SMC (diodes)
    (re.compile(r"\b(SM[ABC])\b"), 1),
    # TO-252, TO-263, etc.
    (re.compile(r"(TO-\d+)"), 1),
]


def extract_package_from_library(library: str) -> str | None:
    """Extract JLCPCB-compatible package name from a KiCad library identifier.

    Examples:
        "Capacitor_SMD:C_0805_2012Metric" → "0805"
        "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm" → "SOIC-8"
        "Package_DFN_QFN:QFN-32-1EP_5x5mm" → "QFN-32"
        "Unknown_Package:Foo" → None
    """
    for pattern, group in _PACKAGE_PATTERNS:
        m = pattern.search(library)
        if m:
            return m.group(group)
    return None


# ── API Client ──────────────────────────────────────────────────────


def _parse_part(data: dict[str, Any]) -> JlcpcbPart:
    """Parse a single component from the jlcsearch API response."""
    extra = data.get("extra", {}) or {}
    price = _extract_lowest_price(data.get("price", 0))
    return JlcpcbPart(
        lcsc=int(data.get("lcsc", 0)),
        mfr=data.get("mfr", ""),
        package=data.get("package", ""),
        description=data.get("description", ""),
        stock=int(data.get("stock", 0)),
        price=price,
        basic=bool(data.get("basic", False)),
        manufacturer=extra.get("manufacturer", ""),
        datasheet_url=extra.get("datasheet", ""),
        moq=int(extra.get("moq", 1) or 1),
        category=extra.get("category", ""),
    )


def _extract_lowest_price(price_val: Any) -> float:
    """Extract a numeric price from various API formats.

    The API may return a float, a string like "$0.0045", or a list of
    price breaks like [{"qty": 1, "price": 0.005}, ...].
    """
    if isinstance(price_val, (int, float)):
        return float(price_val)
    if isinstance(price_val, str):
        cleaned = price_val.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    if isinstance(price_val, list) and price_val:
        # List of price breaks — return lowest qty price
        try:
            return float(price_val[0].get("price", 0))
        except (AttributeError, ValueError, IndexError):
            return 0.0
    return 0.0


def search_parts(
    query: str,
    package: str | None = None,
    limit: int = 20,
    timeout: float = 10.0,
) -> JlcpcbSearchResult:
    """Search the JLCPCB parts catalog via jlcsearch API.

    Args:
        query: Search string (e.g., "100nF", "STM32F103").
        package: Optional package filter (e.g., "0805", "SOIC-8").
        limit: Max results to return.
        timeout: HTTP timeout in seconds.
    """
    params: dict[str, str | int] = {
        "search": query,
        "full": "true",
        "limit": limit,
    }
    if package:
        params["package"] = package

    try:
        resp = httpx.get(
            f"{JLCSEARCH_BASE}/components/list.json",
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
    except httpx.TimeoutException as e:
        raise JlcpcbApiError(f"JLCPCB search timed out after {timeout}s") from e
    except httpx.HTTPStatusError as e:
        raise JlcpcbApiError(f"JLCPCB API error: HTTP {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise JlcpcbApiError(f"JLCPCB API request failed: {e}") from e

    data = resp.json()
    components = data.get("components", [])
    parts = [_parse_part(c) for c in components]
    return JlcpcbSearchResult(query=query, count=len(parts), parts=parts)


def get_part_details(
    lcsc_code: str,
    timeout: float = 10.0,
) -> JlcpcbPart | None:
    """Look up a specific JLCPCB part by LCSC code.

    Args:
        lcsc_code: LCSC part number (e.g., "C123456" or "123456").
        timeout: HTTP timeout in seconds.
    """
    # Strip 'C' prefix if present
    code = lcsc_code.lstrip("Cc")

    result = search_parts(query=f"C{code}", limit=5, timeout=timeout)
    for part in result.parts:
        if str(part.lcsc) == code:
            return part
    return None
