# Coder

Local-first code intelligence and review engine for Python and TypeScript repositories.

Coder indexes a repo into a hybrid retrieval stack, builds a structural graph, runs grouped code review, and exposes the result through MCP so IDE agents can query your local codebase with semantic, graph, and review-aware context.

## Why this exists

Most editor assistants are good at chatting about code and bad at maintaining durable context across a real repository.

Coder is designed to close that gap.

It gives an LLM a local context engine with:

- **Incremental indexing**
- **Semantic retrieval**
- **Dependency and call graph traversal**
- **Persisted review history**
- **MCP-native IDE integration**
- **Grouped LLM review with structured findings**

## What it does

- **Indexes** Python and TypeScript/TSX/JS/JSX repositories into durable local stores
- **Extracts symbols** and builds code chunks for retrieval
- **Builds a graph** of files, symbols, imports, calls, references, and dependencies
- **Embeds chunks** with Jina embeddings when available, with graceful fallback behavior
- **Runs grouped review** over related files before extracting structured findings
- **Persists findings and agent analyses** so review history can be queried later
- **Generates technical and layperson summaries** for each run
- **Serves the indexed repo over MCP** for tools such as Cursor and Windsurf

## Architecture

Coder uses a hybrid local-first storage model.

### Storage layer

- **DuckDB**
  - files
  - symbols
  - chunks
  - review jobs
  - review agent analyses
  - review observations
  - review findings
  - run metadata

- **KuzuDB**
  - file nodes
  - symbol nodes
  - `DEFINES`, `IMPORTS`, `CALLS`, and `REFERENCES` edges

- **LanceDB**
  - semantic vectors for code chunks

### Review layer

The review pipeline is now centered on grouped LLM review.

- **Related files are grouped together**
- **Pass 1** produces a conversational synthesis of what those files are doing together
- **Pass 2** extracts concrete, structured findings from that synthesis
- Findings are merged and deduplicated before being summarized into final reports

This produces more useful output than a strict one-file-at-a-time audit pass.

### MCP layer

Coder exposes the indexed repo through an MCP server with tools including:

- `index_status`
- `semantic_code_search`
- `get_dependencies`
- `get_review_history`
- `get_symbol_context`
- `find_symbols`
- `get_callers_and_callees`
- `get_graph_neighborhood`
- `get_file_summary`
- `get_source_context`

## How indexing works

Incremental runs:

- compare discovered files against the persisted file index
- parse only changed files
- rebuild graph state only where needed
- re-embed changed chunks
- review changed files
- preserve state for unchanged files

The CLI prints stage timings and compact run summaries so you can see what changed in each run.

## Requirements

- Python 3.11+
- Windows is the primary tested environment right now
- Optional OpenRouter API key for LLM-backed review and run summaries
- Optional CUDA-enabled PyTorch install if you want GPU embeddings

## Installation

Create and activate a virtual environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If you want GPU embeddings, install a CUDA-enabled PyTorch build separately.

Then copy the environment template and fill in any values you need:

```powershell
Copy-Item .env.example .env
```

## Configuration

Coder is mostly driven by environment variables.

For a minimal LLM-backed setup, the main thing you need is:

- `OPENROUTER_API_KEY`

Everything else can usually stay at the defaults in `.env.example` to get started.

### Common environment variables

- `OPENROUTER_API_KEY`
  - Enables OpenRouter-backed grouped review and run summaries

- `CODER_PROJECT_ROOT`
  - Optional project root override for MCP startup

- `CODER_REVIEW_ANALYSIS_PROVIDER`
  - Override the review provider

- `CODER_REVIEW_ANALYSIS_MODEL`
  - Override the OpenRouter model used for review/summaries

- `CODER_EMBED_DEVICE`
  - Requested embedding device, for example `cuda` or `cpu`

- `CODER_REVIEW_RUN_LEGACY_HEURISTICS_WITH_LLM`
  - Set to `true` only if you explicitly want the old heuristic review pass to run alongside grouped LLM review

## Quick start

### 1. Index a repository

```powershell
python scripts/run_index.py C:\path\to\your\repo
```

This writes local index state under that repo’s `data/` directory and produces:

- structured index data
- persisted findings
- technical and layperson markdown reports

If you want to test Coder against itself, a good first run is:

```powershell
python scripts/run_index.py .
```

### 2. Start the MCP server

```powershell
python scripts/run_mcp.py C:\path\to\your\repo
```

If you do not pass a project root, Coder will try to resolve one from:

- command-line args
- `CODER_PROJECT_ROOT`
- current working directory
- the most recently indexed sibling repo

### 3. Ask an MCP-capable IDE questions

Examples:

- **Semantic search**
  - “Use `semantic_code_search` to find where we handle LLM rate limiting.”

- **Graph impact analysis**
  - “Use the graph to show what might break if I change this function.”

- **Review history**
  - “Show me prior findings for `backend/config.py`.”

## Typical workflow with Cursor or Windsurf

- **Step 1**
  - Run `python scripts/run_index.py C:\path\to\repo`

- **Step 2**
  - Configure the IDE to launch `python scripts/run_mcp.py C:\path\to\repo`

- **Step 3**
  - Ask the assistant to use MCP tools instead of relying on shallow file search alone

## MCP setup example

Your editor-specific config will vary, but the core command should point at:

```powershell
python scripts/run_mcp.py C:\path\to\your\repo
```

Run it from the `Coder` repo root so imports resolve correctly.

## Output

Each run produces:
 
 - a run id
 - stage timings
 - a persisted manifest
 - merged findings
 - report files:
  - `data/reports/<run_id>/technical_summary.md`
  - `data/reports/<run_id>/layperson_summary.md`

The `data/` directory is intentionally gitignored because it contains local indexes, manifests, vector data, and generated reports.

## Example output

After a run, you should expect artifacts like:

```text
data/
  manifests/current_manifest.json
  reports/<run_id>/technical_summary.md
  reports/<run_id>/layperson_summary.md
```

And a CLI summary shaped roughly like:

```text
Index run completed: <run_id>
- scan: 28.73s | ...
- parse: 10.00s | ...
- graph: 23.99s | ...
- embed: 165.64s | ...
- review: 108.88s | ...
Report files:
- technical: .../technical_summary.md
- layperson: .../layperson_summary.md
```

## Current strengths

- **Local-first**
  - Your code intelligence stays on your machine

- **Hybrid retrieval**
  - Semantic, relational, and graph context all work together

- **Grouped review flow**
  - Related files are reviewed together before findings are extracted

- **Durable review history**
  - Findings and analyses are persisted across runs

- **MCP-native integration**
  - Works well as a local context backend for IDE agents

## Current limitations

- **Python parsing** currently relies on built-in `ast`
- **TypeScript extraction** still needs deeper structural improvements
- **Frontend and Electron review quality** can lag behind backend-heavy repos
- **Markdown files are not indexed**
  - changing `README.md` will not affect `run_index.py`
- **GPU embeddings** depend on a valid CUDA-enabled PyTorch install

## Repository structure

- `app/`
  - indexing/review orchestration
- `indexing/`
  - scanner, chunker, embeddings, graph building, planning
- `reviewers/`
  - providers, context assembly, aggregation, legacy reviewer implementations
- `services/`
  - semantic search, graph queries, summaries, source retrieval, symbol lookup
- `storage/`
  - DuckDB, Kuzu, LanceDB, manifest persistence
- `scripts/`
  - CLI entry points

## Useful commands

### Run indexing

```powershell
python scripts/run_index.py C:\path\to\repo
```

### Run MCP only

```powershell
python scripts/run_mcp.py C:\path\to\repo
```

### Run indexing and then serve MCP

```powershell
python scripts/run_all.py
```

### Windows shortcut

```bat
start.bat
```

## Open source readiness notes

If you plan to publish this repo, the next cleanup passes are probably:

- **Pin and document PyTorch install paths** for CPU vs CUDA users
- **Add screenshots or GIFs** of MCP usage in Cursor/Windsurf
- **Add sample reports** to show technical vs layperson output
- **Document data directory behavior** more explicitly
- **Add tests around ranking and grouped review selection**

## License

This project is licensed under the MIT License. See `LICENSE`.
