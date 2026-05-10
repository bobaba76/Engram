# Code Intelligence Handoff

## Purpose

This document is the current handoff for Coder / Engram code-intelligence work. It replaces the older incremental notes, which had become stale after the Phase 1/2 roadmap work landed.

The goal remains GitNexus-style workflow intelligence for IDE agents:

- git-aware change detection
- API, route, consumer, and response-shape impact
- symbol-level graph context
- frontend field-read blast radius
- process/flow tracing
- risk-sensitive change reports
- pre-commit workflow slicing and test guidance

## Current State

Coder is now far beyond the original Phase 1 and Phase 2 baseline.

Completed and validated:

- explicit git/risk scope metadata
- per-file, per-route, and per-process risk signals
- FastAPI, Flask, Django, and Express route extraction
- frontend `apiClient`, `axios`, and `fetch` consumer extraction
- frontend route constant support
- API wrapper to component propagation
- response-shape extraction and shape checking
- nested frontend field reads, including array items and Recharts `dataKey`
- graph-backed `FETCHES` and `READS_FIELD` contract impact
- graph-backed C/C++ `INCLUDES` impact
- explicit OO member ownership through `HAS_METHOD` and `HAS_PROPERTY`
- `field_impact` lookup
- route-aware `api_impact`
- changed-route and affected-consumer reporting in change reports
- process/flow tracing with route-first ranking
- pre-commit commit-slice planning
- validation/readiness and residual risk after validation
- safe broad-diff behavior for MCP change tools
- README refresh
- LLM/reviewer layer documented as currently disabled

Latest local validation:

```text
python -m pytest
155 passed
```

Latest live MCP smoke against Stock `/products/trends`:

- `route_map` returned quickly and found backend handler plus frontend consumers.
- `api_impact` returned route process flows, graph fetchers, field readers, risk, and shape status.
- `field_impact` found `chart_data[].intransit_stock` readers.
- `shape_check` returned `OK`.

## What Is Strong Today

### Python Backend Intelligence

Coder can extract and reason about:

- function/class symbols
- imports and calls
- FastAPI route decorators
- Flask route decorators
- Django `path` / `re_path` routes
- response keys from returned dictionaries
- common Pydantic response model fields
- nested response keys
- changed route handlers
- backend route to service/repository flow traces

### TypeScript / React Frontend Intelligence

Coder can extract and reason about:

- TypeScript/TSX/JS/JSX symbols
- imports, calls, references, and property accesses
- direct API calls through `apiClient`, `axios`, and `fetch`
- optional API client calls such as `apiClient?.post(...)`
- simple route constants
- wrapper API functions
- wrapper-to-component consumers
- React Query-style wrapper usage
- optional chaining
- destructured response fields
- simple response aliases
- array callback reads such as `chart_data.map(point => point.qty_sold)`
- chart field reads such as `<Bar dataKey="intransit_stock" />`

### Git-Aware Change Intelligence

`detect_changes` and `change_impact_report` now report:

- diff source and git metadata
- changed files
- changed symbols
- impacted files/symbols
- risk scope
- risk applies-to metadata
- confidence and confidence explanation
- risk explanation
- risk by file
- changed routes
- changed response shapes
- affected consumers
- affected processes
- shape mismatches
- broad-diff guardrail warnings

The broad-diff path is intentionally bounded. If a working tree is too large for exhaustive graph/process traversal, Coder returns partial but useful output instead of hanging the MCP client.

### API / Route / Contract Intelligence

Current tools:

- `route_map`
- `api_impact`
- `shape_check`
- `field_impact`

These tools can connect:

- route handlers
- response keys
- nested response keys
- frontend API wrappers
- component consumers
- graph-backed fetchers
- graph-backed field readers
- shape mismatches
- process flows

Example capability:

```text
/products/trends is handled by backend/routers/products.py:get_product_trends,
fetched by frontend/src/services/api.ts:getProductTrends,
and read by ProductTrendModal fields such as metrics.intransit_stock and chart_data[].qty_sold.
```

### Symbol And Graph Context

Current graph/context support includes:

- `CALLS`
- `IMPORTS`
- `INCLUDES`
- `REFERENCES`
- `DECLARES`
- `ASSOCIATED_WITH`
- `ACCESSES`
- `EXTENDS`
- `IMPLEMENTS`
- `METHOD_OVERRIDES`
- `METHOD_IMPLEMENTS`
- `FETCHES`
- `READS_FIELD`
- `HAS_METHOD`
- `HAS_PROPERTY`

Symbol context now exposes:

- callers
- callees
- categorized references
- related symbols by relation
- relation counts
- graph context
- route/process participation where available

### Process / Flow Intelligence

Current process support includes:

- bounded flow tracing from symbols/routes
- route-aware process labels
- route-first ranking over tests/report helpers
- changed-symbol overlays in flows
- process risk factors
- process summaries inside `api_impact`
- process blast-radius fields in pre-commit reports

This is useful and live, but it is not yet a perfect process catalog. The next improvements should be about quality and ranking, not proving the concept.

### Pre-Commit Workflow Intelligence

`change_impact_report` now groups changes into recommended commit slices.

Each slice can include:

- files
- routes
- consumers
- fields
- affected processes
- what can break
- what to test
- follow-up MCP tools
- validation status
- residual risk after validation

This is the most important practical workflow added after the route/API work.

## Current MCP Tool Surface

Key tools for IDE agents:

- `list_repos`
- `select_repo`
- `resolve_target`
- `semantic_code_search`
- `investigate_codebase`
- `get_source_context`
- `unified_context`
- `get_symbol_context`
- `impact_analysis`
- `app_context`
- `detect_changes`
- `change_impact_report`
- `suggest_tests_for_change`
- `find_tests_for_target`
- `route_map`
- `api_impact`
- `shape_check`
- `field_impact`
- `trace_processes`
- `index_status`
- `index_health`

All broad tools should preserve predictable response fields where possible:

- `status`
- `warnings`
- `confidence`
- `next_tools`
- `top_files`
- `top_symbols`
- `partial`
- `compact_summary`

## Important Files

Core MCP/runtime:

- `scripts/run_mcp.py`
- `mcp_server/formatters.py`
- `mcp_server/resolvers.py`

Route/API/field intelligence:

- `services/route_parsing.py`
- `services/route_map_service.py`
- `services/api_impact_service.py`
- `services/shape_check_service.py`
- `services/field_impact_service.py`

Git/change intelligence:

- `services/detect_changes_service.py`
- `services/change_report_service.py`
- `scripts/git_change_snapshot.py`

Graph/symbol/process intelligence:

- `indexing/graph_builder.py`
- `indexing/parsers/python.py`
- `indexing/parsers/typescript.py`
- `storage/kuzu_store.py`
- `services/graph_service.py`
- `services/impact_service.py`
- `services/process_service.py`
- `services/symbol_context_service.py`
- `services/unified_context_service.py`

Test intelligence:

- `services/test_intelligence_service.py`

Current high-value tests:

- `tests/test_api_impact_service.py`
- `tests/test_field_impact_service.py`
- `tests/test_graph_builder.py`
- `tests/test_graph_service.py`
- `tests/test_impact_change_frontend_signal.py`
- `tests/test_mcp_formatters.py`
- `tests/test_mcp_symbol_context_wiring.py`
- `tests/test_parser_registry.py`
- `tests/test_process_service.py`
- `tests/test_route_map_service.py`
- `tests/test_shape_check_service.py`
- `tests/test_symbol_context_service.py`
- `tests/test_test_intelligence_service.py`
- `tests/test_unified_context_service.py`

## Current Limitations

These are real remaining gaps, not stale Phase 1/2 items.

### Frontend Parsing Hardening

Current frontend extraction is useful but still partly heuristic.

Worth doing:

- AST-native field-read extraction rather than mostly regex/local snippets.
- Stronger alias import resolution across files.
- Better wrapper-chain resolution when API calls pass through multiple layers.
- Better dynamic route support where route strings are composed from constants/templates.
- Better React hook/component propagation beyond common React Query patterns.

Do not over-polish here unless a real repo example fails. The current Stock path is already substantially improved.

### Backend Response Shape Hardening

Current backend shape extraction handles common inline dictionaries, returned payload variables, Pydantic-style models, and some framework variants.

Worth doing:

- helper functions that build response payloads
- route handlers returning helper-call results
- deeper Pydantic nesting and aliases
- dataclass/attrs response objects
- framework-specific serializers
- more JS/TS backend response variants

### Process Catalog Quality

Current process tracing works, but deeper GitNexus parity would require better process cataloging.

Worth doing:

- more explicit route -> service -> repository clustering
- terminal node classification
- entrypoint type labels
- process ranking from real validation examples
- better process grouping across repeated helper flows

### Risk Calibration

Risk is now explainable and validation-aware, but still mostly heuristic.

Worth doing:

- calibrate thresholds from real repos and observed false positives
- use actual test execution results when available
- distinguish additive vs breaking contract changes more precisely
- tune broad-diff escalation so CRITICAL/HIGH is useful rather than noisy

### Fixture And Smoke Coverage

Unit coverage is good. More fixture-level coverage would help.

Worth doing:

- fixture repos for route/API scenarios
- fixture repos for process tracing
- fixture repos for inheritance and field access
- live MCP smoke tests that validate latency and compact output shape

### Documentation Examples

README is current, but deeper docs could still help MCP consumers.

Worth doing:

- example outputs for `route_map`
- example outputs for `api_impact`
- example outputs for `shape_check`
- example outputs for `field_impact`
- example outputs for `detect_changes` and `change_impact_report`

## C/C++/C# Status

Recent GitNexus-style optimization has mostly targeted Python and React/TypeScript because Stock, the live validation repo, uses that stack.

C/C++ and C# are supported, but they do not yet have the same workflow-intelligence depth.

### C/C++ Current Support

Current support:

- scanner coverage for `.c`, `.h`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx`
- C-family parser
- `libclang` preferred when available
- tree-sitter fallback
- regex fallback
- first-pass native build-context discovery from `compile_commands.json`, CMake, Make, Visual Studio solution/project markers
- first-pass CMake `add_library` / `add_executable` target ownership when `compile_commands.json` is absent
- parser and index-health visibility for build context confidence, include dirs, defines, standards, compilers, and targets
- explicit native source/header graph relations: `DECLARES_IN_HEADER` and `DEFINES_IMPLEMENTATION`
- explicit native include graph relation: `INCLUDES`
- native header changes are treated as high-risk public/native surface changes in git-aware reports
- native build target/config and exported API/ABI files are treated as high-risk in git-aware reports
- native build targets are surfaced on changed symbols/files when build context can identify ownership
- public header type/typedef/class/macro/constant changes are flagged as ABI/layout surface changes
- C/C++ test suggestions understand common `test_thing.cpp`, `thing_test.cpp`, and related naming conventions
- symbols, includes/import-like metadata, references, calls, and chunks depending on parser confidence

Current limitation:

- build-context discovery exists, but C/C++ graph quality still needs deeper target ownership, source/header pairing, callback handling, and ABI-aware impact before it reaches Python/React workflow depth.
- C/C++ graph quality is now useful for include/header blast radius, but still needs deeper target ownership, callback handling, and ABI-aware impact before it reaches Python/React workflow depth.
- C/C++ graph quality is now useful for include/header blast radius and first-pass build target ownership, but still needs callback handling and deeper ABI-aware impact before it reaches Python/React workflow depth.

### C# Current Support

Current support:

- C# parser module
- tree-sitter/regex fallback style extraction
- symbols and graph basics
- first-pass ASP.NET route extraction for controller attributes and minimal APIs
- route map/API impact compatibility for C# handlers
- first-pass C# DTO response-shape extraction from records/classes and `ActionResult<T>`
- first-pass dependency-injection registrations from `AddScoped`, `AddTransient`, and `AddSingleton`
- graph `INJECTS` edges from registered service/interface to implementation
- constructor-injected service dependencies as `USES_SERVICE` edges
- process tracing can follow controller/method -> interface -> implementation service paths
- C# public route/API, DTO/contract, DI/config, and migration/schema files are risk-sensitive in git-aware reports
- C# test suggestions understand common `.Tests` project and `ThingTests.cs` naming conventions

Current limitation:

- full repository/data-access classification and deeper C# risk calibration from real repo validation are not yet implemented.

## C/C++ Workflow Roadmap

### 1. Build Context

First-pass build-context discovery is implemented. The remaining work is to make it richer and use it more deeply in graph/risk workflows.

Implemented:

- detect `compile_commands.json`
- detect common CMake, Make, solution, and Visual Studio project markers
- map simple CMake `add_library` and `add_executable` sources to target names
- capture include paths
- capture defines/macros
- capture compiler flags
- capture C vs C++ standard
- expose build-context confidence in `index_status` and `index_health`

Still worth doing:

- map files to build targets more precisely across nested/variable-heavy CMake projects
- parse richer CMake target sources when lists are stored in variables
- use build target ownership for commit slicing and test selection

Why:

- Clang can only resolve real C/C++ semantics when it has the same build flags and include paths as the compiler.

### 2. Source/Header Pairing

First-pass graph pairing and include blast-radius support are implemented for matching native header and implementation symbols.

Implemented:

- pair `.h/.hpp` declarations with `.c/.cpp` definitions
- link declarations to implementations
- add `DECLARES_IN_HEADER`
- add `DEFINES_IMPLEMENTATION`
- add `INCLUDES` for native include/import blast radius
- surface those relations through graph/symbol context

Still worth doing:

- distinguish public headers from private/internal headers
- classify high fan-in headers
- make parser qualified names robust enough to avoid declaration/definition symbol collisions in every C/C++ style

Implemented/target relations:

- `DECLARES`
- `DEFINES_IMPLEMENTATION`
- `DECLARES_IN_HEADER`
- `INCLUDES`
- `PUBLIC_API_HEADER`

### 3. Semantic Call Graph

Implement:

- clang USR/canonical-name identity where available
- namespace/class-aware symbol IDs
- overload-aware call edges
- constructor/destructor edges
- virtual method and override edges
- lower-confidence function pointer and callback edges
- macro-expanded or unresolved call confidence metadata

### 4. Entrypoints And Terminals

Implement entrypoint detection for:

- `main`
- exported/shared-library symbols
- task/thread entrypoints
- callback registrations
- CLI command handlers
- RPC/HTTP handlers where present
- firmware loops

Implement terminal detection for:

- file I/O
- sockets/network
- database/client calls
- hardware/register access
- external library boundaries
- process/thread creation

### 5. C/C++ Change Reports

First-pass C/C++-specific risk and blast radius is implemented.

Implemented:

- changed public header
- changed native build target/config
- changed exported API/ABI map-style files
- changed native build target ownership
- changed public header ABI/layout symbols
- include/header graph blast radius through `INCLUDES`
- native test naming recommendations

Still worth doing:

- changed exported function
- changed struct/class layout
- changed enum/typedef
- changed public macro
- changed virtual interface
- high fan-in include scoring from graph fan-in
- ABI risk
- richer build target ownership across complex CMake/Make/Visual Studio layouts

Desired output:

- downstream files
- affected build targets
- impacted entrypoint flows
- affected exported API/ABI surfaces
- suggested tests
- risk explanation

## C# Workflow Roadmap

### 1. ASP.NET Route Extraction

First-pass route extraction is implemented.

Implemented:

- controller route attributes
- action method HTTP attributes
- minimal APIs such as `MapGet`, `MapPost`, `MapGroup`
- route prefixes
- `[controller]` token normalization
- route map integration

Still worth doing:

- middleware and filters where practical
- request/response type extraction

### 2. DTO And Shape Extraction

First-pass DTO shape extraction is implemented.

Implemented:

- records/classes used as request DTOs
- records/classes used as response DTOs
- collection fields
- nested DTOs
- controller return types such as `ActionResult<ProductDto>`
- camel-case JSON field projection for C# properties/record parameters

Still worth doing:

- nullable field semantics
- serialized property names from JSON attributes
- minimal API typed result wrappers beyond the first simple cases
- request DTO extraction and request-shape impact

Use this for:

- route response shape
- consumer compatibility
- breaking vs additive field changes

### 3. Dependency Injection Graph

First-pass DI graph extraction is implemented.

Implemented:

- `AddScoped`
- `AddTransient`
- `AddSingleton`
- interface-to-implementation mappings
- `INJECTS` graph relation
- constructor parameter dependencies
- `USES_SERVICE` graph relation
- process tracing over `CALLS`, `USES_SERVICE`, and `INJECTS`

Still worth doing:

- factory registrations
- open generic registrations
- hosted services
- constructor parameter to concrete implementation resolution in compact summaries
- use DI edges in risk scoring more deeply

### 4. Controller/Service/Repository Flows

First-pass controller-to-service tracing is implemented through constructor dependencies and DI registrations.

Currently traceable:

- controller/minimal API entrypoint
- service method

Still worth doing:

- repository/data access
- database or external HTTP client
- queue/event publisher
- response DTO return

Desired output:

- affected route/action
- affected service/repository chain
- affected DTOs
- affected tests
- risk by route/process/project

### 5. C# Test Mapping

First-pass C# test naming support is implemented.

Implemented:

- project/namespace conventions
- class and method names
- controller/service/repository names
- `.Tests` project/folder markers
- `ThingTests.cs`, `ThingTest.cs`, and `ThingSpecs.cs` naming

Still worth doing:

- xUnit/NUnit/MSTest attribute-aware test mapping
- route name to test mapping
- symbol-level test method ranking

### 6. C# Risk Model

First-pass path-sensitive C# risk is implemented.

Currently escalates for:

- public controller route changes
- DTO shape changes
- DI rewires
- migrations/schema changes

Still worth doing:

- auth/middleware/filter changes
- high fan-in interfaces/services
- shared package/project changes
- calibration from real C# repo validation

## Practical Next Milestones

The highest-value next milestones are:

1. Add C/C++ build-context discovery and index-health reporting.
2. Add ASP.NET route and DTO extraction for C#.
3. Add AST-native frontend field-read extraction only where current heuristics fail real repo examples.
4. Add fixture repos and smoke tests for route/API/process/change workflows.
5. Calibrate risk from real validation results and actual test execution evidence.

## Compatibility Notes

Keep these fields stable for MCP consumers:

- `status`
- `warnings`
- `confidence`
- `next_tools`
- `partial`
- `compact_summary`
- `top_files`
- `top_symbols`
- `risk`
- `risk_scope`
- `changed_files`
- `changed_symbols`
- `impacted_files`
- `impacted_symbols`
- `routes`
- `handlers`
- `consumers`
- `callers`
- `callees`

Prefer adding new fields over replacing existing fields.

## Operational Notes

- Restart the MCP server after code changes; live MCP behavior reflects the running process.
- Keep broad-query tools bounded and partial-friendly.
- Preserve Windows path handling.
- Avoid adding slow eager startup work to `scripts/run_mcp.py`.
- `list_repos` should stay lightweight and should not require opening DuckDB, Kuzu, LanceDB, or embedding models.
- Do not re-enable LLM/reviewer workflows without a deliberate validation pass.

## Validation Checklist

Before handoff or PR:

```powershell
python -m pytest
```

Recommended live smoke after restart:

```text
route_map(repo="Stock", route="/products/trends")
api_impact(repo="Stock", route="/products/trends")
field_impact(repo="Stock", route="/products/trends", field="chart_data[].intransit_stock")
shape_check(repo="Stock", route="/products/trends")
detect_changes(repo="Stock", scope="unstaged")
change_impact_report(repo="Stock", scope="unstaged")
```

Expected live behavior:

- route/API tools return quickly
- ProductTrendModal field reads are visible
- graph-backed fetchers/readers are present where indexed
- shape status is clear
- broad change tools return bounded output or explicit partial warnings instead of timing out

## Bottom Line

The original Python/React GitNexus-style roadmap is mostly implemented at useful first-pass depth.

The remaining work is not "finish Phase 1/2"; it is:

- harden real-world edge cases
- improve process/risk quality from validation
- add fixture and smoke coverage
- bring C/C++/C# up toward the same workflow-intelligence depth
