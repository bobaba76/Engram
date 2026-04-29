from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.app_context_service import app_context
from services.detect_changes_service import detect_changes
from services.impact_service import analyze_impact
from services.test_intelligence_service import suggest_tests_for_change

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


def _merge_frontend_graph_signals(symbol_reports: list[dict[str, object]], app_payloads: list[dict[str, object]]) -> dict[str, object]:
    frontend_files: list[str] = []
    relation_counts: dict[str, int] = {}
    has_indirect = False
    summaries: list[str] = []
    for report in symbol_reports:
        if not isinstance(report, dict):
            continue
        graph = report.get("frontend_graph") or report.get("compact_summary", {}).get("frontend_graph", {})
        if not isinstance(graph, dict):
            continue
        for file_path in graph.get("top_frontend_files", []) if isinstance(graph.get("top_frontend_files", []), list) else []:
            normalized = str(file_path or "").strip()
            if normalized and normalized not in frontend_files:
                frontend_files.append(normalized)
        for relation, count in graph.get("top_relations", {}).items() if isinstance(graph.get("top_relations", {}), dict) else []:
            relation_counts[str(relation)] = relation_counts.get(str(relation), 0) + int(count or 0)
        if bool(graph.get("has_indirect_frontend_path")):
            has_indirect = True
        summary = str(graph.get("summary") or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)
    for payload in app_payloads:
        if not isinstance(payload, dict):
            continue
        graph = payload.get("frontend_graph") or payload.get("compact_summary", {}).get("frontend_graph", {})
        if not isinstance(graph, dict):
            continue
        for file_path in graph.get("top_frontend_files", []) if isinstance(graph.get("top_frontend_files", []), list) else []:
            normalized = str(file_path or "").strip()
            if normalized and normalized not in frontend_files:
                frontend_files.append(normalized)
        for relation, count in graph.get("top_relations", {}).items() if isinstance(graph.get("top_relations", {}), dict) else []:
            relation_counts[str(relation)] = relation_counts.get(str(relation), 0) + int(count or 0)
        if bool(graph.get("has_indirect_frontend_path")):
            has_indirect = True
        summary = str(graph.get("summary") or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)
    merged_summary = summaries[0] if summaries else ""
    return {
        "frontend_file_count": len(frontend_files),
        "top_frontend_files": frontend_files[:6],
        "frontend_graph_edge_count": sum(relation_counts.values()),
        "top_relations": relation_counts,
        "has_indirect_frontend_path": has_indirect,
        "summary": merged_summary,
    }


def change_impact_report(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    scope: str = "unstaged",
    base_ref: str = "",
    max_symbols: int = 5,
) -> dict[str, object]:
    changes = detect_changes(repo_root, duckdb_store, kuzu_store, scope=scope, base_ref=base_ref or None)
    changed_symbols = changes.get("changed_symbols", []) if isinstance(changes, dict) else []
    symbol_reports = []
    for symbol in changed_symbols[:max_symbols] if isinstance(changed_symbols, list) else []:
        if not isinstance(symbol, dict):
            continue
        target = str(symbol.get("qualified_name") or symbol.get("name") or "")
        if not target:
            continue
        symbol_reports.append(analyze_impact(duckdb_store, kuzu_store, target=target, direction="upstream", max_depth=2))
    changed_files = changes.get("changed_files", []) if isinstance(changes, dict) else []
    app_payloads = []
    for file_path in changed_files[:5] if isinstance(changed_files, list) else []:
        app_payloads.append(app_context(repo_root, duckdb_store, kuzu_store, target=str(file_path), limit=5))
    tests = suggest_tests_for_change(repo_root, duckdb_store, kuzu_store, scope=scope, base_ref=base_ref)
    risk = changes.get("risk", "LOW") if isinstance(changes, dict) else "UNKNOWN"
    if any(report.get("risk") == "HIGH" for report in symbol_reports if isinstance(report, dict)):
        risk = "HIGH"
    elif risk == "LOW" and any(report.get("risk") == "MEDIUM" for report in symbol_reports if isinstance(report, dict)):
        risk = "MEDIUM"
    changed_file_count = len(changed_files) if isinstance(changed_files, list) else 0
    frontend_graph = _merge_frontend_graph_signals(symbol_reports, app_payloads)
    return {
        "scope": scope,
        "base_ref": base_ref,
        "risk": risk,
        "changes": changes,
        "symbol_impacts": symbol_reports,
        "app_contexts": app_payloads,
        "frontend_graph": frontend_graph,
        "test_recommendations": tests,
        "what_changed": [
            f"{changed_file_count} files changed.",
            f"{len(changed_symbols) if isinstance(changed_symbols, list) else 0} indexed symbols changed.",
        ],
        "what_to_test": tests.get("compact_summary", {}).get("top_files", []) if isinstance(tests, dict) else [],
        "compact_summary": {
            "target": f"{scope} changes",
            "risk": risk,
            "changed_file_count": changed_file_count,
            "changed_symbol_count": len(changed_symbols) if isinstance(changed_symbols, list) else 0,
            "top_changed_files": changed_files[:8] if isinstance(changed_files, list) else [],
            "top_impacted": [
                report.get("compact_summary", {}).get("target", "")
                for report in symbol_reports[:6]
                if isinstance(report, dict)
            ],
            "top_tests": tests.get("compact_summary", {}).get("top_files", []) if isinstance(tests, dict) else [],
            "frontend_graph": frontend_graph,
        },
    }
