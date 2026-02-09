# KiCad MCP Server

AI-assisted PCB design through the [Model Context Protocol](https://modelcontextprotocol.io). Analyze, modify, route, verify, and export KiCad boards — all from your AI assistant.

**75 tools** | **360 tests, 100% pass** | **Pure Python, zero KiCad dependency for reads**

## What It Does

This MCP server gives AI assistants (Claude, etc.) full access to KiCad PCB design workflows:

- **Open and analyze** boards, schematics, and libraries without KiCad installed
- **Place, move, rotate, flip, edit, and replace** components with full undo/rollback
- **Route traces and vias**, manage nets and zones, add copper pours
- **Run DRC** and check manufacturability against JLCPCB/OSHPark/PCBWay rules
- **Export** Gerber, PDF, SVG, STEP, VRML, BOM, and pick-and-place files
- **Create projects** and schematics from scratch

## Quick Start

### Install

```bash
# Requires Python 3.11+
uv sync --all-extras
```

### Configure Your AI Client

Add to your MCP client configuration (e.g. Claude Desktop `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kicad-mcp": {
      "command": "uv",
      "args": ["--directory", "/path/to/KiCad-MCP", "run", "kicad-mcp"]
    }
  }
}
```

### Run Standalone

```bash
uv run kicad-mcp
```

## Tool Categories

| Category | Tools | Description |
|---|---|---|
| **Project** | 6 | Open/create/save projects, list components, board info |
| **Board Setup** | 7 | Board size, outline, mounting holes, text, design rules |
| **Placement** | 8 | Place, rotate, flip, delete, edit, replace, group components |
| **Routing** | 5 | Route traces, add/delete vias, ratsnest analysis |
| **Net/Zone** | 7 | Create/delete nets, zones, copper pours, net classes |
| **Schematic** | 11 | Open/edit schematics, add symbols/wires/labels, generate netlists |
| **Analysis** | 6 | Net list, layer stack, board extents, clearance checks |
| **DRC** | 2 | Design rule check with violation details |
| **Export** | 7 | Gerber, PDF, SVG, STEP, VRML, BOM, pick-and-place |
| **Library** | 6 | Search symbols/footprints across installed KiCad libraries |
| **Manufacturer** | 3 | DRC presets for JLCPCB, OSHPark, PCBWay |
| **Session** | 7 | Start/commit/rollback sessions, preview moves, undo changes |

## Architecture

### Two-Tier Tool Router

Not all 75 tools are dumped into the LLM context. Instead:

- **8 direct tools** are always visible (open project, start session, etc.)
- **67 routed tools** are discoverable via 4 meta-tools: `list_tool_categories`, `get_category_tools`, `execute_tool`, `search_tools`

This reduces LLM context usage by ~70%.

### Three Backends

1. **S-expression parser** — Pure Python, zero dependencies. Reads `.kicad_pcb`, `.kicad_sch`, `.kicad_mod` files directly. Used for all read operations. KiCad does **not** need to be installed.
2. **kicad-cli** — Wraps KiCad's official CLI (KiCad 8+) for DRC, Gerber export, PDF rendering. Auto-detects install path on Windows/Linux/macOS.
3. **KiCad IPC API** — For real-time UI sync when KiCad is running (KiCad 9+, planned).

### Session Model (Query-Before-Commit)

All board mutations go through a safe transaction model:

```
start_session → query_move (preview) → apply_move → undo → commit / rollback
```

The AI can preview changes before applying, undo individual operations, and rollback entire sessions. Nothing touches disk until `commit_session`.

### Three-Pillar MCP Design

Following the full MCP specification:

- **Tools** — Actions that modify state (75 tools)
- **Resources** — Read-only board data (component list, net map, board summary)
- **Prompts** — Conversation templates (DRC troubleshooting, design review, placement guidance)

## Development

```bash
# Install with dev dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Lint and format
uv run ruff check .
uv run ruff format .

# Type check
uv run mypy src/
```

### Project Structure

```
src/kicad_mcp/
├── server.py              # FastMCP server entry point
├── state.py               # Global board state
├── schematic_state.py     # Global schematic state
├── security.py            # Path validation, subprocess guards
├── tools/
│   ├── registry.py        # ToolSpec + TOOL_REGISTRY (single source of truth)
│   ├── router.py          # 4 meta-tools for dynamic discovery
│   ├── board_setup.py     # Board size, outline, text, design rules
│   ├── placement.py       # Component placement, edit, replace, group
│   ├── routing.py         # Traces, vias, ratsnest
│   ├── netzone.py         # Nets, zones, copper pours, net classes
│   ├── schematic.py       # Schematic editing, netlist generation
│   ├── analysis.py        # Board analysis, clearance checks
│   ├── export.py          # Gerber, PDF, SVG, STEP, VRML, BOM
│   ├── drc.py             # Design rule checking
│   ├── library.py         # KiCad library search
│   ├── manufacturer.py    # Manufacturer DRC presets
│   ├── project.py         # Project create/save
│   ├── mutation.py        # Session start/commit/rollback/undo
│   └── direct.py          # Core direct tools (open project, etc.)
├── session/
│   └── manager.py         # SessionManager with undo/rollback
├── backends/
│   └── kicad_cli.py       # kicad-cli wrapper (DRC, export)
├── sexp/
│   ├── parser.py          # Zero-dependency S-expression parser
│   └── document.py        # Document model with round-trip fidelity
├── schema/                # Typed KiCad models (board, schematic, footprint)
├── resources/             # MCP Resources (read-only board state)
├── prompts/               # MCP Prompt templates
└── manufacturers/         # DRC presets (JLCPCB, OSHPark, PCBWay)
```

## Requirements

- **Python 3.11+**
- **KiCad 8+** (optional — only needed for DRC and export commands; board reading works without it)
- **uv** (recommended) or pip

## License

GPL-3.0 — matching KiCad itself.
