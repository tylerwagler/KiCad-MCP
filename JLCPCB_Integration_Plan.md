# JLCPCB Parts Integration

## Context

The KiCad MCP server (75 tools, 372 tests) has JLCPCB DRC presets but no parts catalog integration. Users want to search for JLCPCB-stocked parts, check availability/pricing, auto-assign LCSC part numbers to board components, and export JLCPCB-format BOM + CPL files for SMT assembly ordering.

## API Choice: jlcsearch (tscircuit)

**Primary**: `https://jlcsearch.tscircuit.com` — community API, no auth, clean JSON, documented.
- `GET /components/list.json?search=<query>&package=<pkg>&full=true&limit=N`
- Returns: `{components: [{lcsc, mfr, package, description, stock, price, basic, extra: {manufacturer, datasheet, moq, category, description}}]}`

Why not alternatives:
- JLCPCB internal endpoint: undocumented, could break
- LCSC OpenAPI: requires API key + signature (violates zero-config goal)

**HTTP client**: `httpx` 0.28.1 — already installed as transitive dep from FastMCP. Add as explicit dep in pyproject.toml.

---

## 4 New Tools (category: `"jlcpcb"`, all routed)

### 1. `jlcpcb_search_parts`
- **Params**: `query` (str, required), `package` (str, optional), `limit` (int, default 20)
- **Returns**: `{query, count, parts: [{lcsc, mfr, manufacturer, package, description, stock, price_usd, basic, datasheet_url, moq, category}]}`

### 2. `jlcpcb_check_availability`
- **Params**: `lcsc_code` (str, e.g. "C123456")
- **Returns**: `{found, in_stock, part: {...}}` or `{found: false, message: "..."}`

### 3. `jlcpcb_auto_assign`
- **Params**: `prefer_basic` (bool, default true), `references` (str, optional comma-sep filter)
- **Requires**: loaded board via `state.get_footprints()`
- **Logic**: For each component, search jlcsearch with value + extracted package, rank by basic-first then stock, assign best match
- **Returns**: `{assigned, skipped, errors, assignments: [{reference, value, footprint, lcsc, mfr, description, basic, confidence, alternatives}], skipped_details, error_details}`

### 4. `jlcpcb_export_bom_cpl`
- **Params**: `output_dir` (str, optional), `assignments` (str, optional JSON `{"R1": "C123456"}`)
- **Requires**: loaded board
- **BOM CSV**: `Comment,Designator,Footprint,LCSC Part #` (grouped by value+footprint+lcsc)
- **CPL CSV**: `Designator,Mid X,Mid Y,Layer,Rotation` (F.Cu→"Top", B.Cu→"Bottom")
- **Returns**: `{bom_csv, cpl_csv, bom_rows, cpl_rows, bom_path?, cpl_path?}`

---

## Data Models

`JlcpcbPart` — frozen dataclass with `lcsc` (int), `mfr`, `package`, `description`, `stock`, `price`, `basic`, `manufacturer`, `datasheet_url`, `moq`, `category`. Property `lcsc_code` → `"C{lcsc}"`. Method `to_dict()`.

`JlcpcbSearchResult` — `query`, `count`, `parts: list[JlcpcbPart]`. Method `to_dict()`.

`JlcpcbAssignment` — `reference`, `value`, `footprint`, `lcsc`, `mfr`, `description`, `basic`, `confidence`, `alternatives`. Method `to_dict()`.

`JlcpcbApiError` — exception for API failures.

## Package Extraction

`extract_package_from_library(library: str) -> str | None` — regex patterns to extract JLCPCB-compatible package names from KiCad library identifiers:
- `"Capacitor_SMD:C_0805_2012Metric"` → `"0805"`
- `"Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"` → `"SOIC-8"`
- `"Package_DFN_QFN:QFN-32-1EP_5x5mm"` → `"QFN-32"`
- Unknown → `None` (search without package filter, lower confidence)

---

## Files

| File | Action | Content |
|------|--------|---------|
| `src/kicad_mcp/manufacturers/jlcpcb.py` | **NEW** | Data models, API client, package extraction |
| `src/kicad_mcp/tools/jlcpcb.py` | **NEW** | 4 tool handlers + `register_tool()` calls |
| `src/kicad_mcp/tools/__init__.py` | **EDIT** | Add `jlcpcb` to imports |
| `src/kicad_mcp/manufacturers/__init__.py` | **EDIT** | Re-export JLCPCB types |
| `pyproject.toml` | **EDIT** | Add `httpx>=0.25` to dependencies |
| `tests/unit/test_jlcpcb.py` | **NEW** | ~30 tests with mocked HTTP |

## Key Existing Code

- `schema/board.py:70` — `Footprint` dataclass: `.reference`, `.value`, `.library`, `.position` (Position with `.x`, `.y`, `.angle`), `.layer`
- `schema/common.py:10` — `Position` dataclass: `.x`, `.y`, `.angle`
- `state.py` — `get_footprints()` returns `list[Footprint]`
- `tools/export.py:131` — existing `export_bom` handler (pattern reference)
- `tools/registry.py` — `register_tool(name, description, parameters, handler, category, direct)`
- `manufacturers/presets.py` — JLCPCB DRC presets already exist here

---

## Execution Order

### Phase 1: Foundation
1. Add `httpx>=0.25` to pyproject.toml
2. Create `manufacturers/jlcpcb.py` — data models, `_parse_part()`, `_extract_lowest_price()`, `search_parts()`, `get_part_details()`, `extract_package_from_library()`
3. Update `manufacturers/__init__.py` to re-export

### Phase 2: Tools
4. Create `tools/jlcpcb.py` — 4 handlers + registrations
5. Add import in `tools/__init__.py`

### Phase 3: Tests
6. Create `tests/unit/test_jlcpcb.py`:
   - `TestParsePartData` (~6 tests): field extraction, price parsing, basic flag, lcsc_code property
   - `TestPackageExtraction` (~7 tests): 0805, 0402, SOIC-8, SOT-23, QFN-32, TSSOP, unknown
   - `TestSearchParts` (~5 tests): success, with package, timeout, HTTP error, empty
   - `TestGetPartDetails` (~3 tests): found, not found, C-prefix stripping
   - `TestToolHandlers` (~10 tests): search, availability, auto-assign (basic pref, DNP skip, specific refs, partial failure), BOM/CPL export (content format, assignments, grouping, layer mapping, file write)

### Phase 4: Verify
7. `uv run pytest tests/ -v` — all pass
8. `uv run ruff check . && uv run ruff format --check .`
9. Manual smoke test: `list_tool_categories` shows "jlcpcb" with 4 tools

**Target**: 79 tools, ~400 tests, 0 lint errors.
