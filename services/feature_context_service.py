from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from services.app_context_service import app_context
from services.symbol_resolution_service import resolve_candidates

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


FEATURE_HINTS = {
    "routes": ("route", "router", "api", "endpoint"),
    "repositories": ("repository", "repositories", "database", "db", "store"),
    "frontend": ("frontend", "component", "page", "view", "screen", "tsx", "jsx"),
    "tests": ("test", "tests", "spec"),
    "processes": ("process", "workflow", "pipeline", "job"),
}


def _classify_feature_file(file_path: str) -> list[str]:
    normalized = file_path.replace("\\", "/").lower()
    tags = []
    for tag, hints in FEATURE_HINTS.items():
        if any(hint in normalized for hint in hints):
            tags.append(tag)
    if not tags:
        tags.append("supporting_code")
    return tags


def _merge_file_paths(*groups: list[str], limit: int = 24) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for file_path in group:
            normalized = str(file_path or "").replace("\\", "/").strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
            if len(merged) >= limit:
                return merged
    return merged


def _symbol_feature_files(duckdb_store: DuckDBStore, feature: str, limit: int) -> list[str]:
    files = []
    for item in resolve_candidates(duckdb_store, target=feature, limit=max(limit * 2, 12)):
        symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
        file_path = str(symbol.get("file_path", "") or "")
        if file_path:
            files.append(file_path)
    return files


def _chunk_feature_files(duckdb_store: DuckDBStore, feature: str, limit: int) -> list[str]:
    return [
        str(chunk.get("file_path", ""))
        for chunk in duckdb_store.chunks.fetch_for_target(feature, limit=max(limit * 2, 12))
        if chunk.get("file_path")
    ]


def _process_feature_files(duckdb_store: DuckDBStore, feature: str, limit: int) -> tuple[list[str], list[dict[str, object]]]:
    processes = duckdb_store.processes.fetch_clusters(limit=max(limit, 12), query=feature)
    files: list[str] = []
    inflated = []
    for process in processes:
        raw_paths = str(process.get("file_paths_json", "[]") or "[]")
        try:
            process_paths = json.loads(raw_paths)
        except Exception:
            process_paths = []
        path_list = [str(path) for path in process_paths if str(path or "").strip()]
        files.extend(path_list[:6])
        inflated.append(
            {
                "cluster_id": process.get("cluster_id", ""),
                "name": process.get("name", ""),
                "process_type": process.get("process_type", ""),
                "process_count": process.get("process_count", 0),
                "file_paths": path_list[:8],
            }
        )
    return files, inflated[:limit]


def feature_context(repo_root: Path, duckdb_store: DuckDBStore, kuzu_store: KuzuStore, feature: str, limit: int = 12) -> dict[str, object]:
    app = app_context(repo_root, duckdb_store, kuzu_store, target=feature, limit=limit)
    files = app.get("files", []) if isinstance(app, dict) else []
    app_file_paths = [str(item.get("file_path", "")) for item in files if isinstance(item, dict) and item.get("file_path")]
    symbol_file_paths = _symbol_feature_files(duckdb_store, feature, limit)
    chunk_file_paths = _chunk_feature_files(duckdb_store, feature, limit)
    process_file_paths, process_fallbacks = _process_feature_files(duckdb_store, feature, limit)
    fallback_paths = _merge_file_paths(app_file_paths, symbol_file_paths, chunk_file_paths, process_file_paths, limit=limit)
    existing_paths = set(app_file_paths)
    fallback_nodes = []
    for file_path in fallback_paths:
        if file_path in existing_paths:
            continue
        fallback_nodes.append(
            {
                "file_path": file_path,
                "kind": "feature_match",
                "symbols": [
                    {
                        "name": row.get("name", ""),
                        "qualified_name": row.get("qualified_name", ""),
                        "kind": row.get("kind", ""),
                        "start_line": row.get("start_line"),
                        "end_line": row.get("end_line"),
                    }
                    for row in duckdb_store.fetch_symbols_for_file(file_path)[:6]
                ],
                "db_tables": [],
                "match_sources": [
                    source
                    for source, paths in (
                        ("app_context", app_file_paths),
                        ("symbol", symbol_file_paths),
                        ("chunk", chunk_file_paths),
                        ("process", process_file_paths),
                    )
                    if file_path in paths
                ],
            }
        )
    files = [*(files if isinstance(files, list) else []), *fallback_nodes]
    feature_files = []
    tag_counts: dict[str, int] = {}
    for item in files if isinstance(files, list) else []:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file_path", ""))
        tags = _classify_feature_file(file_path)
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        feature_files.append({**item, "feature_tags": tags})
    app_processes = app.get("processes", []) if isinstance(app, dict) else []
    processes = app_processes if app_processes else process_fallbacks
    graph_edges = app.get("graph_edges", []) if isinstance(app, dict) else []
    tool_hints = [
        {"tool": "investigate_codebase", "question": feature, "why": "Get a synthesized answer with evidence."},
        {"tool": "semantic_code_search", "task": feature, "why": "Broaden retrieval if feature_context is sparse."},
    ]
    if feature_files:
        tool_hints.append({"tool": "get_source_context", "target": feature_files[0].get("file_path", feature), "why": "Inspect the highest-ranked feature file."})
    return {
        "target": feature,
        "feature": feature,
        "files": feature_files,
        "routes": app.get("routes", []) if isinstance(app, dict) else [],
        "db_tables": app.get("db_tables", []) if isinstance(app, dict) else [],
        "processes": processes,
        "graph_edges": graph_edges,
        "next_tools": tool_hints,
        "compact_summary": {
            "target": feature,
            "file_count": len(feature_files),
            "file_kinds": tag_counts,
            "top_files": [item.get("file_path", "") for item in feature_files[:8]],
            "top_routes": app.get("compact_summary", {}).get("top_routes", []) if isinstance(app, dict) else [],
            "top_processes": [item.get("name", "") for item in processes[:6]] if isinstance(processes, list) else [],
            "db_tables": app.get("db_tables", [])[:12] if isinstance(app, dict) and isinstance(app.get("db_tables"), list) else [],
            "graph_edge_count": len(graph_edges) if isinstance(graph_edges, list) else 0,
            "match_sources": {
                "app_context": len(app_file_paths),
                "symbol": len(symbol_file_paths),
                "chunk": len(chunk_file_paths),
                "process": len(process_file_paths),
            },
        },
    }
