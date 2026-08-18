<!-- coder:start -->
# coder MCP - Primary Code Intelligence

This project uses coder MCP as the primary code-intelligence layer for codebase discovery, symbol lookup, dependency tracing, impact review, test discovery, and implementation context.

> Prefer coder MCP for this repository. Use other code-intelligence tools only as optional fallbacks or secondary cross-checks when coder MCP cannot answer a question clearly.

## Always Do

- Use coder MCP first when you need to locate files, symbols, routes, tests, dependencies, execution context, or likely implementation areas.
- Use `coder_semantic_code_search` or `coder_investigate_codebase` when exploring unfamiliar features or trying to find the authoritative implementation.
- Use `coder_resolve_target` and `coder_unified_context` when you need focused symbol-level context (callers, callees, deps, neighborhood in one call).
- Before modifying a function, class, method, route handler, shared module, public header, API contract, or embedded firmware boundary, use coder MCP to inspect symbol context, callers/callees, dependencies, or change impact as appropriate.
- Use `coder_find_tests_for_target` before or after implementation to identify relevant tests.
- Use `coder_detect_changes`, `coder_change_impact_report`, or `coder_post_change_review` to review changed files, likely affected behavior, and test scope when preparing a commit or handoff.
- For C/C++/embedded projects, use `coder_get_dependencies`, `coder_unified_context`, and `coder_detect_changes` to inspect header fan-in, call relationships, project/build files, startup/ISR/trap files, and peripheral/init/flash modules.
- If coder MCP reports stale, incomplete, or low-confidence results, use normal file search/read tools or another code-intelligence system as a fallback.

## Never Do

- NEVER skip reviewing callers, dependencies, or likely test scope for changes to shared or high-risk code.
- NEVER commit or hand off changes without reviewing local change scope using coder MCP or equivalent git diff inspection.
- NEVER ignore low-confidence C/C++ results when compiler/build context is missing. Treat them as useful guidance, then verify with source and build knowledge.

## Preferred Usage

| Task | Preferred coder MCP tool |
|------|--------------------------|
| Find where a feature is implemented | `coder_semantic_code_search` or `coder_investigate_codebase` |
| Find a symbol by name | `coder_resolve_target` or `coder_find_symbols` |
| Understand one symbol (callers, callees, deps) | `coder_unified_context` |
| See callers/callees only | `coder_get_callers_and_callees` |
| Find dependencies | `coder_get_dependencies` |
| Find relevant tests | `coder_find_tests_for_target` |
| Review local change scope | `coder_detect_changes` or `coder_change_impact_report` |
| Full post-change review (changes + impact + tests) | `coder_post_change_review` |
| Inspect API/route blast radius | `coder_api_impact`, `coder_route_map`, or `coder_shape_check` |
| Inspect C/C++ header or embedded blast radius | `coder_get_dependencies`, `coder_unified_context`, or `coder_detect_changes` |
| Trace execution flows | `coder_trace_processes` |
| Trace data/field propagation | `coder_trace_data_flow` |
| Find how A and B are connected | `coder_shortest_path` |
| Detect architecture clusters | `coder_detect_communities` |
| Parse a stack trace | `coder_explain_error` |

<!-- coder:end -->
