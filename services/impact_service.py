from __future__ import annotations

from collections import deque
import json

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from services.graph_edge_utils import edges_for_source_limited, edges_for_target_limited
from services.symbol_resolution_service import ambiguity_status, resolve_candidates, symbol_uid_from_target


DEFAULT_RELATIONS = ("CALLS", "IMPORTS", "INCLUDES", "REFERENCES", "ACCESSES", "FETCHES", "READS_FIELD", "HAS_METHOD", "HAS_PROPERTY", "EXTENDS", "IMPLEMENTS", "METHOD_OVERRIDES", "METHOD_IMPLEMENTS", "INJECTS", "USES_SERVICE")
RELATION_WEIGHTS = {
    "CALLS": 1.0,
    "IMPORTS": 0.18,
    "INCLUDES": 0.8,
    "REFERENCES": 0.35,
    "ACCESSES": 0.35,
    "FETCHES": 0.9,
    "READS_FIELD": 0.55,
    "HAS_METHOD": 0.4,
    "HAS_PROPERTY": 0.45,
    "EXTENDS": 0.8,
    "IMPLEMENTS": 0.75,
    "METHOD_OVERRIDES": 0.7,
    "METHOD_IMPLEMENTS": 0.65,
    "INJECTS": 0.75,
    "USES_SERVICE": 0.8,
}
DEFAULT_EDGE_LIMIT_PER_RELATION = 80
BROAD_EDGE_LIMIT_PER_RELATION = 18
DEFAULT_NODE_BUDGET = 240
BROAD_NODE_BUDGET = 80
RUNTIME_RELATIONS = {"CALLS", "FETCHES", "READS_FIELD", "ACCESSES", "USES_SERVICE", "INJECTS"}


def _normalize_symbol_uid(target: str, symbol_uid: str | None) -> str | None:
    return symbol_uid_from_target(target, symbol_uid)


def _target_shape(target: str, file_path: str | None = None, kind: str | None = None) -> dict[str, object]:
    normalized = str(target or "").strip()
    tokens = [token for token in normalized.replace("::", ".").replace("/", " ").replace("_", " ").split() if token]
    is_file_like = bool(file_path) or "/" in normalized or normalized.lower().endswith((".py", ".ts", ".tsx", ".js", ".jsx"))
    is_symbol_like = bool(kind) or "." in normalized or "::" in normalized or ":" in normalized
    is_broad = bool(normalized) and not is_file_like and not is_symbol_like and len(tokens) <= 2
    return {
        "normalized": normalized,
        "is_file_like": is_file_like,
        "is_symbol_like": is_symbol_like,
        "is_broad": is_broad,
        "tokens": tokens,
    }


def _graph_target_for_symbol(symbol: dict[str, object], fallback: str) -> str:
    qualified_name = str(symbol.get("qualified_name", "") or "").strip()
    name = str(symbol.get("name", "") or "").strip()
    return qualified_name or name or fallback


def _relation_edges(kuzu_store: KuzuStore, node: str, direction: str, relation_types: tuple[str, ...], per_relation_limit: int = DEFAULT_EDGE_LIMIT_PER_RELATION) -> list[dict[str, object]]:
    edges = []
    for relation in relation_types:
        if direction == "upstream":
            edges.extend(edges_for_target_limited(kuzu_store, node, relation=relation, limit=per_relation_limit))
        else:
            edges.extend(edges_for_source_limited(kuzu_store, node, relation=relation, limit=per_relation_limit))
    unique: dict[tuple[str, str, str], dict[str, object]] = {}
    for edge in edges:
        unique[(str(edge.get("source")), str(edge.get("relation")), str(edge.get("target")))] = edge
    return list(unique.values())


def _risk_level(direct_count: int, impacted_count: int, files_affected: int, ambiguous: bool, runtime_direct_count: int, semantic_weight: float) -> str:
    if runtime_direct_count >= 8 or semantic_weight >= 35 or files_affected >= 12:
        return "HIGH"
    if runtime_direct_count >= 3 or semantic_weight >= 10 or files_affected >= 5 or direct_count >= 20 or (ambiguous and impacted_count > 0):
        return "MEDIUM"
    return "LOW"


def _semantic_weight(items: list[dict[str, object]]) -> float:
    return round(sum(float(RELATION_WEIGHTS.get(str(item.get("relation", "")), 0.25)) for item in items), 2)


def _process_participation(duckdb_store: DuckDBStore, symbol_name: str, limit: int = 8) -> list[dict[str, object]]:
    rows = duckdb_store.fetch_process_clusters_for_symbol(symbol_name, limit=limit)
    processes = []
    for row in rows:
        processes.append(
            {
                "cluster_id": row.get("cluster_id", ""),
                "name": row.get("name", ""),
                "process_type": row.get("process_type", ""),
                "entry_symbol": row.get("canonical_entry_symbol", ""),
                "terminal_symbol": row.get("canonical_terminal_symbol", ""),
                "process_count": int(row.get("process_count", 0) or 0),
                "avg_step_count": float(row.get("avg_step_count", 0.0) or 0.0),
                "module_tags": json.loads(str(row.get("module_tags_json", "[]") or "[]")),
            }
        )
    return processes


def _affected_modules(items: list[dict[str, object]]) -> list[dict[str, object]]:
    counts: dict[str, int] = {}
    for item in items:
        file_path = str(item.get("file_path", ""))
        module = file_path.split("/", 1)[0] if "/" in file_path else file_path
        if module:
            counts[module] = counts.get(module, 0) + 1
    return [
        {"module": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:8]
    ]


def _affected_flows(items: list[dict[str, object]]) -> list[dict[str, object]]:
    flows = []
    for item in items[:12]:
        symbol = str(item.get("symbol", ""))
        via = str(item.get("via", ""))
        if symbol:
            flows.append({"name": f"{via} → {symbol}" if via else symbol, "step": int(item.get("depth", 0) or 0)})
    return flows


def _is_frontend_path(file_path: str) -> bool:
    normalized = str(file_path or "").replace("\\", "/").lower()
    return normalized.endswith((".ts", ".tsx", ".js", ".jsx")) and any(
        hint in normalized for hint in ("/frontend", "/components", "/pages", "/views", "/screens", "/hooks", "/ui")
    )


def _frontend_graph_summary(target_file_path: str, items: list[dict[str, object]]) -> dict[str, object]:
    frontend_files: list[str] = []
    relation_counts: dict[str, int] = {}
    if _is_frontend_path(target_file_path):
        frontend_files.append(str(target_file_path).replace("\\", "/"))
    for item in items:
        file_path = str(item.get("file_path", "") or "").replace("\\", "/")
        if not _is_frontend_path(file_path):
            continue
        if file_path not in frontend_files:
            frontend_files.append(file_path)
        relation = str(item.get("relation", "") or "").strip().upper()
        if relation:
            relation_counts[relation] = relation_counts.get(relation, 0) + 1
    summary = ""
    if frontend_files and relation_counts:
        summary = "Impact includes graph-linked frontend TS/TSX paths, so implementation fallout may be indirect rather than lexical."
    elif frontend_files:
        summary = "Impact touches frontend TS/TSX files, but the graph path is weak or shallow."
    return {
        "frontend_file_count": len(frontend_files),
        "top_frontend_files": frontend_files[:6],
        "frontend_graph_edge_count": sum(relation_counts.values()),
        "top_relations": relation_counts,
        "has_indirect_frontend_path": bool(frontend_files and relation_counts),
        "summary": summary,
    }


def analyze_impact(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    target: str,
    direction: str = "upstream",
    max_depth: int = 3,
    relation_types: tuple[str, ...] = DEFAULT_RELATIONS,
    file_path: str | None = None,
    kind: str | None = None,
    symbol_uid: str | None = None,
) -> dict[str, object]:
    normalized_direction = direction if direction in {"upstream", "downstream"} else "upstream"
    target_shape = _target_shape(target, file_path=file_path, kind=kind)
    resolved_symbol_uid = _normalize_symbol_uid(target, symbol_uid)
    lookup_target = str(target or "").strip()
    if resolved_symbol_uid and resolved_symbol_uid == lookup_target:
        lookup_target = ""
    candidate_rows = resolve_candidates(duckdb_store, target=lookup_target, file_path=file_path, kind=kind, symbol_uid_value=resolved_symbol_uid, limit=25)
    resolved = candidate_rows[0] if candidate_rows else None
    if resolved is None:
        return {
            "target": target,
            "direction": normalized_direction,
            "risk": "UNKNOWN",
            "error": f"Target '{target}' not found",
        }
    candidate_matches = []
    for item in candidate_rows[:5]:
        symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
        candidate_matches.append({
            "qualified_name": symbol.get("qualified_name", ""),
            "file_path": symbol.get("file_path", ""),
            "kind": symbol.get("kind", ""),
            "uid": symbol.get("uid", ""),
            "score": round(float(item.get("score", 0.0) or 0.0), 4),
            "confidence": item.get("confidence", "low"),
        })
    target_symbol = resolved["symbol"]
    resolved_target = target_symbol.get("qualified_name") or target_symbol.get("name") or target
    graph_target = _graph_target_for_symbol(target_symbol, resolved_target)
    ambiguous = ambiguity_status(candidate_rows)
    broad_query = bool(target_shape["is_broad"]) or ambiguous
    per_relation_limit = BROAD_EDGE_LIMIT_PER_RELATION if broad_query else DEFAULT_EDGE_LIMIT_PER_RELATION
    node_budget = BROAD_NODE_BUDGET if broad_query else DEFAULT_NODE_BUDGET
    queue = deque([(graph_target, 0)])
    seen = {graph_target}
    by_depth: dict[str, list[dict[str, object]]] = {}
    all_impacted: list[dict[str, object]] = []
    traversal_truncated = False
    while queue:
        if len(all_impacted) >= node_budget:
            traversal_truncated = True
            break
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in _relation_edges(kuzu_store, current, direction=normalized_direction, relation_types=relation_types, per_relation_limit=per_relation_limit):
            neighbor = str(edge.get("source")) if normalized_direction == "upstream" else str(edge.get("target"))
            if not neighbor or neighbor in seen:
                continue
            seen.add(neighbor)
            neighbor_matches = duckdb_store.fetch_symbols_for_target(neighbor, limit=1)
            file_path = neighbor_matches[0].get("file_path", "") if neighbor_matches else ""
            item = {
                "symbol": neighbor,
                "relation": edge.get("relation", ""),
                "file_path": file_path,
                "depth": depth + 1,
                "via": current,
            }
            by_depth.setdefault(f"d={depth + 1}", []).append(item)
            all_impacted.append(item)
            if len(all_impacted) >= node_budget:
                traversal_truncated = True
                break
            queue.append((neighbor, depth + 1))
    impacted_count = len(all_impacted)
    direct_count = len(by_depth.get("d=1", []))
    runtime_direct_count = sum(1 for item in by_depth.get("d=1", []) if str(item.get("relation", "")).upper() in RUNTIME_RELATIONS)
    files_affected = len({item["file_path"] for item in all_impacted if item.get("file_path")})
    semantic_weight = _semantic_weight(all_impacted)
    risk = _risk_level(direct_count, impacted_count, files_affected, ambiguous, runtime_direct_count, semantic_weight)
    process_participation = _process_participation(duckdb_store, graph_target)
    frontend_graph = _frontend_graph_summary(str(target_symbol.get("file_path", "") or ""), all_impacted)
    warnings = ["Target resolution is ambiguous; pass file_path or kind to narrow it."] if ambiguous else []
    if broad_query:
        warnings.append("Target is broad; impact traversal was capped to avoid an expensive fan-out.")
    if traversal_truncated:
        warnings.append("Impact traversal hit a safety cap; results are partial but still useful for narrowing.")
    return {
        "target": {
            "name": target_symbol.get("name", target),
            "qualified_name": resolved_target,
            "kind": target_symbol.get("kind", ""),
            "uid": target_symbol.get("uid", resolved_symbol_uid or ""),
            "file_path": target_symbol.get("file_path", ""),
            "confidence": resolved.get("confidence", "low"),
            "relevance": resolved.get("relevance", ""),
        },
        "direction": normalized_direction,
        "relation_types": list(relation_types),
        "impacted_count": impacted_count,
        "risk": risk,
        "status": "partial" if traversal_truncated else "ambiguous" if ambiguous else "found",
        "warnings": warnings,
        "guardrail": {
            "broad_query": broad_query,
            "per_relation_limit": per_relation_limit,
            "node_budget": node_budget,
            "traversal_truncated": traversal_truncated,
        },
        "candidate_matches": candidate_matches,
        "affected_modules": _affected_modules(all_impacted),
        "affected_flows": _affected_flows(all_impacted),
        "frontend_graph": frontend_graph,
        "participating_processes": process_participation,
        "process_explanation": {
            "top_relations": [item.get("relation", "") for item in all_impacted[:8]],
            "semantic_weight": semantic_weight,
            "participating_processes": [item.get("name", "") for item in process_participation[:5]],
            "reason": "Impact is estimated from weighted graph traversals across calls, imports, references, field access, and inheritance relations.",
        },
        "summary": {
            "direct": direct_count,
            "runtime_direct": runtime_direct_count,
            "max_depth": max_depth,
            "files_affected": files_affected,
            "semantic_weight": semantic_weight,
        },
        "by_depth": by_depth,
        "compact_summary": {
            "target": resolved_target,
            "direction": normalized_direction,
            "risk": risk,
            "status": "partial" if traversal_truncated else "ambiguous" if ambiguous else "found",
            "impacted_count": impacted_count,
            "direct": direct_count,
            "runtime_direct": runtime_direct_count,
            "semantic_weight": semantic_weight,
            "top_impacted": [item["symbol"] for item in all_impacted[:8]],
            "frontend_graph": frontend_graph,
            "warnings": warnings,
        },
    }
