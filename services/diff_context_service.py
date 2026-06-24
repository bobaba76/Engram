"""Diff-aware context builder.

Given a set of changed files (from git diff or explicit list), returns the minimal
context an LLM needs to review them: changed symbols, their source snippets, callers,
and dependent files. This is the "review pack" — everything needed to understand a
change without reading the entire codebase.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.graph_edge_utils import edges_for_target_limited, edges_for_source_limited
from services.source_retrieval_service import _direct_file_snippet
from services.symbol_resolution_service import resolve_candidates

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _file_symbols(duckdb_store: DuckDBStore, file_path: str) -> list[dict[str, object]]:
    rows = duckdb_store.fetch_symbols_for_file(file_path)
    return [
        {
            "name": row.get("name", ""),
            "qualified_name": row.get("qualified_name", ""),
            "kind": row.get("kind", ""),
            "start_line": row.get("start_line"),
            "end_line": row.get("end_line"),
            "signature": row.get("signature", ""),
        }
        for row in rows
    ]


def _symbol_snippet(repo_root: Path, symbol: dict[str, object], context_lines: int = 3) -> dict[str, object] | None:
    return _direct_file_snippet(repo_root, symbol, context_lines=context_lines)


def _callers_for_symbol(kuzu_store: KuzuStore, qualified_name: str, limit: int = 5) -> list[str]:
    edges = edges_for_target_limited(kuzu_store, qualified_name, relation="CALLS", limit=limit)
    return [str(edge.get("source", "")) for edge in edges if str(edge.get("source", ""))]


def _callees_for_symbol(kuzu_store: KuzuStore, qualified_name: str, limit: int = 5) -> list[str]:
    edges = edges_for_source_limited(kuzu_store, qualified_name, relation="CALLS", limit=limit)
    return [str(edge.get("target", "")) for edge in edges if str(edge.get("target", ""))]


def diff_context(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    changed_files: list[str] | None = None,
    scope: str = "unstaged",
    base_ref: str = "",
    max_snippets: int = 20,
) -> dict[str, object]:
    from services.detect_changes_service import detect_changes

    if changed_files is None:
        changes = detect_changes(
            repo_root, duckdb_store, kuzu_store,
            scope=scope, base_ref=base_ref or None,
        )
        changed_files = [
            str(f.get("file_path", "") or f.get("path", ""))
            for f in changes.get("changed_files", [])
            if isinstance(f, dict)
        ]
        changed_files = [f for f in changed_files if f]

    if not changed_files:
        return {
            "status": "no_changes",
            "changed_files": [],
            "context": [],
            "compact_summary": {"status": "no_changes", "changed_files": []},
            "summary_text": "No changed files detected.",
        }

    file_contexts: list[dict[str, object]] = []
    total_snippets = 0
    all_callers: set[str] = set()
    all_callees: set[str] = set()

    for file_path in changed_files[:50]:
        normalized = file_path.replace("\\", "/")
        symbols = _file_symbols(duckdb_store, normalized)

        symbol_contexts: list[dict[str, object]] = []
        for symbol in symbols:
            if total_snippets >= max_snippets:
                break

            qn = str(symbol.get("qualified_name", "") or "").strip()
            snippet = _symbol_snippet(repo_root, symbol)
            callers = _callers_for_symbol(kuzu_store, qn) if qn else []
            callees = _callees_for_symbol(kuzu_store, qn) if qn else []

            all_callers.update(callers)
            all_callees.update(callees)

            symbol_contexts.append({
                "name": symbol.get("name", ""),
                "qualified_name": qn,
                "kind": symbol.get("kind", ""),
                "start_line": symbol.get("start_line"),
                "end_line": symbol.get("end_line"),
                "signature": symbol.get("signature", ""),
                "source_snippet": snippet,
                "callers": callers,
                "callees": callees,
            })
            total_snippets += 1

        file_contexts.append({
            "file_path": normalized,
            "symbol_count": len(symbols),
            "symbols": symbol_contexts,
        })

    impacted_files = set()
    for caller in all_callers:
        rows = duckdb_store.fetch_symbols_for_target(caller, limit=1)
        if rows:
            fp = str(rows[0].get("file_path", "") or "")
            if fp and fp not in changed_files:
                impacted_files.add(fp)

    return {
        "status": "ok",
        "changed_files": [f.replace("\\", "/") for f in changed_files],
        "file_count": len(changed_files),
        "context": file_contexts,
        "impacted_files": sorted(impacted_files)[:20],
        "total_symbols": sum(fc.get("symbol_count", 0) for fc in file_contexts),
        "total_snippets": total_snippets,
        "compact_summary": {
            "status": "ok",
            "file_count": len(changed_files),
            "total_symbols": sum(fc.get("symbol_count", 0) for fc in file_contexts),
            "impacted_file_count": len(impacted_files),
            "top_changed_files": [f.replace("\\", "/") for f in changed_files[:5]],
            "top_impacted_files": sorted(impacted_files)[:5],
        },
        "summary_text": f"{len(changed_files)} changed files, {sum(fc.get('symbol_count', 0) for fc in file_contexts)} symbols, {len(impacted_files)} impacted files.",
    }
