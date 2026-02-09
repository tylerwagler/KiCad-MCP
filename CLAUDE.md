# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A KiCad MCP (Model Context Protocol) server for AI-assisted PCB design. Pure Python, built on FastMCP. Licensed GPL-3.0 (matching KiCad itself).

The goal is to fill the gap no existing project covers: the full **analyze → modify → route → verify → export** loop with undo/rollback, smart tool routing, and real-time KiCad UI sync.

## Commands

```bash
# Install all dependencies (including dev)
uv sync --all-extras

# Run the MCP server (stdio transport)
uv run kicad-mcp

# Run tests
uv run pytest
uv run pytest tests/unit/test_foo.py::test_bar  # single test

# Lint and format
uv run ruff check .
uv run ruff format .

# Type check
uv run mypy src/
```

## Architecture

### Two-Tier Tool System (Tool Router Pattern)

The server exposes 75 tools but **does NOT register them all directly with MCP**. Instead:

- **Direct tools** (8): Always visible to the LLM — `open_project`, `get_board_info`, `list_components`, `find_component`, `start_session`, `commit_session`, `list_libraries`, `run_drc`
- **Routed tools** (67): Discoverable via 4 meta-tools: `list_tool_categories`, `get_category_tools`, `execute_tool`, `search_tools`

This reduces LLM context usage by ~70%. All tools are registered in a **single unified registry** (`tools/registry.py`) with `ToolSpec` dataclasses. The `direct=True` flag controls which tier a tool lives in.

### Package Layout

```
src/kicad_mcp/
├── server.py           # FastMCP server creation and startup
├── tools/
│   ├── registry.py     # ToolSpec + TOOL_REGISTRY (single source of truth)
│   └── router.py       # Meta-tools for dynamic discovery/execution
├── resources/          # MCP Resources (read-only board/project state)
├── prompts/            # MCP Prompt templates (DRC debug, design review, etc.)
├── backends/           # KiCad communication backends
├── sexp/               # S-expression parser (zero-dependency KiCad file reading)
├── schema/             # Typed KiCad file models (board, schematic, footprint)
├── session/            # Session/transaction model with undo/rollback
└── manufacturers/      # DRC rule presets (JLCPCB, OSHPark, PCBWay, etc.)
```

### Backend Strategy

The `backends/` package abstracts how we talk to KiCad:

1. **S-expression parser** (`sexp/` + `schema/`): Pure Python, zero dependencies. Used for all **read** operations. Parses `.kicad_pcb`, `.kicad_sch`, `.kicad_mod` files directly. Must preserve round-trip fidelity (parse → modify → write back without losing formatting/comments).
2. **kicad-cli**: For operations KiCad does better (DRC, Gerber export, PDF rendering). Requires KiCad installed.
3. **KiCad IPC API** (kipy): For real-time UI sync when KiCad is running. Optional, KiCad 9+ only.

The backend factory selects the best available backend at runtime. Read operations should never require KiCad to be installed.

### Session Model (Query-Before-Commit)

Write operations go through a session/transaction layer:

```
start_session → query_move (preview impact) → apply_move → commit / rollback
```

The LLM can test modifications before writing to disk. The session tracks a stack of changes for undo.

### Three-Pillar MCP Design

Following the MCP spec, the server exposes:
- **Tools**: Actions that modify state (place component, route trace, run DRC)
- **Resources**: Read-only data (board state, component list, net connections)
- **Prompts**: Conversation templates (DRC troubleshooting, design review checklists)

### Tool Registration Pattern

Every tool is defined once in the registry. The handler uses lazy imports to keep startup fast:

```python
register_tool(
    name="analyze_board",
    description="Analyze board layout and return summary statistics",
    parameters={"board_path": {"type": "string", "description": "Path to .kicad_pcb"}},
    handler=analyze_board_handler,
    category="analysis",
    direct=True,
)
```

### Typed Responses

Tool handlers return typed dataclasses (not raw dicts). Each dataclass has a `.to_dict()` method for MCP serialization. This ensures consistent response shapes and enables IDE autocompletion during development.

## Competitive Context

This project synthesizes the best patterns from 6 existing KiCad MCP servers:

| Pattern | Source | Status |
|---|---|---|
| Tool router (context reduction) | mixelpixx/KiCAD-MCP-Server | Implemented |
| Unified tool registry | rjwalters/kicad-tools | Implemented |
| Session/undo for mutations | rjwalters/kicad-tools | Implemented |
| S-expr parser (no KiCad dep) | rjwalters/kicad-tools | Implemented |
| Resources/Tools/Prompts split | lamaalrajih/kicad-mcp | Implemented |
| Manufacturer DRC presets | rjwalters/kicad-tools | Implemented |
| JLCPCB parts catalog | mixelpixx/KiCAD-MCP-Server | Planned |
| Input validation/security | lamaalrajih/kicad-mcp | Implemented |

## KiCad-Specific Notes

- KiCad 9.x removed several pcbnew APIs: `GetLayerStack()`, `SetActiveLayer()`, `GetDRCMarkers()`. Always check against KiCad 9 API.
- KiCad file formats use S-expressions (Lisp-like syntax). The `.kicad_pcb`, `.kicad_sch`, `.kicad_pro`, and `.kicad_mod` files are all S-expression based.
- The `pcbnew` Python module is only available when KiCad is installed and its bundled Python is used. Do not make it a hard dependency.
- `kicad-cli` is the official command-line tool (KiCad 8+). It handles DRC, export, and conversion without needing a GUI.
