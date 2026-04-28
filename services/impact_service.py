from __future__ import annotations

from collections import deque
import json

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from services.symbol_resolution_service import ambiguity_status, resolve_candidates, symbol_uid_from_target


DEFAULT_RELATIONS = ("CALLS", "IMPORTS", "REFERENCES")
RELATION_WEIGHTS = {"CALLS": 1.0, "IMPORTS": 0.85, "REFERENCES": 0.45}


def _normalize_symbol_uid(target: str, symbol_uid: str | None) -> str | None:
    return symbol_uid_from_target(target, symbol_uid)


def _graph_target_for_symbol(symbol: dict[str, object], fallback: str) -> str:
    qualified_name = str(symbol.get("qualified_name", "") or "").strip()
    name = str(symbol.get("name", "") or "").strip()
    return qualified_name or name or fallback


def _relation_edges(kuzu_store: KuzuStore, node: str, direction: str, relation_types: tuple[str, ...]) -> list[dict[str, object]]:
    edges = []
    for relation in relation_types:
        if direction == "upstream":
            edges.extend(kuzu_store.edges_for_target(node, relation=relation))
        else:
            edges.extend(kuzu_store.edges_for_source(node, relation=relation))
    unique: dict[tuple[str, str, str], dict[str, object]] = {}
    for edge in edges:
        unique[(str(edge.get("source")), str(edge.get("relation")), str(edge.get("target")))] = edge
    return list(unique.values())


def _risk_level(direct_count: int, impacted_count: int, files_affected: int, ambiguous: bool) -> str:
    if direct_count >= 10 or impacted_count >= 25 or files_affected >= 12:
        return "HIGH"
    if direct_count >= 4 or impacted_count >= 10 or files_affected >= 5 or (ambiguous and impacted_count > 0):
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
    queue = deque([(graph_target, 0)])
    seen = {graph_target}
    by_depth: dict[str, list[dict[str, object]]] = {}
    all_impacted: list[dict[str, object]] = []
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in _relation_edges(kuzu_store, current, direction=normalized_direction, relation_types=relation_types):
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
            queue.append((neighbor, depth + 1))
    impacted_count = len(all_impacted)
    direct_count = len(by_depth.get("d=1", []))
    files_affected = len({item["file_path"] for item in all_impacted if item.get("file_path")})
    semantic_weight = _semantic_weight(all_impacted)
    risk = _risk_level(direct_count, impacted_count, files_affected, ambiguous)
    process_participation = _process_participation(duckdb_store, graph_target)
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
        "status": "ambiguous" if ambiguous else "found",
        "warnings": ["Target resolution is ambiguous; pass file_path or kind to narrow it."] if ambiguous else [],
        "candidate_matches": candidate_matches,
        "affected_modules": _affected_modules(all_impacted),
        "affected_flows": _affected_flows(all_impacted),
        "participating_processes": process_participation,
        "process_explanation": {
            "top_relations": [item.get("relation", "") for item in all_impacted[:8]],
            "semantic_weight": semantic_weight,
            "participating_processes": [item.get("name", "") for item in process_participation[:5]],
            "reason": "Impact is estimated from weighted CALLS, IMPORTS, and REFERENCES traversals.",
        },
        "summary": {
            "direct": direct_count,
            "max_depth": max_depth,
            "files_affected": files_affected,
            "semantic_weight": semantic_weight,
        },
        "by_depth": by_depth,
        "compact_summary": {
            "target": resolved_target,
            "direction": normalized_direction,
            "risk": risk,
            "status": "ambiguous" if ambiguous else "found",
            "impacted_count": impacted_count,
            "direct": direct_count,
            "top_impacted": [item["symbol"] for item in all_impacted[:8]],
        },
    }
