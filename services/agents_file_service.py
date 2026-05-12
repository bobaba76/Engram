from __future__ import annotations

from pathlib import Path


CODER_BLOCK_START = "<!-- coder:start -->"
CODER_BLOCK_END = "<!-- coder:end -->"


AGENTS_MD_TEMPLATE = f"""{CODER_BLOCK_START}
# coder MCP - Primary Code Intelligence

This project uses coder MCP as the primary code-intelligence layer for codebase discovery, symbol lookup, dependency tracing, impact review, test discovery, and implementation context.

> Prefer coder MCP for this repository. Use other code-intelligence tools only as optional fallbacks or secondary cross-checks when coder MCP cannot answer a question clearly.

## Always Do

- Use coder MCP first when you need to locate files, symbols, routes, tests, dependencies, execution context, or likely implementation areas.
- Use `coder_app_context`, `coder_feature_context`, or `coder_semantic_code_search` when exploring unfamiliar features or trying to find the authoritative implementation.
- Use `coder_find_symbols`, `coder_get_symbol_context`, and `coder_get_callers_and_callees` when you need focused symbol-level context.
- Before modifying a function, class, method, route handler, shared module, public header, API contract, or embedded firmware boundary, use coder MCP to inspect symbol context, callers/callees, dependencies, or change impact as appropriate.
- Use `coder_find_tests_for_target` or `coder_suggest_tests_for_change` before or after implementation to identify relevant tests.
- Use `coder_detect_changes`, `coder_change_impact_report`, or `coder_test_impact` to review changed files, likely affected behavior, and test scope when preparing a commit or handoff.
- For C/C++/embedded projects, use `coder_get_dependencies`, `coder_get_symbol_context`, and `coder_detect_changes` to inspect header fan-in, call relationships, project/build files, startup/ISR/trap files, and peripheral/init/flash modules.
- If coder MCP reports stale, incomplete, or low-confidence results, use normal file search/read tools or another code-intelligence system as a fallback.

## Never Do

- NEVER skip reviewing callers, dependencies, or likely test scope for changes to shared or high-risk code.
- NEVER rely on broad text replacement for symbol renames. Use graph-aware rename tooling where available and review all edits carefully.
- NEVER commit or hand off changes without reviewing local change scope using coder MCP or equivalent git diff inspection.
- NEVER ignore low-confidence C/C++ results when compiler/build context is missing. Treat them as useful guidance, then verify with source and build knowledge.

## Preferred Usage

| Task | Preferred coder MCP tool |
|------|--------------------------|
| Find where a feature is implemented | `coder_feature_context` or `coder_semantic_code_search` |
| Find a symbol by name | `coder_find_symbols` |
| Understand one symbol | `coder_get_symbol_context` |
| See callers/callees | `coder_get_callers_and_callees` |
| Find dependencies | `coder_get_dependencies` |
| Find relevant tests | `coder_find_tests_for_target` |
| Review local change scope | `coder_detect_changes` or `coder_change_impact_report` |
| Determine likely tests to run | `coder_test_impact` or `coder_suggest_tests_for_change` |
| Inspect API/route blast radius | `coder_api_impact`, `coder_route_map`, or `coder_shape_check` |
| Inspect C/C++ header or embedded blast radius | `coder_get_dependencies`, `coder_get_symbol_context`, or `coder_detect_changes` |
| Rename a symbol safely | `coder_preview_rename` first, then apply reviewed edits |

{CODER_BLOCK_END}
"""


def _replace_coder_block(existing: str, block: str) -> str:
    start = existing.find(CODER_BLOCK_START)
    end = existing.find(CODER_BLOCK_END)
    if start == -1 or end == -1 or end < start:
        separator = "\n\n" if existing.strip() else ""
        return f"{existing.rstrip()}{separator}{block.rstrip()}\n"
    end += len(CODER_BLOCK_END)
    return f"{existing[:start].rstrip()}\n\n{block.rstrip()}\n\n{existing[end:].lstrip()}".strip() + "\n"


def update_agents_file(repo_root: Path, *, enabled: bool = True) -> dict[str, object]:
    if not enabled:
        return {"enabled": False, "updated": False, "path": str((repo_root / "AGENTS.md").resolve())}
    agents_path = repo_root / "AGENTS.md"
    existing = agents_path.read_text(encoding="utf-8", errors="ignore") if agents_path.exists() else ""
    updated = _replace_coder_block(existing, AGENTS_MD_TEMPLATE)
    if updated != existing:
        agents_path.write_text(updated, encoding="utf-8")
        return {"enabled": True, "updated": True, "path": str(agents_path.resolve())}
    return {"enabled": True, "updated": False, "path": str(agents_path.resolve())}
