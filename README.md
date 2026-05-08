# Engram / Coder

Engram is a local-first code intelligence engine for IDE agents. It indexes a repository, builds structural and graph context, and exposes that context through MCP so coding assistants can answer grounded questions about where code lives, what changes affect, which routes and consumers are involved, and what should be tested before commit.

The project is currently used as the Coder MCP backend.

## Current Status

Engram is strongest today for Python backends and TypeScript/React frontends. Recent work added GitNexus-style intelligence for:

- git-aware change detection and risk scope
- route/API/consumer impact
- response-shape checking
- frontend field-read blast radius
- symbol callers/callees and graph context
- process/flow tracing from route handlers and changed symbols
- pre-commit workflow slicing with tests, routes, fields, processes, and risk
- safe broad-diff behavior so MCP tools return bounded results instead of hanging

C/C++ and C# are supported at the indexing/parser level, but they do not yet have the same workflow-intelligence depth as Python/React.

## Important Note: LLM Review Is Disabled

The older README described LLM-backed review and summary workflows as a normal part of indexing. That section is currently disabled/not part of the active workflow. The useful path right now is deterministic local indexing plus MCP tools. Treat the LLM/reviewer layer as legacy or future work until it is explicitly re-enabled and validated.

## What It Can Answer

Typical MCP questions:

- where is `Coordinator.run` implemented?
- who calls this symbol, and what does it call?
- what files are affected by these unstaged changes?
- which route handlers changed?
- if `/products/trends` changes, which frontend components and fields are affected?
- does the backend response still satisfy frontend field reads?
- what commit slices make sense for this working tree?
- what tests should be run for this change?

## Main MCP Tools

Core navigation:

- `list_repos`
- `select_repo`
- `resolve_target`
- `semantic_code_search`
- `investigate_codebase`
- `get_source_context`
- `unified_context`
- `get_symbol_context`

Graph and impact:

- `impact_analysis`
- `app_context`
- `get_dependencies`
- `find_symbols`
- `get_callers_and_callees`
- `get_graph_neighborhood`
- `get_file_summary`

Git-aware workflows:

- `detect_changes`
- `change_impact_report`
- `suggest_tests_for_change`
- `find_tests_for_target`
- `test_impact`

API and contract intelligence:

- `route_map`
- `api_impact`
- `shape_check`
- `field_impact`
- `trace_processes`

Health and diagnostics:

- `index_status`
- `index_health`

## What The Newer Intelligence Includes

### Git-Aware Change Reports

`detect_changes` and `change_impact_report` include:

- changed files and changed symbols
- risk scope, such as whole unstaged working tree vs focused target
- git metadata and diff source
- risk by file
- changed routes
- affected frontend/API consumers
- changed response shapes
- affected processes
- suggested tests
- pre-commit slices
- validation/readiness status

The tools are designed to return bounded partial output for broad diffs instead of exhaustively traversing the graph until the MCP client times out.

### Route, API, And Field Impact

`route_map`, `api_impact`, `shape_check`, and `field_impact` can connect:

- backend route handlers
- response keys and nested response keys
- frontend API wrapper calls
- frontend component consumers
- field reads such as `metrics.intransit_stock`
- array item reads such as `chart_data[].qty_sold`
- chart `dataKey="..."` reads
- graph-backed `FETCHES` and `READS_FIELD` edges

Supported route/consumer extraction currently includes:

- FastAPI-style Python decorators
- Flask-style Python route decorators
- Django `path` / `re_path` mappings
- Express-style JS/TS routes
- frontend `apiClient`, `axios`, and `fetch`
- direct string routes and simple route constants
- wrapper-to-component propagation for common React Query patterns

### Process And Flow Impact

`trace_processes`, `api_impact`, and change reports can surface execution flows such as:

```text
GET /products/trends -> get_product_trends -> get_product_trend_data -> repository/helper calls
```

Change reports can overlay changed symbols onto these flows and use process participation as a risk factor.

### Pre-Commit Workflow Intelligence

`change_impact_report` now groups changes into recommended commit slices. Each slice can include:

- files
- routes
- consumers
- field reads
- affected processes
- what can break
- what to test
- follow-up MCP tools
- validation status
- residual risk after validation

This is meant to answer: "what can break, what should I test, and how should I split this commit?"

## Language Support

### Strongest Today

- Python
- TypeScript
- TSX/React
- JavaScript/JSX for route/API/frontend consumer patterns

### Supported But Less Workflow-Deep

- C
- C++
- C#

C/C++ support includes scanner coverage for `.c`, `.h`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, and `.hxx`. The parser prefers `libclang`, falls back to tree-sitter, then regex extraction. C# has parser support via tree-sitter/regex fallback. These languages are useful for symbols, chunks, references, and graph basics, but need additional work before they reach Python/React-level route/process/risk intelligence.

See `docs/code-intelligence-handoff.md` for the C/C++/C# workflow-intelligence roadmap.

## Architecture

Engram uses local storage:

- DuckDB for indexed files, symbols, chunks, process metadata, and run metadata
- Kuzu for graph nodes and relationships
- LanceDB for vector embeddings when semantic retrieval is enabled

Main directories:

- `app/`: coordinator, lifecycle, run modes
- `config/`: settings and defaults
- `indexing/`: scanner, parser registry, parsers, graph builder, chunks, embeddings
- `mcp_server/`: MCP server wiring, schemas, resolvers, formatters
- `models/`: structured runtime and entity models
- `scripts/`: index, MCP, smoke, and helper entry points
- `services/`: route/API/field/process/change/search/context intelligence
- `storage/`: DuckDB, Kuzu, LanceDB, manifests
- `tests/`: focused behavior tests
- `docs/`: roadmap and handoff notes

## Requirements

- Python 3.11+
- Windows is the main tested environment
- local filesystem access to the repo being indexed

Optional:

- `libclang` for stronger C/C++ parsing
- tree-sitter language package for parser fallbacks
- embedding provider dependencies if semantic vector retrieval is enabled

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Then adjust `.env` if needed.

## Quick Start

Index a repo:

```powershell
python scripts/run_index.py C:\path\to\repo incremental
```

Start the MCP server:

```powershell
python scripts/run_mcp.py C:\path\to\repo
```

Run smoke checks:

```powershell
python scripts/smoke_mcp.py
```

Run tests:

```powershell
python -m pytest
```

## Useful Commands

Full rebuild:

```powershell
python scripts/run_index.py C:\path\to\repo full
```

Realtime indexing:

```powershell
python scripts/run_realtime_index.py C:\path\to\repo --debounce 2 --poll-interval 2
```

Index then serve MCP:

```powershell
python scripts/run_all.py
```

Investigation evaluation:

```powershell
python scripts/evaluate_investigate.py
```

## Current Limitations

- Python/React workflow intelligence is ahead of C/C++/C# workflow intelligence.
- C/C++ needs build-context awareness for highly reliable call graphs.
- Some frontend field-read extraction is still heuristic, though it now covers many real-world patterns.
- Dynamic routes and highly abstracted API clients can still require fallback source inspection.
- MCP live behavior reflects the running server process; restart the server after code changes.
- LLM-backed review/summaries are currently disabled.

## Contributor Priorities

When improving Engram, prioritize:

- predictable MCP output shape
- bounded behavior for broad queries
- useful compact summaries
- low-latency tool paths
- graph and contract evidence over vague search results
- real repo validation, not only unit tests

Good next areas:

- C/C++ build-context-aware call graph
- C# ASP.NET controller/DTO/DI impact
- AST-native frontend field reads
- richer process catalog quality
- more live MCP smoke tests

## License

This project is licensed under the MIT License. See `LICENSE`.
