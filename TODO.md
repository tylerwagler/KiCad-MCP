# KiCad MCP — TODO

## Current State
- 90 tools, 577 tests, 100% pass, 14 categories
- Full featureparity with old Node.js server (which had 78% pass rate)
- Best-in-class among 6 competing KiCad MCP repos
- CI pipeline (GitHub Actions), integration tests, performance benchmarks
- IPC API integration complete (KiCad 9+ only)
- Schematic-PCB sync complete (forward/back annotation)
- JLCPCB parts integration complete (catalog search, BOM export)

---

## Remaining Gaps (from competitive analysis)

### KiCad IPC API Integration
- [x] Wire up `backends/ipc_api.py` for real-time KiCad UI sync (KiCad 9+ only)
- [x] Live board state push/pull without file round-trips
- [x] Highlight components in KiCad GUI from MCP commands
- [x] Bi-directional selection sync (click in KiCad -> MCP knows, MCP selects -> KiCad highlights)

### Schematic-PCB Sync
- [x] Forward annotation: push schematic changes to PCB
- [x] Back annotation: push PCB reference changes to schematic
- [x] Cross-reference validation (schematic vs PCB mismatch detection)

### JLCPCB Parts Integration
- [x] Live JLCPCB parts catalog search (basic/extended stock)
- [x] Part availability + pricing lookup
- [x] Auto-assign LCSC part numbers to BOM
- [x] JLCPCB-specific BOM + CPL export

---

## New Feature Ideas

### Auto-Routing
- [x] Simple point-to-point auto-router (Manhattan/45-degree)
- [ ] Differential pair routing helper
- [ ] Length-matched routing for high-speed signals
- [ ] Fan-out via generation for BGA/QFN pads

### Auto-Placement
- [x] Force-directed component placement with SA cooling
- [x] Placement evaluation (HPWL metric, overlap detection)
- [ ] Constraint-aware placement (keep-out zones, thermal grouping)
- [ ] Component placement suggestions (group by function, minimize trace length)

### Design Assistance
- [ ] Power delivery network analysis (voltage drop, current density)
- [ ] Thermal analysis (identify hot spots from copper area + power dissipation)
- [ ] Impedance calculator (microstrip/stripline for controlled impedance traces)

### Advanced DRC
- [ ] Custom DRC rules engine (beyond manufacturer presets)
- [ ] Antenna rule checking for RF designs
- [ ] High-voltage clearance rules (creepage/clearance per IPC-2221)
- [ ] Assembly-specific checks (tombstoning risk, solder paste ratio)

### Import/Export
- [ ] Import from Eagle (.brd/.sch)
- [ ] Import from Altium (limited — ASCII format)
- [ ] Export interactive BOM (like InteractiveHtmlBom plugin)
- [ ] Export 3D render (ray-traced PNG/JPEG via kicad-cli)
- [ ] ODB++ export for advanced manufacturing

### Multi-Board / Hierarchy
- [ ] Hierarchical schematic support (sub-sheets)
- [ ] Multi-board project management (backplane + daughter cards)
- [ ] Connector pin mapping between boards

### Version Control Integration
- [ ] Visual diff for .kicad_pcb changes (render before/after)
- [ ] Schematic diff (component added/removed/moved)
- [ ] Design review comments anchored to board coordinates

### Documentation Generation
- [ ] Auto-generate assembly instructions from board data
- [ ] Pinout diagram generation from schematic
- [ ] Generate test point documentation
- [ ] Create fabrication notes from design rules + stackup

### Library Management
- [ ] Create custom footprints from parameters (wizard-style)
- [ ] Footprint pad calculator (IPC-7351 land patterns)
- [ ] Symbol generator from datasheet pin tables
- [ ] Library health check (unused symbols, outdated footprints)

---

## Tech Debt / Quality

- [x] Update CLAUDE.md competitive table — all patterns now implemented, remove "Planned" status
- [x] Integration tests for new session manager methods (12 tests covering full commit/rollback workflows)
- [x] Performance benchmarks for large boards (24 tests, up to 500 components)
- [x] CI pipeline (GitHub Actions: pytest + ruff + mypy on Python 3.11-3.13, Ubuntu + Windows)
- [x] Pagination (limit/offset) for listing tools to prevent context window overflow
- [x] Global response truncation safety net in execute_tool (50KB cap)

### Recent Tech Debt (from production hardening)
- [ ] Fix kicad-cli `--format plain` validation issue - use `json` format instead
- [ ] Add integration test for real KiCad IPC API (requires KiCad installation)
- [ ] Improve documentation for optional dependencies (kipy, pcbnew)
