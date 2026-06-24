"""Change detection facade — delegates to focused submodules.

Decomposed from the original monolithic module into:
- detect_changes_git: git diff operations and diff text parsing
- detect_changes_risk: risk assessment, scoring, and confidence helpers
- detect_changes_summaries: route and process change summaries

All symbols are re-exported here for backward compatibility with existing
imports and monkeypatch-based tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore
from services.timeout_utils import run_with_timeout

# Re-export everything from submodules for backward compatibility
from services.detect_changes_git import (  # noqa: F401
    HUNK_PATTERN,
    _diff_output,
    _find_git_root,
    _git_top_level,
    _normalize_status_path,
    _parse_changed_lines,
    _run_git,
    _synthetic_untracked_diff,
    _untracked_files,
)
from services.detect_changes_risk import (  # noqa: F401
    _confidence,
    _diff_command_equivalent,
    _file_risk,
    _focused_followups,
    _normalized_scope,
    _overall_risk,
    _path_risk_hints,
    _risk_applies_to,
    _risk_by_file,
    _risk_explanation,
    _risk_scope,
    _symbol_metadata,
    _symbol_risk_hints,
    _symbols_for_changed_lines,
    _weighted_risk,
)
from services.detect_changes_summaries import (  # noqa: F401
    ROUTE_OPERATION_TIMEOUT_SECONDS,
    PROCESS_OPERATION_TIMEOUT_SECONDS,
    _indexed_process_rows,
    _process_change_summary,
    _process_target_priority,
    _route_change_summary,
)
BROAD_GRAPH_FILE_LIMIT = 20
BROAD_PROCESS_SYMBOL_LIMIT = 80
GRAPH_OPERATION_TIMEOUT_SECONDS = 1.5


def detect_changes(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    scope: str = "unstaged",
    base_ref: str | None = None,
    diff_text_override: str | None = None,
    git_warning: str | None = None,
) -> dict[str, object]:
    warnings: list[str] = []
    normalized_scope = _normalized_scope(scope)
    diff_text = diff_text_override if diff_text_override is not None else _diff_output(repo_root, scope=normalized_scope, base_ref=base_ref)
    if git_warning:
        warnings.append(git_warning)
    if diff_text_override is None and not diff_text:
        if not _run_git(repo_root, ["rev-parse", "--git-dir"]):
            discovered = _find_git_root(repo_root)
            if discovered is not None:
                warnings.append(f"Git repo found at {discovered} (nested inside {repo_root}). Using nested git root for diff operations.")
            else:
                warnings.append(f"No git repository found at {repo_root}. detect_changes requires a git repo.")
    changed_lines_by_file = _parse_changed_lines(diff_text)
    changed_files = sorted(changed_lines_by_file)
    changed_symbols: list[dict[str, object]] = []
    for file_path in changed_files:
        changed_symbols.extend(_symbols_for_changed_lines(duckdb_store, file_path, changed_lines_by_file[file_path]))
    if len(changed_files) > BROAD_GRAPH_FILE_LIMIT:
        impacted_files = []
        warnings.append(
            f"Graph blast-radius traversal skipped for {len(changed_files)} changed files; narrow the scope or target a file/symbol for full graph impact."
        )
    else:
        impacted_files = sorted(run_with_timeout(
            lambda: kuzu_store.get_impacted_files(changed_files),
            timeout_seconds=GRAPH_OPERATION_TIMEOUT_SECONDS,
            default=set(),
            warnings=warnings,
            label="Graph blast-radius traversal",
        )) if changed_files else []
    impacted_symbols: list[dict[str, object]] = []
    seen_symbols: set[tuple[str, str]] = set()
    for file_path in impacted_files[:25]:
        for symbol in duckdb_store.fetch_symbols_for_file(file_path)[:10]:
            key = (file_path, str(symbol.get("qualified_name", "")))
            if key in seen_symbols:
                continue
            seen_symbols.add(key)
            impacted_symbols.append(
                {
                    "qualified_name": symbol.get("qualified_name", ""),
                    "name": symbol.get("name", ""),
                    "kind": symbol.get("kind", ""),
                    "file_path": file_path,
                }
            )
    file_risks = _risk_by_file(changed_files, changed_symbols, impacted_files)
    route_summary = _route_change_summary(repo_root, duckdb_store, changed_files, changed_symbols, kuzu_store=kuzu_store)
    if len(changed_symbols) > BROAD_PROCESS_SYMBOL_LIMIT or len(changed_files) > BROAD_GRAPH_FILE_LIMIT:
        process_summary = {"affected_processes": [], "risk_by_process": []}
        if changed_symbols:
            warnings.append(
                f"Process tracing skipped for broad diff ({len(changed_symbols)} changed symbols); use trace_processes on a focused target for full flows."
            )
    else:
        process_summary = _process_change_summary(duckdb_store, kuzu_store, changed_symbols, route_summary.get("changed_routes", []), warnings)
    risk = _overall_risk(changed_files, changed_symbols, impacted_files, file_risks)
    if route_summary.get("shape_mismatches") and risk != "CRITICAL":
        risk = "HIGH"
    elif any(item.get("risk") == "HIGH" for item in route_summary.get("risk_by_route", []) if isinstance(item, dict)) and risk == "LOW":
        risk = "MEDIUM"
    if any(item.get("risk") == "HIGH" for item in process_summary.get("risk_by_process", []) if isinstance(item, dict)) and risk not in {"HIGH", "CRITICAL"}:
        risk = "HIGH"
    weighted_risk = _weighted_risk(changed_files, changed_symbols, impacted_files, file_risks, route_summary, process_summary)
    risk_scope = _risk_scope(normalized_scope)
    risk_explanation = _risk_explanation(changed_files, changed_symbols, impacted_files, file_risks)
    if route_summary.get("changed_routes"):
        risk_explanation.append(f"{len(route_summary.get('changed_routes', []))} API routes touched by changed files")
    if route_summary.get("shape_mismatches"):
        risk_explanation.append(f"{len(route_summary.get('shape_mismatches', []))} route shape mismatches detected")
    if process_summary.get("affected_processes"):
        risk_explanation.append(f"{len(process_summary.get('affected_processes', []))} execution flows include changed symbols")
    git_metadata = {
        "repo_root": str(repo_root.resolve()),
        "scope": normalized_scope,
        "base_ref": base_ref or None,
        "diff_command_equivalent": _diff_command_equivalent(normalized_scope, base_ref),
        "changed_files_count": len(changed_files),
    }
    confidence = _confidence(changed_files, changed_symbols, impacted_files, warnings)
    follow_up_tools = _focused_followups(file_risks, changed_symbols, warnings)
    return {
        "repo_root": str(repo_root.resolve()),
        "scope": normalized_scope,
        "base_ref": base_ref or "",
        "git": git_metadata,
        "risk_scope": risk_scope,
        "risk_applies_to": _risk_applies_to(normalized_scope, base_ref),
        "not_limited_to_recent_edits": normalized_scope in {"unstaged", "staged", "all"},
        "risk_explanation": risk_explanation,
        "risk_score": weighted_risk["score"],
        "risk_score_label": weighted_risk["label"],
        "weighted_risk_factors": weighted_risk["factors"],
        "risk_by_file": file_risks,
        "changed_routes": route_summary.get("changed_routes", []),
        "affected_consumers": route_summary.get("affected_consumers", []),
        "changed_response_shapes": route_summary.get("changed_response_shapes", []),
        "risk_by_route": route_summary.get("risk_by_route", []),
        "shape_mismatches": route_summary.get("shape_mismatches", []),
        "affected_processes": process_summary.get("affected_processes", []),
        "risk_by_process": process_summary.get("risk_by_process", []),
        "changed_files": changed_files,
        "changed_symbols": changed_symbols,
        "impacted_files": impacted_files,
        "impacted_symbols": impacted_symbols,
        "risk": risk,
        "confidence": confidence["level"],
        "confidence_explanation": confidence["why"],
        "warnings": warnings,
        "follow_up_tools": follow_up_tools,
        "compact_summary": {
            "target": str(repo_root.resolve()),
            "scope": normalized_scope,
            "risk_scope": risk_scope,
            "changed_file_count": len(changed_files),
            "changed_symbol_count": len(changed_symbols),
            "impacted_file_count": len(impacted_files),
            "risk": risk,
            "risk_score": weighted_risk["score"],
            "risk_score_label": weighted_risk["label"],
            "weighted_risk_factors": weighted_risk["factors"][:6],
            "confidence": confidence["level"],
            "risk_explanation": risk_explanation[:6],
            "top_risk_files": [row.get("file", "") for row in file_risks if row.get("risk") in {"CRITICAL", "HIGH"}][:8],
            "changed_routes": route_summary.get("changed_routes", [])[:8],
            "shape_mismatches": [item.get("route", "") for item in route_summary.get("shape_mismatches", [])][:8],
            "affected_processes": [item.get("name", "") for item in process_summary.get("affected_processes", [])][:8],
            "top_changed_files": changed_files[:8],
            "top_changed_symbols": [item.get("qualified_name") or item.get("name") for item in changed_symbols[:8]],
            "top_impacted_files": impacted_files[:8],
            "follow_up_tools": follow_up_tools,
        },
    }


def __getattr__(name: str):
    if name == "trace_execution_flows":
        from services.process_service import trace_execution_flows

        return trace_execution_flows
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
