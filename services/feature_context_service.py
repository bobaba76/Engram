from __future__ import annotations

import json
from pathlib import Path
import re
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
FEATURE_STOPWORDS = {"the", "and", "for", "with", "from", "into", "across", "code", "path", "flow", "trace", "find"}
PAGE_HINTS = ("page", "pages", "screen", "screens", "landing", "overview", "dashboard", "route", "router")
SHARED_UI_HINTS = ("component", "components", "selector", "filter", "context", "contexts", "hook", "hooks", "period", "date")
BACKEND_HINTS = ("api", "endpoint", "endpoints", "controller", "controllers", "service", "services", "backend")


def _classify_feature_file(file_path: str) -> list[str]:
    normalized = file_path.replace("\\", "/").lower()
    tags = []
    for tag, hints in FEATURE_HINTS.items():
        if any(hint in normalized for hint in hints):
            tags.append(tag)
    if not tags:
        tags.append("supporting_code")
    return tags


def _feature_file_roles(file_path: str) -> list[str]:
    normalized = file_path.replace("\\", "/").lower()
    roles: list[str] = []
    if any(hint in normalized for hint in PAGE_HINTS):
        roles.append("page")
    if any(hint in normalized for hint in SHARED_UI_HINTS):
        roles.append("shared_ui")
    if any(hint in normalized for hint in BACKEND_HINTS):
        roles.append("backend")
    if not roles:
        roles.append("supporting")
    return roles


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


def _feature_query_terms(feature: str, limit: int = 5) -> list[str]:
    normalized = " ".join(str(feature or "").split()).strip()
    if not normalized:
        return []
    terms: list[str] = [normalized]
    tokens = [
        token
        for token in re.split(r"[^a-zA-Z0-9]+", normalized.lower())
        if token and token not in FEATURE_STOPWORDS and len(token) >= 3
    ]
    for size in (3, 2):
        for index in range(0, max(0, len(tokens) - size + 1)):
            phrase = " ".join(tokens[index : index + size])
            if phrase and phrase not in terms:
                terms.append(phrase)
            if len(terms) >= limit:
                return terms[:limit]
    for token in tokens:
        if token not in terms:
            terms.append(token)
        if len(terms) >= limit:
            return terms[:limit]
    return terms[:limit]


def _symbol_feature_files(duckdb_store: DuckDBStore, feature: str, limit: int) -> list[str]:
    files = []
    seen: set[str] = set()
    for term in _feature_query_terms(feature, limit=4):
        for item in resolve_candidates(duckdb_store, target=term, limit=max(limit * 2, 12)):
            symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
            file_path = str(symbol.get("file_path", "") or "")
            if file_path and file_path not in seen:
                seen.add(file_path)
                files.append(file_path)
            if len(files) >= max(limit * 2, 12):
                return files
    return files


def _chunk_feature_files(duckdb_store: DuckDBStore, feature: str, limit: int) -> list[str]:
    ranked_files: list[str] = []
    scores: dict[str, int] = {}
    fetch_for_target = getattr(duckdb_store.chunks, "fetch_for_target", None)
    search_chunks_content = getattr(duckdb_store, "search_chunks_content", None)
    for index, term in enumerate(_feature_query_terms(feature, limit=5)):
        rows = []
        if callable(fetch_for_target):
            try:
                rows.extend(fetch_for_target(term, limit=max(limit * 2, 12)))
            except Exception:
                pass
        if callable(search_chunks_content):
            try:
                rows.extend(search_chunks_content(term, limit=max(limit * 2, 12)))
            except Exception:
                pass
        for row in rows:
            file_path = str(row.get("file_path", "") or "")
            if not file_path:
                continue
            scores[file_path] = scores.get(file_path, 0) + max(1, 6 - index)
    for file_path, _ in sorted(scores.items(), key=lambda item: (item[1], item[0]), reverse=True)[:limit]:
        ranked_files.append(file_path)
    return ranked_files


def _process_feature_files(duckdb_store: DuckDBStore, feature: str, limit: int) -> tuple[list[str], list[dict[str, object]]]:
    process_map: dict[str, dict[str, object]] = {}
    ordered_ids: list[str] = []
    for index, term in enumerate(_feature_query_terms(feature, limit=4)):
        processes = duckdb_store.processes.fetch_clusters(limit=max(limit, 12), query=term)
        for process in processes:
            cluster_id = str(process.get("cluster_id", "") or f"process-{len(ordered_ids)}")
            if cluster_id not in process_map:
                process_map[cluster_id] = {**process, "_score": 0}
                ordered_ids.append(cluster_id)
            process_map[cluster_id]["_score"] = int(process_map[cluster_id].get("_score", 0) or 0) + max(1, 5 - index)
    files: list[str] = []
    inflated = []
    ranked_processes = sorted(
        (process_map[cluster_id] for cluster_id in ordered_ids),
        key=lambda item: (int(item.get("_score", 0) or 0), int(item.get("process_count", 0) or 0)),
        reverse=True,
    )[:limit]
    for process in ranked_processes:
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


def feature_context(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    feature: str,
    limit: int = 12,
    lightweight: bool = False,
) -> dict[str, object]:
    app = {"files": [], "routes": [], "db_tables": [], "processes": [], "graph_edges": [], "compact_summary": {}, "guardrail": {"lightweight": True}} if lightweight else app_context(repo_root, duckdb_store, kuzu_store, target=feature, limit=limit)
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
    role_groups = {"page_files": [], "shared_ui_files": [], "backend_files": []}

    def add_role_file(role: str, file_path: str, role_limit: int = 6) -> None:
        if role not in role_groups:
            return
        normalized = str(file_path or "").strip()
        if normalized and normalized not in role_groups[role] and len(role_groups[role]) < role_limit:
            role_groups[role].append(normalized)

    for item in files if isinstance(files, list) else []:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file_path", ""))
        tags = _classify_feature_file(file_path)
        roles = _feature_file_roles(file_path)
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        for role in roles:
            if role == "page":
                add_role_file("page_files", file_path)
            elif role == "shared_ui":
                add_role_file("shared_ui_files", file_path)
            elif role == "backend":
                add_role_file("backend_files", file_path)
        feature_files.append({**item, "feature_tags": tags, "feature_roles": roles})
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
        "partial": bool(lightweight),
        "files": feature_files,
        "routes": app.get("routes", []) if isinstance(app, dict) else [],
        "db_tables": app.get("db_tables", []) if isinstance(app, dict) else [],
        "processes": processes,
        "graph_edges": graph_edges,
        "role_groups": role_groups,
        "guardrail": {
            "lightweight": bool(lightweight),
            "app_context_skipped": bool(lightweight),
        },
        "next_tools": tool_hints,
        "compact_summary": {
            "target": feature,
            "partial": bool(lightweight),
            "file_count": len(feature_files),
            "file_kinds": tag_counts,
            "top_files": [item.get("file_path", "") for item in feature_files[:8]],
            "role_groups": role_groups,
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
