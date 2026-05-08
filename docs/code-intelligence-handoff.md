# Code Intelligence Handoff

## Purpose

This document hands off the current Code Intelligence enhancement work for Coder. The goal is to continue moving Coder toward GitNexus-style code intelligence: richer graph context, API/route/consumer impact, shape checking, git-aware risk reporting, and process/flow-aware change analysis.

## Current Status

Coder now has a solid implementation of the original Phase 1 and Phase 2 scope, plus several Phase 3-style graph/process integrations. Recent live Stock validation also confirmed deeper frontend field reads, alias-aware route/process tracing, and faster local git-change reporting for a broad working tree.

Latest validation:

- Full test suite: `126 passed`.
- Stock full reindex run ID: `2b83e937`.
- Live MCP `trace_processes` now ranks `get_product_trends` above report/test callers for `get_product_trend_data`.
- Local Stock `detect_changes` completed in about 7 seconds for a 30-file working tree after broad-diff guardrails.
- Local Stock `change_impact_report` completed in about 12 seconds and populated frontend graph route-consumer signals.

## Completed Work

### MCP Startup Reliability

Completed in `scripts/run_mcp.py`.

Implemented:

- Removed eager repo context opening during MCP startup.
- Removed eager Kuzu graph opening during MCP startup.
- Moved embedding model pre-warming to the semantic-search path instead of server boot.
- Kept lightweight tools such as `list_repos` independent of DuckDB, LanceDB, Kuzu, and transformer startup.
- Added a regression test to keep heavy startup resources lazy.

Validation:

- `list_repos` returned successfully through the live MCP attachment in ~0.02s after the fix.

### Phase 1: Git-Aware Risk Output

Completed in `services/detect_changes_service.py` and propagated through `services/change_report_service.py`.

Implemented:

- Structured git metadata.
- Risk scope and risk applicability metadata.
- Per-file risk output.
- Confidence level and confidence explanation.
- Risk explanations.
- Compact summaries for change reports.
- Propagation into `change_impact_report`.

Key output fields now include:

- `git`
- `risk_scope`
- `risk_applies_to`
- `risk_explanation`
- `risk_by_file`
- `confidence`
- `confidence_explanation`
- `compact_summary`

### Phase 2: API / Route / Consumer Impact

Completed across:

- `services/route_map_service.py`
- `services/route_parsing.py`
- `services/api_impact_service.py`
- `services/shape_check_service.py`
- `scripts/run_mcp.py`

Implemented:

- FastAPI route handler extraction.
- Route normalization, including `/api` prefix normalization and trailing slash normalization.
- Frontend consumer detection for `apiClient`, `axios`, and `fetch`.
- Frontend consumer metadata, including file path, function/component name, route, and method when available.
- API wrapper-to-component propagation.
- Backend response key extraction.
- Nested response key extraction.
- Array item response key extraction, such as `items[].id`.
- Consumer field-read extraction.
- Shape mismatch detection between backend responses and frontend field reads.
- `shape_check` MCP tool registration.

Additional hardening completed:

- FastAPI decorator parsing now keeps decorator arguments such as `response_model=...`.
- Pydantic-style response model field extraction is used as route response-shape evidence.
- Nested Pydantic-style model fields are surfaced as nested response-shape evidence.
- List item Pydantic-style models are surfaced as `field[]` nested response-shape evidence.
- Simple returned payload variables are resolved back to inline dictionary shapes.
- TypeScript API wrapper detection handles return annotations such as `Promise<any>`.
- Frontend field-read extraction handles optional chaining, destructured response fields, and simple aliases such as `const metrics = data.metrics`.
- Frontend field-read extraction handles common chart `dataKey="..."` usage tied to route data arrays.
- Wrapper propagation covers React Query-style `queryFn: () => getWrapper()` consumers.
- Wrapper propagation now links annotated API functions to UI reads in fresh-process validation.
- Frontend direct API route call detection now uses tree-sitter AST parsing for TypeScript/TSX/JS/JSX when available, with regex fallback.
- AST route detection handles member calls such as `apiClient.get(...)`, `axios.post(...)`, `fetch(...)`, and optional member calls such as `apiClient?.post(...)`.

### Git-Aware Route/API Integration

Completed in:

- `services/detect_changes_service.py`
- `services/change_report_service.py`

Implemented:

- Changed route detection from git diffs.
- Affected consumer reporting.
- Changed response shape reporting.
- Route-level risk output.
- Shape mismatch risk escalation.
- Route/API metadata propagation into `change_impact_report`.
- Candidate-route-first change analysis so broad diffs do not shape-check every route in the repo.
- Broad-diff guardrails that skip exhaustive graph/process traversal and return warnings instead of timing out.
- `change_impact_report` reuses already-computed change data when suggesting tests, avoiding duplicate `detect_changes` work.

Key output fields include:

- `changed_routes`
- `affected_consumers`
- `changed_response_shapes`
- `risk_by_route`
- `shape_mismatches`

### Process / Flow Integration

Completed in:

- `services/detect_changes_service.py`
- `services/change_report_service.py`

Implemented:

- Integration with existing process tracing from `services/process_service.py`.
- Affected process reporting for changed symbols.
- Process risk reporting.
- Risk escalation based on process impact.
- Propagation into `change_impact_report`.
- Process entrypoint ranking now prefers route handlers over report helpers and tests.

Key output fields include:

- `affected_processes`
- `risk_by_process`

### Route Parsing Refactor

Completed in:

- `services/route_map_service.py`
- `services/route_parsing.py`

Implemented:

- Extracted route parsing regexes and helper functions into `route_parsing.py`.
- Kept `route_map_service.py` focused on orchestration and aggregation.
- Fixed Windows path escaping issues in the refactor.

### Deeper Symbol Graph Context

Completed in:

- `services/graph_service.py`
- `services/unified_context_service.py`
- `services/symbol_context_service.py`
- `scripts/run_mcp.py`

Implemented:

- Categorized references for symbol context.
- Backward-compatible `callers` and `callees` fields.
- Relation metadata for available graph relations.
- Relation counts.
- Related symbols grouped by relation.
- Surfaced richer graph context through `unified_context`.
- Added optional graph enrichment to `get_symbol_context` via `kuzu_store`.
- Wired MCP `get_symbol_context` to pass `kuzu_store`.

Relations currently covered:

- `CALLS`
- `IMPORTS`
- `REFERENCES`
- `DECLARES`
- `ASSOCIATED_WITH`
- `ACCESSES`
- `EXTENDS`
- `IMPLEMENTS`
- `METHOD_OVERRIDES`
- `METHOD_IMPLEMENTS`

New fields include:

- `categorized_references`
- `related_symbols_by_relation`
- `relation_counts`
- `graph_context`

### Richer Graph Relations

Completed first-pass support across:

- `indexing/parsers/python.py`
- `indexing/parsers/typescript.py`
- `indexing/graph_builder.py`
- `storage/kuzu_store.py`
- `services/graph_service.py`
- `services/impact_service.py`
- `services/semantic_search.py`
- `services/search_ranking.py`

Implemented:

- Property/field access metadata from Python and TypeScript/TSX parsing.
- Synthetic property symbols such as `property:data.metrics.intransit_stock`.
- `ACCESSES` edges from symbols to property symbols.
- Python class base extraction.
- TypeScript class/interface `extends` extraction.
- TypeScript class `implements` extraction.
- `EXTENDS` and `IMPLEMENTS` graph edges.
- Basic method override/implementation inference from matching method names on related classes/interfaces.
- `METHOD_OVERRIDES` and `METHOD_IMPLEMENTS` graph edges.
- Impact/search/graph-context visibility for the new relations.

Live Coder reindex validation:

- Full reindex run ID: `0c65ce72`.
- Graph rebuilt with `15,295` edges.
- MCP graph query reported `4,377` `ACCESSES` edges.
- MCP graph query reported `20` `EXTENDS` edges.
- MCP graph query reported `27` `METHOD_OVERRIDES` edges.

### Process-Aware API Impact

Completed in:

- `services/api_impact_service.py`
- `scripts/run_mcp.py`
- `services/process_service.py`

Implemented:

- `api_impact` accepts optional Kuzu graph context.
- MCP `api_impact` passes graph context so route handlers can include bounded execution-flow summaries.
- Route output now includes a `processes` list with flow name, entry symbol, step count, module, symbols, and step details.
- Compact summaries include `top_processes`.
- Process flow labels now use ASCII `->` for Windows-safe console/MCP output.
- Route mapping ignores obvious test fixture paths so app route maps are not polluted by test decorators.
- Process flow ranking now prefers project/app symbols over generic runtime or collection/string terminal calls.
- Generic terminal flows such as `max`, `now`, `values`, `items`, `lower`, and `upper` are suppressed when more actionable project flows exist.
- API impact process names are route-aware, for example `GET /products/trends -> get_product_trends -> ...`.
- API impact route risk now includes consumers, traced process flows, shape mismatches, and deep-flow factors.

Fresh-process validation against Stock:

- `/products/trends` resolved one backend handler.
- Wrapper propagation found three frontend consumers.
- Shape check status was `OK`.
- Route risk was `MEDIUM` with factors for three consumers and three traced process flows.
- Process-aware API impact found route-aware flows such as `GET /products/trends -> get_product_trends -> build_branch_breakdown -> ...`.

## New / Modified Important Files

### Services

- `services/api_impact_service.py`
- `services/change_report_service.py`
- `services/detect_changes_service.py`
- `services/graph_service.py`
- `services/route_map_service.py`
- `services/route_parsing.py`
- `services/shape_check_service.py`
- `services/symbol_context_service.py`
- `services/unified_context_service.py`

### MCP Entrypoint

- `scripts/run_mcp.py`

### Tests

- `tests/test_api_impact_service.py`
- `tests/test_graph_service.py`
- `tests/test_impact_change_frontend_signal.py`
- `tests/test_mcp_symbol_context_wiring.py`
- `tests/test_route_map_service.py`
- `tests/test_shape_check_service.py`
- `tests/test_symbol_context_service.py`
- `tests/test_unified_context_service.py`

## Validation Command

Use this focused validation command after continuing this work:

```bash
python -m pytest tests/test_mcp_symbol_context_wiring.py tests/test_symbol_context_service.py tests/test_unified_context_service.py tests/test_graph_service.py tests/test_route_map_service.py tests/test_api_impact_service.py tests/test_shape_check_service.py tests/test_impact_change_frontend_signal.py
```

Last known result:

```text
20 passed
```

Before final handoff or PR, also run the full suite:

```bash
python -m pytest
```

## What Is Left From the Original Roadmap

The core Phase 1 and Phase 2 work is complete. The remaining work is mostly deeper GitNexus-parity functionality and hardening.

### 1. Richer Graph Schema and Relationship Types

First-pass support is complete for:

- `ACCESSES`
- `EXTENDS`
- `IMPLEMENTS`
- `METHOD_OVERRIDES`
- `METHOD_IMPLEMENTS`

Recommended next work:

- Harden property access extraction with AST-native TypeScript nodes.
- Add explicit member ownership relations such as `HAS_METHOD` and `HAS_PROPERTY`.
- Improve method override matching beyond same-name heuristics.
- Add C# / C-family inheritance relation support.

Likely files to update:

- `storage/kuzu_store.py`
- `indexing/graph_builder.py`
- language-specific parsers under `indexing/`
- `services/graph_service.py`
- `services/impact_service.py`
- relevant tests under `tests/`

### 2. AST-Based Frontend Parsing

Direct frontend route-call parsing now has a first AST-based implementation. Consumer field reads and wrapper propagation still rely mostly on regex plus local heuristics.

Recommended next work:

- Extend AST-based parsing from direct API calls to consumer field reads.
- Improve destructured response read detection.
- Improve aliased import detection.
- Improve dynamic route string handling.
- Improve wrapper chain resolution.
- Improve React hook/component propagation.

Likely files to update:

- `services/route_parsing.py`
- `services/route_map_service.py`
- TypeScript parser/indexer code under `indexing/`
- `tests/test_route_map_service.py`
- `tests/test_api_impact_service.py`

### 3. Better Backend Response Shape Extraction

First-pass support is complete for Pydantic-style `response_model` fields and common inline dictionaries. It should still be hardened for more backend styles.

Recommended next work:

- Support helper functions that build response payloads.
- Support route handlers returning variables assigned from helper calls.
- Support nested Pydantic models and list item models.
- Support framework variants beyond FastAPI where relevant.

Likely files to update:

- `services/route_parsing.py`
- `services/api_impact_service.py`
- backend parser/indexing files under `indexing/`
- `tests/test_api_impact_service.py`
- `tests/test_shape_check_service.py`

### 4. More Precise Process Modeling

Current process integration uses existing flow tracing. API impact now includes bounded route handler flows when graph context is available. It is useful but not yet a full process catalog comparable to GitNexus.

Recommended next work:

- Connect route handlers to service/repository execution paths more explicitly.
- Continue improving route-aware process labels and terminal ranking.
- Include terminal nodes and entry point types in change reports.
- Improve process clustering and ranking.

Likely files to update:

- `services/process_service.py`
- `services/process_catalog_service.py`
- `services/detect_changes_service.py`
- `services/change_report_service.py`
- `services/api_impact_service.py`

### 5. Impact Analysis Integration With New Graph Relations

After adding richer graph edges, update impact analysis to use them.

Recommended next work:

- Include `ACCESSES` in field-impact mode.
- Include `EXTENDS` / `IMPLEMENTS` for inheritance impact.
- Include method override/implementation impact.
- Report relation-specific risk explanations.
- Add compact summaries for high-risk relation types.

Likely files to update:

- `services/impact_service.py`
- `services/graph_service.py`
- `services/detect_changes_service.py`
- `services/change_report_service.py`

### 6. MCP Output and Documentation Hardening

Recommended next work:

- Update README with new tools and fields.
- Document `route_map`, `api_impact`, `shape_check`, `detect_changes`, `change_impact_report`, `get_symbol_context`, and `unified_context` outputs.
- Add example MCP responses.
- Add compatibility notes for output consumers.

Likely files to update:

- `README.md`
- `scripts/run_mcp.py`
- docs under `docs/`

### 7. Full-Suite and Real-Repo Testing

The focused tests pass, but the next developer should run and stabilize the full suite.

Recommended next work:

- Run `python -m pytest`.
- Add fixture repos for route/API scenarios.
- Add fixture repos for process tracing.
- Add fixture repos for inheritance and field access once those graph relations exist.
- Add MCP smoke tests around registered tool outputs.

### 8. C/C++/C# Workflow Intelligence

Current status:

- C/C++ files are scanned and parsed through the C-family parser.
- C/C++ parsing prefers `libclang`, falls back to tree-sitter, then regex.
- C/C++ extensions currently include `.c`, `.h`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, and `.hxx`.
- C# has parser support, but does not yet have deep ASP.NET / DTO / dependency-injection workflow intelligence.
- The recent GitNexus-style workflow improvements were mostly optimized around Python backends and React/TypeScript frontends.

Goal:

- Bring C/C++ and C# closer to the Python/React workflow-intelligence depth: symbol context, process/flow tracing, API/handler impact where applicable, risk-aware change reports, and pre-commit guidance.

Recommended C/C++ roadmap:

1. Build-context discovery.
   - Detect `compile_commands.json`.
   - Parse common CMake build directories.
   - Capture include paths, defines, language standard, compiler flags, and target ownership.
   - Surface build-context confidence in index status and change reports.

2. Source/header pairing and ownership.
   - Link `.h/.hpp` declarations to `.c/.cpp` definitions.
   - Add relations such as `DECLARES`, `DEFINES_IMPLEMENTATION`, `DECLARES_IN_HEADER`, and `INCLUDES_HEADER`.
   - Prefer implementation definitions in caller/callee flows while retaining header context.

3. Semantic call graph hardening.
   - Use clang USRs/canonical names where available.
   - Resolve overloads and namespaces for C++.
   - Track function pointers, callbacks, and virtual dispatch as lower-confidence edges.
   - Mark macro-expanded or unresolved call edges with confidence metadata.

4. Entrypoint and terminal detection.
   - Detect `main`, exported symbols, task/thread entrypoints, callback registrations, CLI handlers, RPC/HTTP handlers, and firmware loops.
   - Detect terminal dependencies such as file I/O, sockets/network, database/client calls, hardware/register access, and external library boundaries.

5. Flow tracing and change reports.
   - Trace from entrypoints through C/C++ call chains.
   - Overlay changed files/symbols onto flows.
   - Add risk factors for high fan-in headers, exported ABI changes, shared structs/enums, macros, and build target ownership.
   - Add test recommendations from nearby test files, target names, and build metadata.

6. C/C++ API/ABI impact.
   - Detect changed exported functions, public headers, structs, enums, typedefs, virtual interfaces, and public macros.
   - Report downstream source files and build targets that include or call changed public surfaces.
   - Add ABI-risk labels for signature/layout changes.

Recommended C# roadmap:

1. ASP.NET route extraction.
   - Detect controllers, minimal APIs, endpoint maps, route attributes, HTTP method attributes, and middleware.
   - Extract route path, method, handler symbol, request type, and response type.

2. DTO and response-shape extraction.
   - Parse records/classes used as request/response DTOs.
   - Track serialized property names, nullable fields, collections, and nested DTOs.
   - Compare route responses with client/consumer reads when C# clients or frontend consumers are indexed.

3. Dependency-injection graph.
   - Parse `AddScoped`, `AddTransient`, `AddSingleton`, factory registrations, and interface-to-implementation mappings.
   - Use DI edges to improve caller/callee and process tracing.

4. Service/repository/process flows.
   - Trace controller/minimal API entrypoints into services, repositories, database clients, queues, and external HTTP clients.
   - Add risk per controller/action/process.

5. Test mapping.
   - Map xUnit/NUnit/MSTest files to controllers, services, DTOs, and repositories.
   - Recommend tests by project, namespace, class name, route, and changed symbol.

6. Risk model.
   - Escalate risk for public controller/DTO changes, auth/middleware changes, shared interface changes, migrations, DI rewires, and high fan-in services.
   - Report risk by route, service, project, and test coverage confidence.

Likely files to update:

- `indexing/parsers/c_family.py`
- `indexing/clang_extractor.py`
- `indexing/parsers/csharp.py`
- `indexing/scanner.py`
- `indexing/graph_builder.py`
- `storage/kuzu_store.py`
- `services/process_service.py`
- `services/detect_changes_service.py`
- `services/change_report_service.py`
- `services/impact_service.py`
- `services/symbol_context_service.py`
- `services/test_intelligence_service.py`
- C/C++ and C# fixture tests under `tests/`

Success criteria:

- A changed public C/C++ header can report downstream source files, build targets, impacted entrypoint flows, and suggested tests.
- A changed C/C++ implementation function can report callers, callees, terminal dependencies, flow membership, and risk.
- A changed ASP.NET route/controller can report route, request/response DTOs, service/repository process flow, consumers, risk, and tests.
- A C# service/interface/DI change can report affected controllers/processes and likely tests.

## Recommended Next Milestones

### Milestone A: Add Field Access Graph Edges

Goal:

- Track where symbols read/write fields or response properties.

Suggested implementation:

1. Extend parser metadata to emit field/property reads and writes.
2. Extend graph builder to create `ACCESSES` edges.
3. Extend Kuzu schema to include `ACCESSES`.
4. Extend `graph_service` categorized context to include `ACCESSES`.
5. Extend `impact_service` to optionally include field access impact.
6. Add tests.

### Milestone B: Add Inheritance / Interface Graph Edges

Goal:

- Understand object-oriented impact for class, interface, and override changes.

Suggested implementation:

1. Extend parser metadata for class inheritance and interface implementation.
2. Add graph relations: `EXTENDS`, `IMPLEMENTS`, `METHOD_OVERRIDES`, `METHOD_IMPLEMENTS`.
3. Update graph context and impact analysis.
4. Add tests with small Python/TypeScript fixtures.

### Milestone C: Harden API Shape Analysis

Goal:

- Reduce false negatives in route response and consumer shape checking.

Suggested implementation:

1. Improve destructured frontend reads.
2. Improve aliased API imports.
3. Improve response variables and helper-return extraction.
4. Add Pydantic model shape extraction.
5. Add real-world fixture tests.

### Milestone D: Process-Aware API Impact

Goal:

- Make API impact report include route-to-service execution flow.

Suggested implementation:

1. Link route handlers to process traces.
2. Add process summaries to `api_impact`.
3. Add process risk to route risk.
4. Add compact summary fields for top affected flows.

## Backward Compatibility Notes

Maintain these existing fields because MCP clients may depend on them:

- `callers`
- `callees`
- `compact_summary`
- `risk`
- `confidence`
- `changed_files`
- `changed_symbols`
- `impacted_files`
- `impacted_symbols`
- `routes`
- `handlers`
- `consumers`

Prefer adding new fields over replacing existing ones.

## Known Design Constraints

- Much of the current route and consumer parsing is regex-based.
- Existing graph schema is intentionally simple.
- Some higher-level services expect plain dictionaries and compact summaries.
- MCP tools should remain stable and avoid breaking existing clients.
- Windows path handling matters for this repo.

## Suggested Developer Workflow

1. Start with a small focused milestone.
2. Add tests before or alongside implementation.
3. Keep output fields backward-compatible.
4. Run the focused validation command.
5. Run the full test suite before finalizing.
6. Update this document if the roadmap changes.

## Current Handoff Summary

Completed:

- Phase 1 git-aware risk metadata.
- Phase 2 API/route/consumer impact.
- Shape checking and `shape_check` MCP tool.
- Route/process integration in git-aware reports.
- Route parsing refactor.
- Categorized graph context.
- MCP wiring for graph-enriched symbol context.

Still left:

- Richer graph schema beyond the first-pass relation set.
- AST-based frontend parsing.
- Stronger backend response shape extraction from helper-built payloads.
- More precise process modeling and process catalog quality.
- Impact analysis over new graph relations.
- README/MCP output documentation.
- More MCP smoke tests around live tool latency and partial-output behavior.
