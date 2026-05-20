# Engram

Engram is a local code-intelligence engine for AI coding assistants.

It reads your repository, builds a searchable map of the code, and exposes that map through an MCP server so tools like Codex, Cursor, Claude Desktop, Windsurf, and other agent-style editors can ask grounded questions before they edit.

In plain English: Engram helps an AI assistant understand your project like a developer would.

It can answer questions such as:

- Where is this feature implemented?
- Who calls this function?
- What does this header affect?
- If I change this API route, which frontend components might break?
- What changed in my working tree?
- How risky is this change?
- What should I test before committing?
- How should I split this big change into sensible commits?

Engram is designed to be local-first. Your code is indexed into local databases on your machine, and the MCP tools query those local indexes.

## Why This Exists

Modern AI coding assistants are powerful, but they often lack durable project memory. They can read a few files at a time, but real software work needs more than that:

- symbol lookup
- dependency tracing
- route and API contract awareness
- call graphs
- include graphs
- test discovery
- git-diff impact analysis
- risk explanations
- pre-commit guidance

Engram tries to provide that missing intelligence layer.

The original goal was to build a practical helper for real coding work, especially for large, older, and mixed-language projects where normal search is not enough. That includes modern Python/React apps, C# services, and embedded C/C++ projects such as MPLAB firmware.

## What Engram Does

Engram indexes a repository and creates several kinds of context:

- Files and source chunks
- Symbols such as functions, classes, methods, components, types, macros, and constants
- Imports, calls, references, includes, inheritance, field reads, API calls, and route relationships
- Backend route handlers and frontend API consumers
- Response shapes and frontend field reads
- Process/flow traces through routes, services, repositories, and tests
- Git-aware changed files and changed symbols
- Risk summaries and recommended tests

That context is exposed as MCP tools. An AI assistant can call those tools instead of guessing.

## What Makes It Useful

Engram is not just semantic search.

It combines several layers:

- Relational metadata for fast file/symbol/chunk lookup
- A graph database for dependency and impact traversal
- Optional vector search for semantic discovery
- Git diff mapping for change analysis
- Language-specific parsers for structure
- Risk heuristics for public APIs, shared modules, headers, embedded firmware boundaries, and frontend contracts

This means Engram can produce answers like:

```text
/products/trends is handled by backend/routers/products.py:get_product_trends.
It is fetched by frontend/src/services/api.ts:getProductTrends.
ProductTrendModal reads metrics.intransit_stock and chart_data[].qty_sold.
Changing this route is MEDIUM risk. Run the product trends tests and check the modal.
```

Or for embedded C:

```text
global.h is a high-risk public/native header.
It is directly included by uart.c, init.c, flash.c, and VideoOverlay.c.
It is also part of the MPLAB target "Video Overlay" for dsPIC33FJ64GP204.
Changing it may affect startup, UART, flash, and global state behavior.
```

## Current Status

Engram is active and usable, but still evolving.

Strongest areas today:

- Python backend indexing
- TypeScript/React frontend indexing
- API route and frontend consumer impact
- Response-shape and field-read checks
- Git-aware change reports
- Pre-commit workflow intelligence
- C/C++ and embedded-C project awareness
- C# indexing and basic ASP.NET route support

Still improving:

- Full compiler-accurate C/C++ analysis when no `compile_commands.json` exists
- Deep C/C++ call graph quality
- C# inheritance/DTO/controller process precision
- Highly dynamic frontend API clients
- More framework-specific route extraction
- Process catalog quality and ranking

## Important Note: LLM Review Is Currently Disabled

Older versions of this project included LLM-backed review and summary workflows during indexing.

That layer is currently disabled and should be treated as legacy/future work until it is explicitly re-enabled and validated.

The main working path today is deterministic local indexing plus MCP tools.

## Language Support

### Strongest Today

- Python
- TypeScript
- TSX/React
- JavaScript/JSX

### Supported

- C
- C++
- C#
- Object Pascal

### C/C++ And Embedded Support

Engram supports native and embedded projects with:

- `.c`, `.h`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx`
- assembly and include-style files such as `.s`, `.S`, `.asm`, and `.inc`
- `compile_commands.json`
- CMake target detection
- Visual Studio `.sln` / `.vcxproj` markers
- MPLAB project files such as `.mcp`, `.mcw`, `.mptags`, `.scl`, and `.plt`
- device/project hints from MPLAB projects
- include directory and compiler flag extraction where available
- header blast-radius summaries
- embedded risk rules for global headers, device headers, ISR/trap/startup files, UART/flash/init/bootloader modules, and linker scripts

When `compile_commands.json` exists, Engram can use stronger compiler-aware context. When it does not, Engram still uses project files and heuristics, but it will report lower confidence.

## Architecture

Engram uses a local, multi-store architecture:

- DuckDB stores files, symbols, chunks, process metadata, findings, and run metadata.
- Kuzu stores graph relationships such as `CALLS`, `IMPORTS`, `INCLUDES`, `FETCHES`, and `READS_FIELD`.
- LanceDB stores optional vector embeddings for semantic search.
- The MCP server exposes all of this as tools an AI assistant can call.

Main directories:

- `app/`: indexing coordinator, lifecycle, and run modes
- `config/`: settings and defaults
- `indexing/`: scanner, parsers, graph builder, chunking, embeddings
- `mcp_server/`: MCP server, schemas, tool formatting, target resolution
- `models/`: structured models used across the indexer
- `reviewers/`: legacy/local review infrastructure
- `scripts/`: command-line entry points
- `services/`: code intelligence services
- `storage/`: DuckDB, Kuzu, LanceDB, and manifest stores
- `tests/`: behavior and regression tests
- `docs/`: roadmap, handoff notes, and engineering backlog

## MCP Tools

Engram exposes a broad MCP tool set. Most tools accept an optional `repo` parameter so an assistant can target a specific indexed repository.

### Repository And Index Management

| Tool | Purpose |
|------|---------|
| `list_repos` | List indexed repositories Engram knows about. |
| `select_repo` | Set the active repository for follow-up calls. |
| `index_status` | Show whether an index is ready and what run it came from. |
| `index_health` | Show index health, parser counts, graph integrity, and native build context. |
| `reindex_project` | Start a full or incremental reindex. Defaults to background mode. |
| `reindex_status` | Poll a background reindex job. |
| `get_recent_runs` | List recent indexing runs. |
| `get_run_metrics` | Inspect metrics for a specific index run. |

### Code Discovery

| Tool | Purpose |
|------|---------|
| `semantic_code_search` | Search for code by natural-language task or concept. |
| `investigate_codebase` | Higher-level investigation with ranked files and next-tool suggestions. |
| `feature_context` | Find likely implementation areas for a feature. |
| `app_context` | Gather app-level context for a route, feature, file, or broad target. |
| `get_file_summary` | Summarize an indexed file. |
| `get_source_context` | Return source snippets for a target. |

### Symbols And Graph

| Tool | Purpose |
|------|---------|
| `resolve_target` | Disambiguate a symbol/file/target before deeper work. |
| `find_symbols` | Find symbols by name, kind, file, or UID. |
| `get_symbol_context` | Show symbol metadata, graph context, and related symbols. |
| `get_callers_and_callees` | Show direct callers and callees. |
| `get_dependencies` | Show inbound/outbound dependencies and native header blast radius. |
| `get_graph_neighborhood` | Traverse nearby graph edges. |
| `graph_query` | Run a bounded graph query. |
| `impact_analysis` | Analyze upstream or downstream impact for a target. |
| `unified_context` | Combine symbol resolution, source, graph, and nearby context. |
| `preview_rename` | Preview graph-aware symbol rename impact before editing. |

### Git-Aware Change Intelligence

| Tool | Purpose |
|------|---------|
| `detect_changes` | Analyze staged, unstaged, or compared git changes. |
| `change_impact_report` | Produce a higher-level change report with risks, slices, tests, routes, fields, and processes. |
| `suggest_tests_for_change` | Recommend tests from the current diff. |
| `test_impact` | Estimate test impact from the current diff. |
| `find_tests_for_target` | Find tests relevant to a symbol, file, route, or feature. |

### API, Route, And Contract Intelligence

| Tool | Purpose |
|------|---------|
| `route_map` | Map backend routes to handlers and consumers. |
| `api_impact` | Show route handler, consumers, field reads, shape status, and risk. |
| `shape_check` | Compare backend response shape with frontend reads. |
| `field_impact` | Find who reads a response field such as `metrics.intransit_stock`. |

### Process And Flow Intelligence

| Tool | Purpose |
|------|---------|
| `trace_processes` | Trace execution flows through graph/process data. |
| `list_processes` | List indexed process flows. |
| `symbol_process_participation` | Show which processes include a symbol. |

## Example Workflows

### Find Where A Feature Lives

```text
investigate_codebase(question="Where is product trend data built?")
```

Engram ranks likely files, symbols, and next tools instead of giving a broad text-search dump.

### Check An API Change

```text
api_impact(route="/products/trends")
shape_check(route="/products/trends")
field_impact(route="/products/trends", field="chart_data[].intransit_stock")
```

Engram can connect backend handlers to frontend wrappers, components, and field reads.

### Review A Working Tree Before Commit

```text
detect_changes(scope="unstaged")
change_impact_report(scope="unstaged")
suggest_tests_for_change(scope="unstaged")
```

Engram reports risk scope, changed files, changed symbols, affected routes, frontend consumers, process impact, suggested tests, and recommended commit slices.

### Inspect Embedded Header Impact

```text
get_dependencies(target="global.h")
get_dependencies(target="include/global.h")
```

Engram can summarize direct and indirect include blast radius, public-header risk, and embedded-specific risk factors.

## Installation

Requirements:

- Python 3.11+
- Windows is the main tested environment today
- local filesystem access to the repositories you want to index

Optional:

- `libclang` for stronger C/C++ parsing
- CUDA-capable PyTorch if using local GPU embeddings
- embedding provider dependencies if semantic vector retrieval is enabled

Setup:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Then edit `.env` if needed.

## Quick Start

Index a repository:

```powershell
python scripts/run_index.py C:\path\to\repo incremental
```

Start the MCP server:

```powershell
python scripts/run_mcp.py C:\path\to\repo
```

Run tests:

```powershell
python -m pytest
```

Run a smoke check:

```powershell
python scripts/smoke_mcp.py
```

## Other Useful Commands

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

## Output Style

Engram tools are designed for AI agents, so outputs usually include:

- `status`
- `confidence`
- `warnings`
- `partial`
- `repo_root`
- `repo_name`
- `compact_summary`
- `top_files`
- `top_symbols`
- `next_tools`

Broad or expensive queries are intentionally bounded. If Engram cannot safely traverse everything before an MCP client timeout, it returns partial results with warnings instead of hanging.

## Current Limitations

- Engram is not a compiler, type checker, or replacement for tests.
- C/C++ precision is best when `compile_commands.json` is available.
- MPLAB support is useful, but it is project-file-aware rather than a complete Microchip compiler emulator.
- Dynamic routes and highly abstracted API clients may still need source inspection.
- Some frontend field-read extraction is heuristic.
- Existing MCP server processes need a restart after code changes.
- Existing repos need a reindex before newly added intelligence appears in live MCP results.
- LLM-backed review workflows are currently disabled.

## Roadmap

Near-term priorities:

- Better C/C++ include and call graph depth
- More precise embedded target/test mapping
- C# controller/service/repository workflow intelligence
- Stronger DTO and response-shape checks for C#
- More backend frameworks
- More robust AST-native frontend field reads
- Better process catalog quality
- More live MCP smoke tests

## Repository Instructions

Engram can write an `AGENTS.md` file into indexed repositories. That file tells AI assistants to prefer Engram MCP for code discovery, impact analysis, test discovery, and implementation context.

This is useful because MCP servers often expose many tools, and an assistant needs guidance on which tool to call first.

## Philosophy

Engram is built around a simple idea:

> AI coding assistants become much more useful when they can ask the codebase structured questions before they edit.

The goal is not to replace developer judgment. The goal is to give both the developer and the assistant better context:

- fewer blind edits
- fewer missed callers
- fewer broken frontend/backend contracts
- better tests before commit
- clearer risk explanations
- better support for older real-world codebases

## License

This project is licensed under the MIT License. See `LICENSE`.
