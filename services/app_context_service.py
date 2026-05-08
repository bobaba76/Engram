from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

from services.api_impact_service import api_impact
from services.route_map_service import route_map

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


TABLE_PATTERN = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO|TABLE|REFERENCES)\s+[`\"]?(?P<table>[A-Za-z_][A-Za-z0-9_\.]*)[`\"]?",
    re.IGNORECASE,
)
COMPONENT_FILE_HINTS = ("/components/", "/pages/", "/views/", "/screens/")
REPOSITORY_FILE_HINTS = ("/repositories/", "/repository/", "/models/", "/database", "/db_")
ENDPOINT_FILE_HINTS = ("/routers/", "/routes/", "/api/")


def _target_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^A-Za-z0-9_./:-]+", str(value or "").strip()) if token]


def _target_shape(target: str) -> dict[str, object]:
    normalized = str(target or "").strip()
    lowered = normalized.lower()
    is_route = normalized.startswith("/") or "/api/" in lowered
    is_file_like = "/" in normalized or lowered.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))
    is_symbol_like = "." in normalized or "::" in normalized or ":" in normalized
    tokens = _target_tokens(normalized)
    is_broad = bool(normalized) and not is_route and not is_file_like and not is_symbol_like and len(tokens) <= 2
    return {
        "normalized": normalized,
        "is_route": is_route,
        "is_file_like": is_file_like,
        "is_symbol_like": is_symbol_like,
        "is_broad": is_broad,
        "tokens": tokens,
    }


def _file_kind(file_path: str) -> str:
    normalized_path = file_path.replace("\\", "/")
    normalized = f"/{normalized_path}".lower()
    if normalized.endswith((".tsx", ".jsx")) and any(hint in normalized for hint in COMPONENT_FILE_HINTS):
        return "frontend_component"
    if normalized.endswith(".py") and any(hint in normalized for hint in ENDPOINT_FILE_HINTS):
        return "backend_endpoint"
    if normalized.endswith(".py") and any(hint in normalized for hint in REPOSITORY_FILE_HINTS):
        return "repository"
    if normalized.endswith((".ts", ".tsx", ".js", ".jsx")):
        return "frontend"
    if normalized.endswith(".py"):
        return "backend"
    return "other"


def _symbols_for_file(duckdb_store: DuckDBStore, file_path: str, limit: int = 8) -> list[dict[str, object]]:
    return [
        {
            "name": row.get("name", ""),
            "qualified_name": row.get("qualified_name", ""),
            "kind": row.get("kind", ""),
            "start_line": row.get("start_line"),
            "end_line": row.get("end_line"),
        }
        for row in duckdb_store.fetch_symbols_for_file(file_path)[:limit]
    ]


def _tables_for_file(repo_root: Path, file_path: str) -> list[str]:
    try:
        source = (repo_root / file_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    tables = {
        match.group("table").strip(".")
        for match in TABLE_PATTERN.finditer(source)
        if match.group("table")
    }
    return sorted(tables)[:20]


def _inflate_file_node(repo_root: Path, duckdb_store: DuckDBStore, file_path: str) -> dict[str, object]:
    return {
        "file_path": file_path,
        "kind": _file_kind(file_path),
        "symbols": _symbols_for_file(duckdb_store, file_path),
        "db_tables": _tables_for_file(repo_root, file_path),
    }


def _is_frontend_kind(kind: str) -> bool:
    normalized = str(kind or "").strip().lower()
    return normalized in {"frontend", "frontend_component"}


def _frontend_graph_summary(file_nodes: list[dict[str, object]], graph_edges: list[dict[str, object]]) -> dict[str, object]:
    frontend_files = [
        str(node.get("file_path", "") or "").strip()
        for node in file_nodes
        if _is_frontend_kind(str(node.get("kind", "") or "")) and str(node.get("file_path", "") or "").strip()
    ]
    frontend_symbols = {
        str(symbol.get("qualified_name", "") or "").strip()
        for node in file_nodes
        if _is_frontend_kind(str(node.get("kind", "") or ""))
        for symbol in node.get("symbols", [])
        if isinstance(symbol, dict) and str(symbol.get("qualified_name", "") or "").strip()
    }
    frontend_edges = [
        edge
        for edge in graph_edges
        if str(edge.get("source", "") or "").strip() in frontend_symbols
        or str(edge.get("target", "") or "").strip() in frontend_symbols
    ]
    relations: dict[str, int] = {}
    for edge in frontend_edges:
        relation = str(edge.get("relation", "") or "").strip()
        if relation:
            relations[relation] = relations.get(relation, 0) + 1
    summary_text = ""
    if frontend_files and frontend_edges:
        summary_text = "Frontend implementation paths include graph-linked TS/TSX files, so behavior may be discovered indirectly."
    elif frontend_files:
        summary_text = "Frontend TS/TSX files are present in app context, but no graph-linked implementation path was summarized."
    return {
        "frontend_file_count": len(frontend_files),
        "top_frontend_files": frontend_files[:6],
        "frontend_graph_edge_count": len(frontend_edges),
        "top_relations": relations,
        "has_indirect_frontend_path": bool(frontend_files and frontend_edges),
        "summary": summary_text,
    }


def _processes_for_files(duckdb_store: DuckDBStore, file_paths: set[str], limit: int = 8) -> list[dict[str, object]]:
    rows = []
    for process in duckdb_store.processes.fetch_clusters(limit=100):
        raw_paths = str(process.get("file_paths_json", "[]") or "[]")
        try:
            process_paths = set(json.loads(raw_paths))
        except json.JSONDecodeError:
            process_paths = set()
        overlap = sorted(file_paths & process_paths)
        if not overlap:
            continue
        rows.append(
            {
                "cluster_id": process.get("cluster_id", ""),
                "name": process.get("name", ""),
                "process_type": process.get("process_type", ""),
                "overlap_files": overlap[:6],
                "process_count": process.get("process_count", 0),
            }
        )
    rows.sort(key=lambda row: (len(row["overlap_files"]), int(row.get("process_count", 0) or 0)), reverse=True)
    return rows[:limit]


def _graph_edges_for_files(kuzu_store: KuzuStore, duckdb_store: DuckDBStore, file_paths: set[str], limit: int = 40) -> list[dict[str, object]]:
    edges: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for file_path in sorted(file_paths):
        for symbol in duckdb_store.fetch_symbols_for_file(file_path)[:12]:
            qualified_name = str(symbol.get("qualified_name", ""))
            if not qualified_name:
                continue
            for edge in [*kuzu_store.edges_for_source(qualified_name), *kuzu_store.edges_for_target(qualified_name)]:
                key = (str(edge.get("source", "")), str(edge.get("relation", "")), str(edge.get("target", "")))
                if key in seen:
                    continue
                seen.add(key)
                edges.append(edge)
                if len(edges) >= limit:
                    return edges
    return edges


def app_context(repo_root: Path, duckdb_store: DuckDBStore, kuzu_store: KuzuStore, target: str = "", limit: int = 12) -> dict[str, object]:
    normalized_target = str(target or "").strip()
    target_shape = _target_shape(normalized_target)
    warnings: list[str] = []
    route_input = normalized_target if bool(target_shape["is_route"]) else ""
    routes = route_map(repo_root, duckdb_store, route=route_input) if route_input else {"routes": [], "compact_summary": {"route_count": 0}}
    route_rows = routes.get("routes", []) if isinstance(routes, dict) else []
    if normalized_target and not normalized_target.startswith("/"):
        route_rows = [
            route
            for route in route_rows
            if normalized_target.lower() in str(route.get("route", "")).lower()
            or normalized_target.lower() in json.dumps(route).lower()
        ]
    selected_routes = route_rows[:limit]
    route_files: set[str] = set()
    for route in selected_routes:
        for handler in route.get("handlers", []) if isinstance(route, dict) else []:
            if handler.get("file_path"):
                route_files.add(str(handler["file_path"]))
        for consumer in route.get("consumers", []) if isinstance(route, dict) else []:
            if consumer.get("file_path"):
                route_files.add(str(consumer["file_path"]))

    symbol_limit = limit * (2 if bool(target_shape["is_broad"]) else 3)
    symbol_rows = duckdb_store.fetch_symbols_for_target(normalized_target, limit=symbol_limit) if normalized_target else []
    symbol_files = {str(row.get("file_path", "")) for row in symbol_rows if row.get("file_path")}
    candidate_files = route_files | set(list(symbol_files)[:limit])
    if not candidate_files and not normalized_target:
        for row in duckdb_store.files.fetch_all()[:limit]:
            candidate_files.add(str(row.get("path", "")))
    if bool(target_shape["is_broad"]):
        warnings.append("Target is broad; app context was narrowed to direct symbol/file matches to avoid an expensive fan-out.")

    file_nodes = [_inflate_file_node(repo_root, duckdb_store, file_path) for file_path in sorted(candidate_files)[:limit]]
    kinds: dict[str, int] = {}
    tables: set[str] = set()
    for node in file_nodes:
        kind = str(node.get("kind", "other"))
        kinds[kind] = kinds.get(kind, 0) + 1
        tables.update(str(table) for table in node.get("db_tables", []) if table)

    api_rows = api_impact(repo_root, duckdb_store, route=route_input, kuzu_store=kuzu_store) if route_input else {"routes": [], "compact_summary": {"route_count": 0}}
    processes = _processes_for_files(duckdb_store, candidate_files, limit=limit)
    graph_limit = 16 if bool(target_shape["is_broad"]) else 40
    graph_edges = _graph_edges_for_files(kuzu_store, duckdb_store, candidate_files, limit=graph_limit)
    frontend_graph = _frontend_graph_summary(file_nodes, graph_edges)

    return {
        "target": normalized_target or "application",
        "guardrail": {
            "target_shape": target_shape,
            "route_scan_skipped": not bool(route_input),
            "api_impact_skipped": not bool(route_input),
            "graph_edge_limit": graph_limit,
            "symbol_match_count": len(symbol_rows),
        },
        "warnings": warnings,
        "routes": selected_routes,
        "files": file_nodes,
        "api_impact": api_rows.get("routes", [])[:limit] if isinstance(api_rows, dict) else [],
        "processes": processes,
        "graph_edges": graph_edges,
        "frontend_graph": frontend_graph,
        "db_tables": sorted(tables),
        "compact_summary": {
            "target": normalized_target or "application",
            "route_count": len(selected_routes),
            "file_count": len(file_nodes),
            "file_kinds": kinds,
            "db_tables": sorted(tables)[:12],
            "top_routes": [route.get("route", "") for route in selected_routes[:8] if isinstance(route, dict)],
            "top_files": [node.get("file_path", "") for node in file_nodes[:8]],
            "top_processes": [process.get("name", "") for process in processes[:6]],
            "graph_edge_count": len(graph_edges),
            "frontend_graph": frontend_graph,
            "warnings": warnings,
        },
    }
