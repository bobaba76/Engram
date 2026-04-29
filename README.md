# Engram

Engram is a local-first code intelligence engine for IDE agents.

Its job is simple: give tools like Windsurf Cascade or other MCP-capable assistants deep, durable access to a real codebase instead of forcing them to rely on shallow file search and short chat memory.

Engram indexes a repository into local stores, builds structural and process context, and exposes that through MCP so an assistant can answer questions like:

- where is this handled?
- what will this affect?
- what tests should I run?
- what files are most related to this target?

## What Engram is for

Engram is aimed at day-to-day coding help, especially for someone working inside an IDE with an agent doing the querying.

That means the most important qualities are:

- local context
- durable indexing
- predictable tool outputs
- safe handling of broad questions
- useful next-step guidance for coding tasks

The goal is not to be a chat bot with a few search tricks. The goal is to be a reliable context backend for real software work.

## What it does today

- indexes Python and TypeScript/JavaScript repositories into local stores
- extracts files, symbols, chunks, and graph relationships
- stores semantic vectors for chunk retrieval when enabled
- builds dependency and call-style graph context
- builds inferred process and execution-flow records
- runs grouped review and persists findings
- exposes repo intelligence through an MCP server
- supports investigation-style queries that combine:
  - search
  - symbol resolution
  - source snippets
  - graph context
  - app context
  - change/test guidance

## Core capabilities

### Indexing

Engram supports incremental indexing by default.

An index run can:

- scan the repo
- detect changed vs unchanged files
- parse changed files
- rebuild graph state where needed
- rebuild process records
- chunk code for retrieval
- embed chunks
- run review workflows
- persist reports and run metadata

### MCP tools

Engram exposes a fairly broad MCP surface for IDE agents. The most important tools include:

- `resolve_target`
- `semantic_code_search`
- `investigate_codebase`
- `get_source_context`
- `unified_context`
- `impact_analysis`
- `app_context`
- `change_impact_report`
- `find_tests_for_target`
- `suggest_tests_for_change`
- `test_impact`
- `feature_context`
- `index_status`
- `index_health`
- `detect_changes`
- `get_dependencies`
- `find_symbols`
- `get_callers_and_callees`
- `get_graph_neighborhood`
- `get_file_summary`
- `get_review_history`
- `get_symbol_context`

### Investigation workflow

`investigate_codebase` is the main orchestration-style tool.

It is designed to answer natural questions safely and predictably, especially when an IDE agent is the caller.

Recent work in this area has focused on:

- broad-query safety
- target resolution quality
- consistent MCP response shape
- change-help style answers
- lightweight ambiguity handling for weak UI-ish terms

It now returns structured agent-friendly fields such as:

- `status`
- `warnings`
- `confidence`
- `next_tools`
- `top_files`
- `top_symbols`
- `partial`

and investigation payloads also include useful extras like:

- `change_guidance.related_files`
- `change_guidance.recommended_tests`
- `change_guidance.likely_impact_targets`

## Architecture

Engram uses a hybrid local storage model.

### DuckDB

DuckDB stores durable structured index data such as:

- files
- symbols
- chunks
- review data
- run metadata
- process metadata

### Kuzu

Kuzu stores graph relationships, including things like:

- file and symbol nodes
- `DEFINES`
- `IMPORTS`
- `CALLS`
- `REFERENCES`

### LanceDB

LanceDB stores vector embeddings for chunk retrieval.

### Review and summary layer

Engram can run grouped review, persist findings, and generate technical / layperson summaries for index runs.

### MCP server

The MCP server is the interface an IDE agent actually talks to.

## Repository structure

- `app/`
  - orchestration, coordinator, run modes
- `config/`
  - runtime settings
- `indexing/`
  - scanner, parser, chunker, embeddings, graph and process builders
- `mcp_server/`
  - MCP server wiring, formatters, resolvers
- `models/`
  - config, entity, run, review, stage models
- `reviewers/`
  - review pipeline and aggregation logic
- `scripts/`
  - CLI and MCP entry points
- `services/`
  - search, investigation, graph, app context, change/test intelligence, summaries
- `storage/`
  - DuckDB, Kuzu, LanceDB, manifests
- `tests/`
  - focused unit and behavior tests

## Requirements

- Python 3.11+
- Windows is the main tested environment right now
- local filesystem access to the repo you want to index

Optional:

- OpenRouter API key for LLM-backed review/summaries
- CUDA-enabled PyTorch environment if you want GPU embeddings

## Installation

Create and activate a virtual environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy the environment template:

```powershell
Copy-Item .env.example .env
```

Then fill in any values you care about.

## Important configuration

Engram is mostly configured through environment variables.

Some important ones from `.env.example`:

- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `Engram_PROJECT_ROOT`
- `Engram_SCAN_EXCLUDED_DIRS`
- `Engram_SCAN_INCLUDE_PATTERNS`
- `Engram_SCAN_EXCLUDE_PATTERNS`
- `Engram_REVIEW_ENABLED`
- `Engram_REVIEW_ANALYSIS_MODEL`
- `Engram_REVIEW_GROUP_SIZE`
- `Engram_MAX_CONCURRENT_LLM_REVIEWS`
- `Engram_EMBED_PROVIDER`
- `Engram_EMBED_MODEL`
- `Engram_EMBED_DEVICE`
- `Engram_EMBED_BATCH_SIZE`
- `Engram_PROCESS_EXTRACTION_ENABLED`
- `Engram_PROCESS_MAX_DEPTH`
- `Engram_PROCESS_MAX_ENTRYPOINTS`
- `Engram_PROCESS_MAX_RECORDS`

## Quick start

### 1. Index a repo

Incremental index:

```powershell
python scripts/run_index.py C:\path\to\repo incremental
```

Default index run:

```powershell
python scripts/run_index.py C:\path\to\repo
```

Optional full rebuild:

```powershell
python scripts/run_index.py C:\path\to\repo full
```

### 2. Start the MCP server

```powershell
python scripts/run_mcp.py C:\path\to\repo
```

If no repo is passed, Engram can fall back to:

- command-line args
- `Engram_PROJECT_ROOT`
- current working directory
- the most recently indexed sibling repo

### 3. Point your IDE agent at Engram

The main workflow is:

1. index the repo
2. run the MCP server
3. let your IDE assistant query Engram instead of relying only on native search

## Typical Windsurf / Cascade usage

This is the intended shape of use:

- your dad is coding in the IDE
- Cascade calls Engram tools when it needs deeper repo context
- Engram resolves symbols, retrieves snippets, maps related files, and suggests tests or impact follow-ups

The strongest question styles right now are:

- exact symbol or method lookups
- implementation-location questions
- impact-style questions
- test-guidance questions

Examples:

- `where is Coordinator.run handled`
- `what will Coordinator.run affect`
- `what tests should I run for Coordinator.run`
- `where is ProcessRepository.insert_relationships handled`

## Useful scripts

### Run indexing

```powershell
python scripts/run_index.py C:\path\to\repo
```

### Run incremental indexing explicitly

```powershell
python scripts/run_index.py C:\path\to\repo incremental
```

### Run MCP only

```powershell
python scripts/run_mcp.py C:\path\to\repo
```

### Run realtime indexing

```powershell
python scripts/run_realtime_index.py C:\path\to\repo --debounce 2 --poll-interval 2
```

### Run indexing and then serve MCP

```powershell
python scripts/run_all.py
```

### Run smoke checks

```powershell
python scripts/smoke_mcp.py
```

### Run the investigation evaluation set

```powershell
python scripts/evaluate_investigate.py
```

This evaluates a small set of realistic investigation questions and scores them for:

- latency
- target correctness
- top-file quality
- next-tool quality
- expected partial behavior

## Output and local data

Engram writes local index state under the repo's `data/` directory.

That local data can include:

- manifests
- reports
- DuckDB data
- Kuzu graph data
- LanceDB vector data

Example artifacts:

```text
data/
  manifests/current_manifest.json
  reports/<run_id>/technical_summary.md
  reports/<run_id>/layperson_summary.md
```

`data/` is intentionally gitignored.

## Current strengths

- local-first indexing and retrieval
- good symbol resolution for grounded code questions
- safe handling of broad investigation prompts
- useful MCP surface for IDE agents
- change/test guidance built into investigation results
- repeatable evaluation harness for investigation quality

## Current limitations

- weak UI-ish concepts can still be harder than grounded symbols
- test recommendation quality is useful but still somewhat lexical
- frontend concept mapping is improving but not perfect
- retrieval quality still depends heavily on the indexed code and symbol structure
- live MCP behavior can briefly lag behind repo changes until the server reloads

## Good prompts to try

If you want to sanity-check Engram in an IDE, these are good prompts:

- `Use investigate_codebase for: where is Coordinator.run handled`
- `Use investigate_codebase for: what will Coordinator.run affect`
- `Use investigate_codebase for: what tests should I run for Coordinator.run`
- `Use resolve_target for Coordinator.run`
- `Use app_context for Coordinator.run`
- `Use impact_analysis for ProcessRepository.insert_relationships`

## Notes for contributors

If you are improving Engram, prioritize:

- agent reliability over cleverness
- predictable output shape
- safe broad-query behavior
- better ranking and ambiguity handling
- improvements proven by real eval cases

The best place to extend quality checks right now is the investigation evaluation set in:

- `scripts/investigate_eval_cases.json`
- `scripts/evaluate_investigate.py`

## License

This project is licensed under the MIT License. See `LICENSE`.
