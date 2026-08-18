from __future__ import annotations

import json
from typing import TYPE_CHECKING

from services.symbol_resolution_service import resolve_candidates

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore


def _inflate_cluster(row: dict[str, object], duckdb_store: DuckDBStore, compact: bool = False) -> dict[str, object]:
    cluster_id = str(row.get("cluster_id", ""))
    file_paths = json.loads(str(row.get("file_paths_json", "[]") or "[]"))
    base = {
        "cluster_id": cluster_id,
        "name": row.get("name", ""),
        "process_type": row.get("process_type", ""),
        "canonical_entry_symbol": row.get("canonical_entry_symbol", ""),
        "canonical_terminal_symbol": row.get("canonical_terminal_symbol", ""),
        "process_count": int(row.get("process_count", 0) or 0),
        "avg_step_count": float(row.get("avg_step_count", 0.0) or 0.0),
        "module_tags": json.loads(str(row.get("module_tags_json", "[]") or "[]"))[:10],
        "community_tags": json.loads(str(row.get("community_tags_json", "[]") or "[]"))[:10],
        "file_paths": file_paths[:20],
        "file_paths_total_count": len(file_paths) if len(file_paths) > 20 else None,
        "keywords": json.loads(str(row.get("keywords_json", "[]") or "[]"))[:10],
    }
    if compact:
        # Skip memberships and relationships — they're the bulk of the payload
        # and can be fetched per-process via symbol_process_participation.
        base["membership_count"] = duckdb_store.processes.fetch_memberships_for_cluster(cluster_id, limit=1)
        base["has_relationships"] = bool(duckdb_store.processes.fetch_relationships(cluster_id, limit=1))
        return base
    base["memberships"] = duckdb_store.processes.fetch_memberships_for_cluster(cluster_id, limit=20)
    base["relationships"] = duckdb_store.processes.fetch_relationships(cluster_id, limit=15)
    return base


def list_processes(duckdb_store: DuckDBStore, query: str = "", limit: int = 15, compact: bool = False) -> dict[str, object]:
    rows = [_inflate_cluster(row, duckdb_store, compact=compact) for row in duckdb_store.processes.fetch_clusters(limit=limit, query=query)]
    return {
        "query": query,
        "total": len(rows),
        "processes": rows,
        "compact_summary": {
            "target": query or "all_processes",
            "total": len(rows),
            "top_processes": [row.get("name", "") for row in rows[:8]],
        },
    }


def get_symbol_process_participation(
    duckdb_store: DuckDBStore,
    target: str,
    file_path: str | None = None,
    kind: str | None = None,
    symbol_uid: str | None = None,
    limit: int = 15,
) -> dict[str, object]:
    candidates = resolve_candidates(
        duckdb_store,
        target=target,
        file_path=file_path,
        kind=kind,
        symbol_uid_value=symbol_uid,
        limit=5,
    )
    if not candidates:
        return {
            "target": target,
            "status": "not_found",
            "processes": [],
            "compact_summary": {"target": target, "status": "not_found", "process_count": 0},
        }
    primary = candidates[0]
    symbol = primary.get("symbol", {}) if isinstance(primary, dict) else {}
    resolved_target = str(symbol.get("qualified_name") or symbol.get("name") or target)
    processes = [_inflate_cluster(row, duckdb_store) for row in duckdb_store.processes.fetch_clusters_for_symbol(resolved_target, limit=limit)]
    return {
        "target": target,
        "status": "found",
        "resolved_target": resolved_target,
        "resolved_uid": symbol.get("uid", ""),
        "processes": processes,
        "candidate_matches": [
            {
                "qualified_name": item.get("symbol", {}).get("qualified_name", ""),
                "file_path": item.get("symbol", {}).get("file_path", ""),
                "kind": item.get("symbol", {}).get("kind", ""),
                "uid": item.get("symbol", {}).get("uid", ""),
                "score": item.get("score", 0.0),
                "confidence": item.get("confidence", "low"),
            }
            for item in candidates
        ],
        "compact_summary": {
            "target": resolved_target,
            "status": "found",
            "process_count": len(processes),
            "top_processes": [row.get("name", "") for row in processes[:8]],
        },
    }
