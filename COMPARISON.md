# Comparison: KiCad-MCP vs. mixelpixx/KiCAD-MCP-Server

A competitive analysis of this project against
[mixelpixx/KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server),
one of the six existing KiCad MCP servers this project draws patterns from.

_Last updated: 2026-06-17_

## Headline architecture differences

| | **This project (KiCad-MCP)** | **mixelpixx/KiCAD-MCP-Server** |
|---|---|---|
| Stack | Pure Python (FastMCP) | Python + TypeScript (two-process) |
| KiCad communication | 3 backends with fallback: **S-expr parser**, kicad-cli, IPC (kipy) | `pcbnew` SWIG + IPC (kipy) |
| Reads without KiCad installed | ✅ Yes (pure-Python parser) | ❌ No — requires `pcbnew` |
| Total tools | 112 | 122 |
| Tool router | ✅ 9 direct + 103 routed + 4 meta | ✅ 18 direct + 65 routed + 35 always-on + 4 meta |
| Undo / safety model | ✅ Query-before-commit transactions, undo stack, rollback | ❌ Snapshots only ("operations are permanent unless reverted") |
| Dependencies | 2 core (FastMCP, httpx) + 1 optional (kipy) | KiCad 9, Node 18+, Python 3.11+, Java/Docker |

Both projects share DNA: this project's CLAUDE.md credits mixelpixx as the source
for the tool-router (context-reduction) and JLCPCB patterns, and both converged on
nearly identical meta-tool names (`list_tool_categories`, `get_category_tools`,
`search_tools`, `execute_tool`). They diverged on two fundamental bets.

### Bet 1 — Pure-Python S-expression parser vs. `pcbnew`

- **Our advantage:** read/analyze any `.kicad_pcb`/`.kicad_sch`/`.kicad_mod`/`.kicad_pro`
  with zero KiCad install, zero subprocess, and round-trip formatting fidelity.
  Faster, more portable, far easier to test (no GUI in the loop).
- **Their advantage:** `pcbnew` provides KiCad's own geometry/connectivity engine
  for free — real ratsnest, true DRC geometry, footprint instantiation from libraries.

### Bet 2 — Real transaction model vs. snapshots

Our `start_session → query_move → apply → undo → commit/rollback` is a materially
better safety model for an LLM that makes mistakes. mixelpixx documents "no built-in
undo system." This is our strongest differentiator.

## Where mixelpixx is ahead (gaps to close)

Most of these are tractable for them because `pcbnew` makes them cheap:

1. **Schematic depth** — 27 schematic tools (full wiring, net labels, pin-location
   discovery with rotation, geometric net tracing, ERC, netlist gen) vs. our 10.
   Our schematic parsing is explicitly partial.
2. **Footprint / symbol creation** — they generate custom footprints and symbols via
   S-expr injection. We only read/search libraries.
3. **Freerouting integration** — a real autorouter via Java/Docker (DSN export /
   SES import). Our autoroute is 3 home-grown A*-based tools — adequate for simple
   cases, not competitive on real boards.
4. **Visual feedback** — `get_board_2d_view`, snapshots, session logs.
5. **Convenience placement** — `place_component_array`, `align_components`,
   `duplicate_component`, `group_components`.
6. **Differential-pair routing**, datasheet enrichment, `import_svg_logo`.
7. **JLCPCB catalog** — full 2.5M-part downloadable SQLite catalog vs. our live API
   query (ours is lighter, but no offline/bulk lookups).

## Where this project is ahead

- **Transaction / undo model** (their biggest gap).
- **Install-free reads** + zero-dependency parser (2 core deps vs. KiCad+Node+Python+Java/Docker).
- **Round-trip fidelity** preserving formatting/comments — important for version-controlled files.
- **Test rigor** — ~360 tests, strict mypy, ruff.
- **MCP three-pillar completeness** — 5 Resources + 3 Prompts (they have 8 resources, no prompts).
- **Manufacturer DRC presets with `check_violations()`** (JLCPCB/OSHPark/PCBWay, tiered) —
  they have `set_design_rules` but no preset library.

## Assessment

This is not a clone. We made the harder, cleaner architectural choices (pure-Python
parsing + real transactions); they made the pragmatic, feature-rich choice (lean on
`pcbnew`, ship more verbs).

- For **safety, portability, and correctness**, ours is the better-engineered base.
- For **breadth of "can it actually do X on a real board"**, they are ahead today —
  especially schematic editing, footprint/symbol creation, and real autorouting.

## Gap-closing roadmap (highest leverage first)

1. ✅ **Freerouting integration** — _done_ (see below).
2. **Deepen schematic tools** — close the 10 → 27 gap; our parser already reads
   `.kicad_sch`, so this is incremental.
3. **Footprint / symbol creation** — we already have round-trip S-expr write;
   generating `.kicad_mod`/`.kicad_sym` is within reach without KiCad.
4. ✅ **Visual feedback** (`get_board_2d_view` via kicad-cli SVG render) — _done_.
5. ✅ **Convenience placement tools** — `duplicate_component`, `place_component_array`,
   `align_components` (left/right/top/bottom, center, distribute); `group_components`
   already existed — _done_.

### Completed: kipy live PCB backend, hybrid live-preferred (2026-06-17)

Stopped reimplementing KiCad's engine where the IPC API (kipy ≥ 0.7) can supply it.
This is a *hybrid* — kipy requires a running KiCad GUI and exposes no schematics, DRC,
export, or ratsnest, so the parser (reads/schematics/fidelity), kicad-cli (DRC/export),
and Freerouting (routing) all remain.

- **Phase 0–1:** installed and introspected the real kipy 0.7.1 API and rewrote the
  write paths, which were speculative and wrong: `Track.layer` is a `BoardLayer` enum,
  `Track.net` is a `Net` object (not `.net_code`), `Via` uses `diameter`/`drill_diameter`,
  `Zone` outlines build from `PolygonWithHoles`. Added an atomic `commit()` context
  (`begin`/`push`/`drop`) so each write is one undo step. **Net codes are deprecated in
  KiCad 10** → net resolution now binds by name. Hardened `connect()` to do a real
  round-trip (kipy connects lazily, so the old code reported false "connected").
- **Phase 2:** new `board_provider.py` — live-preferred reads. `state.get_summary`/
  `get_footprints` return live board data when KiCad is connected, else the parser;
  consumers unchanged. `get_document()` stays parser-only (mutations/DSN need the tree).
- **Phase 3:** session commits translate all applied changes into **one atomic kipy
  commit** (binding nets by name), replacing per-change best-effort pushes.
- **Phase 4:** deprecated the built-in A* router (`auto_route_*`, `preview_route`) in
  favor of `autoroute_freerouting`; kept ratsnest (kipy has no ratsnest API). DSN export
  now uses the **real Edge.Cuts outline polygon** (chained from straight segments) instead
  of the bbox rectangle — read from the parsed file offline, or live from kipy
  `get_shapes()` when KiCad is connected; bbox remains the fallback (curved outlines).
  (Pad geometry was already read accurately from the file; live pad→image reconstruction
  isn't reliably supported by the kipy API and adds no routing value, so it's not used.)
- **Phase 5:** `scripts/verify_kipy.py` (manual live harness) + a gated
  `tests/integration/test_ipc_integration.py`; mock-based unit tests construct **real**
  kipy objects to verify field/enum/coordinate correctness.

**Verification caveat:** the dev environment is headless, so the live *transport* is
unverified here — correctness rests on the real-API introspection + object-level tests
until `scripts/verify_kipy.py` is run against a live KiCad.

### Completed: Freerouting integration (2026-06-17)

Real autorouting via Freerouting, implemented entirely without `pcbnew` — we
generate the Specctra DSN from our own board model and parse the SES result back.
Tool count 116 → 120; new `freerouting` category: `check_freerouting`,
`export_dsn`, `import_ses`, `autoroute_freerouting`.

- **`specctra/dsn.py`** — pure-Python Specctra DSN generator from the parsed board
  (layers, board boundary, per-component images + deduplicated padstacks, nets,
  netclass rules). Follows KiCad's conventions: `(resolution um 10)`, mm × 10000
  units, Y negated, footprint rotation baked into pin coordinates.
- **`specctra/ses.py`** — SES parser (reuses our S-expr parser). Because Freerouting
  does not always emit coordinates at the resolution it declares, the scale is
  **calibrated** from the session's placement echo against known board positions —
  robust to that quirk.
- **`backends/freerouting.py`** — locates a runtime (jar via `FREEROUTING_JAR`, a
  native launcher, or the Docker image) and runs it headless
  (`-de/-do … --gui.enabled=false`). Success is judged by a parseable SES, not the
  (unreliable) exit code.
- `autoroute_freerouting` runs the whole DSN → route → SES pipeline and applies the
  traces/vias through the **existing session model**, so the result is fully
  undoable/rollback-able like any other mutation.
- Verified end-to-end against Freerouting v2.2.4: the fixture board routes all nets,
  the SES re-imports at exact mm coordinates, and the committed board round-trips.
  The live-router test is gated on a locally runnable jar/native runtime (CI without
  one simply skips it); DSN-export and SES-import are tested with a checked-in `.ses`
  fixture and need no Freerouting install.
- Also added `.dsn`/`.ses` to the allowed export extensions and a
  `PathValidator.validate_import` for non-KiCad input files.

### Completed: "quick wins" bundle (2026-06-17)

- Added `duplicate_component`, `place_component_array`, `align_components` (placement)
  and `get_board_2d_view` (new `visual` category). Tool count 112 → 116.
- Session layer gained `read_position` and `apply_duplicate` (full footprint clone with
  regenerated UUIDs; recorded as a `place_component` op so undo/rollback works).
- **Bug fix (pre-existing):** `SecureSubprocess` rejected every absolute export-output
  path and every comma-separated `--layers` value, which silently broke
  `export_svg` / `export_pdf` / `export_step` / `export_pos` for normal absolute-path
  calls. Both are now allowed (with the suspicious-path guard intact), repairing the
  existing export tools as well as the new view tool. Regression tests added.

## Tool-count detail (mixelpixx, 122 across 16 categories)

Project (5), Board (12), Component (16), Routing (13), Schematic (27), DRC (8),
Export (8), Footprint Libraries (4), Symbol Libraries (4), Footprint Creator (4),
Symbol Creator (4), Datasheet (2), JLCPCB (5), Freerouting (4), UI Management (2),
plus 4 router meta-tools.
