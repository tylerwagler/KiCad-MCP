# KiCad MCP — TODO

## Current State
- 75 tools, 315 tests, 100% pass, 12 categories
- Full feature parity with old Node.js server (which had 78% pass rate)
- Best-in-class among 6 competing KiCad MCP repos

---

## Remaining Gaps (from competitive analysis)

### KiCad IPC API Integration
- [ ] Wire up `backends/ipc_api.py` for real-time KiCad UI sync (KiCad 9+ only)
- [ ] Live board state push/pull without file round-trips
- [ ] Highlight components in KiCad GUI from MCP commands
- [ ] Bi-directional selection sync (click in KiCad -> MCP knows, MCP selects -> KiCad highlights)

### Schematic-PCB Sync
- [ ] Forward annotation: push schematic changes to PCB
- [ ] Back annotation: push PCB reference changes to schematic
- [ ] Cross-reference validation (schematic vs PCB mismatch detection)

### JLCPCB Parts Integration
- [ ] Live JLCPCB parts catalog search (basic/extended stock)
- [ ] Part availability + pricing lookup
- [ ] Auto-assign LCSC part numbers to BOM
- [ ] JLCPCB-specific BOM + CPL export

---

## New Feature Ideas

### Auto-Routing
- [ ] Simple point-to-point auto-router (Manhattan/45-degree)
- [ ] Differential pair routing helper
- [ ] Length-matched routing for high-speed signals
- [ ] Fan-out via generation for BGA/QFN pads

### Design Assistance
- [ ] Component placement suggestions (group by function, minimize trace length)
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

- [ ] Update CLAUDE.md competitive table — all patterns now implemented, remove "Planned" status
- [ ] Add type stubs for `pcbnew` module (for IDE support when available)
- [ ] Integration tests for new session manager methods (currently unit-tested only)
- [ ] Performance benchmarks for large boards (100+ component S-expr parsing)
- [ ] CI pipeline (GitHub Actions: pytest + ruff + mypy)
