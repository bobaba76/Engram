# Engineering Landmines and Hardening Backlog

## Purpose

This document tracks concerns raised during external review and live MCP usage. The review was broadly positive; this file intentionally focuses only on things that could become correctness, reliability, performance, or maintainability problems as Coder is used on larger and messier repositories.

Treat these as incremental hardening items, not proof that the current system is unusable.

## Priority 1: Runtime Safety and MCP Reliability

### 1. Stateful MCP repository selection

Status:
First-pass safety guard implemented. Repo-aware MCP tools now add `repo_root`, `repo_name`, and `repo_selection` metadata to responses. If a tool has a `repo` parameter but the caller omits it, the response warns that Coder used the selected repo fallback. `select_repo` also returns explicit requested/resolved repo metadata. A deeper stateless rewrite is still optional future hardening.

Concern:
`scripts/run_mcp.py` keeps an active selected repository in process state. In long-running MCP processes, two clients or chats can accidentally affect each other if one changes the selected repo.

Why it matters:
The worst failure mode is silent wrong-repo answers. That is more dangerous than a visible error.

Preferred fix:
Move toward stateless tool calls where every repository-aware tool accepts an explicit `repo` argument and resolves it per request. Keep `select_repo` as a convenience only, with strong output warnings and repo echoes on every response.

Likely files:

- `scripts/run_mcp.py`
- `mcp_server/formatters.py`
- repo resolution helpers

Validation:

- Open two MCP sessions against different repos and verify one session cannot silently change the other's target.
- Ensure every response includes the resolved repo root or repo name.

### 2. Background reindex job state

Status:
Implemented first pass. Background reindex jobs now write a `job.json` state file beside `stdout.log` and `stderr.log`, and `reindex_status` can restore that persisted state after an MCP restart. If the restored job was still marked running, live process polling is not available after restart, so the response includes a warning and log tails. The MCP close path now releases DuckDB, Kuzu, vector-store, SQLite cache, and thread-local DuckDB handles before launching the child indexer, reducing self-inflicted database lock failures.

Concern:
Background reindex jobs have historically been tracked in memory. If the MCP server restarts, job state can disappear while the underlying index process may still be running or may already have completed.

Why it matters:
Users need reliable `reindex_status` answers after IDE restarts, MCP restarts, or crashes.

Preferred fix:
Persist job metadata to DuckDB or a small JSONL/job-state file. Include job id, repo root, started time, process id if available, command, status, error, and completed time.

Likely files:

- `scripts/run_mcp.py`
- `storage/duckdb_store.py`
- a small job-state service if this grows

Validation:

- Start background reindex.
- Restart MCP.
- Poll the same job id and get a useful status instead of "unknown".

### 3. Full-file reads in scanner

Status:
Implemented. The scanner now samples only a bounded prefix for heuristics, hashes files in chunks, and skips files larger than `CODER_SCAN_MAX_FILE_BYTES` with a progress warning.

Concern:
The scanner can load whole files into memory for hashing and exclusion checks.

Why it matters:
A checked-in database dump, binary-ish generated file, large CSV, or vendor blob can cause high memory use or an out-of-memory crash during indexing.

Preferred fix:
Use a streaming hash. Read only the first bounded chunk for minified/binary/exclusion heuristics. Apply a hard maximum file size for normal text indexing, with a clear skipped-file reason.

Likely files:

- `indexing/scanner.py`
- scanner tests and fixture files

Validation:

- Add a fixture with a large file.
- Confirm indexing skips or hashes it without loading the whole payload.

### 4. libclang isolation

Status:
Implemented. Public clang extraction now invokes `indexing.clang_worker` in a subprocess with a timeout, so native libclang crashes or hangs are isolated from the parent indexer process. Set `CODER_CLANG_IN_PROCESS=1` only for explicit debug/test scenarios.

Concern:
`libclang` runs native code inside the Python process. Bad C/C++ inputs, broken compile flags, deep macro/template cases, or native library issues can crash the whole process.

Why it matters:
C/C++ indexing should degrade gracefully. One bad translation unit should not kill the MCP server or the entire index run.

Preferred fix:
Run clang extraction in an isolated worker subprocess. Treat non-zero exit, timeout, or crash as a per-file parse failure with diagnostics, then fall back to tree-sitter or regex extraction.

Likely files:

- `indexing/clang_extractor.py`
- `indexing/native_build_context.py`
- coordinator parser dispatch code

Validation:

- Add a deliberately hostile C/C++ fixture.
- Verify the indexer logs a parse warning and continues.

### 5. Per-call thread pool creation in graph timeouts

Status:
Implemented. Graph timeout work now uses a shared bounded executor in `services/timeout_utils.py`, with `CODER_GRAPH_TIMEOUT_WORKERS` controlling worker count. API impact and git-aware change detection use the shared helper, and graph edge calls now go through compatibility helpers that preserve limits without assuming every graph adapter accepts `limit=`.

Concern:
Some timeout wrappers create a new `ThreadPoolExecutor` for each graph expansion.

Why it matters:
High-volume impact tools can spawn and tear down many OS threads, adding latency and risking thread exhaustion under load.

Preferred fix:
Use a shared bounded executor for graph timeout work, or inject an executor into services that need bounded graph calls. Keep cancellation and fallback behavior explicit.

Likely files:

- `services/api_impact_service.py`
- `services/impact_service.py`
- other services with `_with_timeout` helpers

Validation:

- Run API impact across many routes.
- Confirm stable thread counts and no latency spike from executor churn.

## Priority 2: Performance and Scale

### 6. JSON embedding cache bottleneck

Status:
Implemented. Embedding cache entries now persist in `embedding_cache.sqlite` instead of a single `embedding_cache.json` blob. Existing legacy JSON caches are migrated into SQLite and then removed.

Concern:
An `embedding_cache.json` file can become large and expensive to load, update, and rewrite.

Why it matters:
Large repos can turn cache misses into slow disk-heavy operations. JSON also has weak concurrency behavior.

Preferred fix:
Move embedding cache metadata to DuckDB, or rely on LanceDB plus deterministic chunk ids. If a local cache remains, make it append-friendly or partitioned.

Likely files:

- `storage/vector_store.py`
- embedding/chunk repository code

Validation:

- Index a large fixture or real repo twice.
- Confirm the second run does not spend meaningful time loading/writing a giant JSON file.

### 7. Embedding model concurrency and GPU memory behavior

Status:
First-pass hardening implemented. Local transformer embedding inference now runs under a shared lock, avoiding concurrent forward passes through the same model instance. `torch.cuda.empty_cache()` was removed from the embedding hot loop so PyTorch can keep its allocator warm. A dedicated embedding worker/queue remains optional future work if measured concurrency needs it.

Concern:
Embedding requests may share model state across threads. Calling `torch.cuda.empty_cache()` in the hot path can also force expensive synchronization and reduce throughput.

Why it matters:
Concurrent MCP searches and indexing can become slow or unstable, especially on GPU-backed local models.

Preferred fix:
Use a dedicated embedding worker or bounded queue that batches requests. Remove hot-path `empty_cache()` unless there is a measured leak and a deliberate cleanup mode.

Likely files:

- `embeddings.py`
- embedding service / vector store integration

Validation:

- Run concurrent semantic searches.
- Confirm stable latency and memory usage.

### 8. Token budget estimation

Status:
First-pass hardening implemented. Token-aware batching now uses the loaded tokenizer's `encode()` count when available, falling back to the previous conservative character estimate when tokenizer counting fails or dependencies are unavailable.

Concern:
Batching based on `chars / 4` can underestimate token counts for dense code, generated output, hex/base64 strings, or punctuation-heavy files.

Why it matters:
Providers or local models can reject oversized requests, causing indexing or review stages to fail late.

Preferred fix:
Use the model tokenizer where available. For OpenAI-style providers, use the correct tokenizer or a conservative fallback.

Likely files:

- `embedder.py`
- `embeddings.py`
- chunk batching code

Validation:

- Add dense-code and generated-text fixtures.
- Verify batches stay under the configured token limit.

### 9. Concurrent DuckDB writes from review workers

Status:
Implemented. Agent-review workers now return analysis records to the coordinator; the coordinator persists them through one main-thread bulk insert via `ReviewRepository.insert_agent_analyses()`. Per-analysis writes are no longer performed as futures complete.

Concern:
Concurrent analysis workers may each write review results to DuckDB.

Why it matters:
DuckDB allows one writer at a time. Many small concurrent writes can create lock contention and latency spikes.

Preferred fix:
Have workers return analysis records. Aggregate in the coordinator and write with one bulk insert on the main path.

Likely files:

- `app/coordinator.py`
- `storage/repositories.py`
- review repositories

Validation:

- Run many review jobs.
- Confirm writes happen in bulk and no lock timeout occurs.

### 10. Graph fan-out and hub objects

Status:
First-pass implemented. Graph neighborhood responses now include a `hub_summary` with raw/filtered edge counts, direct/incoming/outgoing counts, relation counts, top neighbors, truncation count, and guidance. Hub-like results are marked `partial` when capped and include an explicit warning so clients can avoid treating trimmed graph output as complete.

Concern:
High fan-out routes, hooks, headers, base classes, or utility modules can hit graph caps and return partial results.

Why it matters:
Partial results are acceptable, but users need clear "this is a hub" guidance instead of noisy or misleading truncated lists.

Preferred fix:
Precompute or cheaply derive hub scores such as fan-in/fan-out counts. For known hubs, return compact summaries, top dependents, relation counts, and a high-impact warning instead of deep traversal.

Likely files:

- `storage/kuzu_store.py`
- `services/impact_service.py`
- `services/api_impact_service.py`
- `services/change_report_service.py`

Validation:

- Test `GLOBAL_H`, central frontend API hooks, and common backend utilities.
- Confirm output is capped, summarized, and explicitly marked partial/truncated.

## Priority 3: Correctness and Maintainability

### 11. Graph synchronization during incremental updates

Status:
Implemented first-pass hardening. Kuzu already used `DETACH DELETE` for file/symbol cleanup; this now has real Kuzu regression coverage proving owned symbols and inbound/outbound edges disappear after file deletion. `KuzuStore.graph_integrity_report()` checks for symbols without matching file ownership, and `index_health` surfaces graph-integrity warnings through MCP.

Concern:
DuckDB symbols/files and Kuzu graph edges must remain synchronized when files are changed, deleted, or reindexed.

Why it matters:
Orphaned graph edges can produce stale callers, stale dependencies, or false impact reports.

Preferred fix:
Make file deletion/update transactional at the pipeline level where possible. Before re-upserting a file, remove all graph nodes and edges owned by that file. Add invariant checks for orphaned edges.

Likely files:

- `storage/kuzu_store.py`
- `storage/duckdb_store.py`
- `app/coordinator.py`
- graph builder code

Validation:

- Index a fixture repo.
- Delete or rename a file.
- Reindex incrementally and verify old symbols and edges are gone.

### 12. Hardcoded language and risk heuristics

Status:
First-pass implemented. Path-based language and platform risk hints now live in `services/risk_profiles.py` instead of the change report logic. `detect_changes_service` keeps its compatibility wrapper, but embedded-C sensitivity, high-risk path hints, and high-risk symbol hint classification are now centralized and covered by focused tests for embedded C/MPLAB, C#, and Object Pascal cases.

Concern:
Risk and test mapping logic contains growing language-specific rules for C#, C/C++, embedded C, Object Pascal, frontend, and backend conventions.

Why it matters:
The rules are valuable, but they can become a large hardcoded monolith as more languages and frameworks are added.

Preferred fix:
Move repeatable rules into language profiles or risk profiles, for example YAML/JSON definitions for sensitive paths, extensions, route patterns, test naming, and build artifacts. Keep code for orchestration and graph logic.

Likely files:

- `services/change_report_service.py`
- `services/test_intelligence_service.py`
- language-specific parser/indexer modules
- future `config/language_profiles.*`

Validation:

- Add one new rule through configuration only.
- Confirm existing Python/React/C/C++/C# behavior does not regress.

### 13. Security reviewer string heuristics

Status:
First-pass implemented. `SecurityReviewer` now uses parser/AST-derived symbol context for sensitive identifier handling and Python AST checks for dynamically constructed SQL execution. It ignores benign names such as design tokens, reports findings with symbol/line context, and labels the reviewer as `ast-graph-heuristic-v2`. Broader data-flow and graph-store-backed auth policy checks remain future work.

Concern:
Security checks that rely on simple substring matching can generate noisy false positives.

Why it matters:
Noisy security output trains users and agents to ignore warnings.

Preferred fix:
Use AST/graph facts where possible: variable names, call edges, imports, route metadata, auth middleware, field names, and data-flow-like heuristics.

Likely files:

- `security_reviewer.py`
- graph query services
- parser/indexer modules

Validation:

- Add fixtures for true positive and false positive token/auth cases.
- Confirm warnings are actionable and low-noise.

### 14. DuckDB read-only temp-copy fallback staleness

Status:
Implemented. When read-only DuckDB access falls back to a copied snapshot, `DuckDBStore.read_only_snapshot_metadata` records the source DB, snapshot DB, copy time, source mtime, reason, and stale-read risk. `index_health` surfaces that metadata and warns MCP clients that results may be stale.

Concern:
When the main DuckDB file is locked, read-only consumers may fall back to a temporary copied snapshot.

Why it matters:
That snapshot can become stale while indexing continues.

Preferred fix:
Surface snapshot metadata clearly in responses: copied-at time, source DB mtime, and stale-read warning. Prefer retry/backoff for short locks before copying.

Likely files:

- `storage/duckdb_store.py`
- `storage/connection_manager.py`
- MCP formatters if warnings need to surface

Validation:

- Force a write lock.
- Confirm read-only fallback reports snapshot/staleness metadata.

### 15. C macro expansion safety

Status:
Implemented. Macro extraction now keeps only simple object-like constants and safe CLI defines. It skips function-like, recursive, token-pasting/stringifying, very long, and suspicious macro bodies. Expansion revalidates macros before substitution.

Concern:
Regex-based macro expansion can behave poorly with recursive, function-like, or complex C macros.

Why it matters:
Embedded C code often has macro-heavy headers. Expansion should improve context without risking CPU spikes or misleading pseudo-code.

Preferred fix:
Only expand simple object-like constants. Skip function-like, recursive, very long, or suspicious definitions. Keep strict iteration and size caps.

Likely files:

- `indexing/native_build_context.py`
- C/C++ parser helpers

Validation:

- Add recursive and function-like macro fixtures.
- Confirm they are skipped safely.

## Roadmap-Adjacent Coverage Gaps

These are not defects, but they are useful to track separately from runtime hardening.

### Svelte and non-React frontend intelligence

Coder has strong React/TypeScript route and field-read coverage. Svelte/SvelteKit should be treated as a separate frontend parser expansion:

- `.svelte` component parsing
- SvelteKit route file conventions
- `load` functions and server/client data boundaries
- store subscriptions and reactive statements
- field reads inside markup and script blocks

### More backend framework styles

FastAPI and several mainstream route styles are covered at first-pass depth. Additional frameworks should be added by fixture-driven parser work, not broad regex expansion.

Examples:

- Express variants with router composition
- NestJS decorators and controllers
- Spring annotations beyond common mappings
- ASP.NET minimal APIs and endpoint routing variants

### C/C++ and C# workflow depth

C/C++/C# support is useful today for symbols, chunks, dependency basics, and some risk/test guidance. Deeper parity still needs:

- richer call graphs
- build target and test target mapping
- include/import blast radius
- C# DTO field usage and interface/override precision
- controller/service/repository process tracing

## Suggested Incremental Work Order

1. Make scanner file reads streaming and size-bounded.
2. Persist background reindex job state across MCP restarts.
3. Reduce wrong-repo risk by making MCP repo resolution more stateless and explicit.
4. Replace per-call graph timeout executors with a shared bounded executor.
5. Isolate libclang extraction in a subprocess.
6. Move embedding cache away from a single large JSON file.
7. Add exact tokenizer-based batching.
8. Convert language/risk heuristics into profiles.
9. Add graph sync invariant tests for deleted and renamed files.
10. Improve hub-node summaries and high-fan-out risk output.

## Definition of Done for Each Item

Each hardening item should include:

- a focused unit or fixture test
- a live MCP smoke when the behavior affects tool output
- a clear warning or partial flag when the tool intentionally degrades
- no silent wrong-repo, stale-index, or stale-graph behavior
