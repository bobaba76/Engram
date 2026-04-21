from storage.kuzu_store import KuzuStore


COMMON_HUB_TOKENS = {
    "data",
    "max",
    "min",
    "value",
    "values",
    "item",
    "items",
    "result",
    "results",
    "utils",
    "util",
    "helper",
    "helpers",
    "common",
    "base",
    "config",
    "get_db_connection",
    "get_db_path",
}


def _tokenize(value: str) -> set[str]:
    lowered = value.replace("\\", "/").replace(".", " ").replace(":", " ").replace("_", " ").replace("-", " ").lower()
    return {token for token in lowered.split() if token}


def _hub_penalty(node: str) -> int:
    tokens = _tokenize(node)
    penalty = 0
    if any(token in COMMON_HUB_TOKENS for token in tokens):
        penalty += 2
    if len(tokens) <= 2 and any(len(token) <= 4 for token in tokens):
        penalty += 1
    if any(token in {"connection", "path", "db", "database"} for token in tokens):
        penalty += 1
    return penalty


def _feature_overlap(node: str, target: str) -> int:
    node_tokens = _tokenize(node)
    target_tokens = _tokenize(target)
    overlap = len((node_tokens & target_tokens) - {"py", "ts", "tsx", "js", "jsx"})
    return overlap


def _node_priority(node: str, target: str) -> tuple[int, int, int, int, str]:
    same_namespace = 0
    if "." in node and "." in target:
        same_namespace = int(node.rsplit(".", 1)[0] == target.rsplit(".", 1)[0])
    same_file_hint = int(node.split(":", 1)[0] == target.split(":", 1)[0])
    symbol_like = int("." in node or "::" in node)
    service_or_repository = int(any(part in node.lower() for part in ("service", "repository", "router", "processor")))
    overlap = _feature_overlap(node, target)
    hub_penalty = _hub_penalty(node)
    return (same_namespace, same_file_hint, overlap, symbol_like, service_or_repository, -hub_penalty, node)


def _edge_sort_key(edge: dict[str, object], target: str) -> tuple[int, str, str, str]:
    source = str(edge.get("source", ""))
    relation = str(edge.get("relation", ""))
    target_value = str(edge.get("target", ""))
    touches_target = int(source == target or target_value == target)
    neighbor = target_value if source == target else source
    return (touches_target, *_node_priority(neighbor, target), relation, source, target_value)


def _filter_edges(
    edges: list[dict[str, object]],
    target: str,
    relation: str | None = None,
    mode: str = "full",
    max_edges: int | None = None,
    suppress_common_hubs: bool = False,
) -> list[dict[str, object]]:
    filtered = edges
    if relation:
        filtered = [edge for edge in filtered if str(edge.get("relation", "")).upper() == relation.upper()]
    if mode == "direct":
        filtered = [edge for edge in filtered if edge.get("source") == target or edge.get("target") == target]
    if suppress_common_hubs:
        filtered = [
            edge
            for edge in filtered
            if _hub_penalty(str(edge.get("source", ""))) < 2 and _hub_penalty(str(edge.get("target", ""))) < 2
        ]
    sorted_edges = sorted(filtered, key=lambda edge: _edge_sort_key(edge, target), reverse=True)
    if mode == "focused":
        direct_edges = [edge for edge in sorted_edges if edge.get("source") == target or edge.get("target") == target]
        expanded_edges = [edge for edge in sorted_edges if edge not in direct_edges]
        sorted_edges = direct_edges + expanded_edges[: max(0, (max_edges or 16) - len(direct_edges))]
    if max_edges is not None and max_edges > 0:
        sorted_edges = sorted_edges[:max_edges]
    return sorted_edges


def _nodes_for_edges(target: str, edges: list[dict[str, object]]) -> list[str]:
    nodes = {target}
    for edge in edges:
        source = str(edge.get("source", "")).strip()
        target_value = str(edge.get("target", "")).strip()
        if source:
            nodes.add(source)
        if target_value:
            nodes.add(target_value)
    return sorted(nodes)


def _top_neighbors(edges: list[dict[str, object]], target: str, limit: int = 8) -> list[dict[str, object]]:
    scores: dict[str, dict[str, object]] = {}
    for edge in edges:
        source = str(edge.get("source", ""))
        target_value = str(edge.get("target", ""))
        relation = str(edge.get("relation", ""))
        for node in (source, target_value):
            if not node or node == target:
                continue
            entry = scores.setdefault(node, {"node": node, "edge_count": 0, "relations": set(), "feature_overlap": _feature_overlap(node, target), "hub_penalty": _hub_penalty(node)})
            entry["edge_count"] = int(entry["edge_count"]) + 1
            relations = entry["relations"]
            if isinstance(relations, set):
                relations.add(relation)
    ranked = sorted(
        scores.values(),
        key=lambda item: (int(item["feature_overlap"]), -int(item["hub_penalty"]), int(item["edge_count"]), len(item["relations"]), *_node_priority(str(item["node"]), target)),
        reverse=True,
    )
    compact: list[dict[str, object]] = []
    for item in ranked[:limit]:
        relations = item["relations"]
        compact.append(
            {
                "node": item["node"],
                "edge_count": item["edge_count"],
                "feature_overlap": item["feature_overlap"],
                "hub_penalty": item["hub_penalty"],
                "relations": sorted(relations) if isinstance(relations, set) else [],
            }
        )
    return compact


def _relation_breakdown(edges: list[dict[str, object]], limit_per_relation: int = 4) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for edge in edges:
        relation = str(edge.get("relation", "UNKNOWN"))
        grouped.setdefault(relation, []).append(edge)
    breakdown: dict[str, dict[str, object]] = {}
    for relation, relation_edges in grouped.items():
        breakdown[relation] = {
            "count": len(relation_edges),
            "sample": relation_edges[:limit_per_relation],
        }
    return breakdown


def _expansion_warnings(target: str, depth: int, node_count: int, edge_count: int, mode: str, relation: str | None, suppress_common_hubs: bool) -> list[str]:
    warnings: list[str] = []
    if edge_count >= 200 or node_count >= 120:
        warnings.append("This graph is broad and may contain noisy cross-cutting context.")
    if depth > 1 and edge_count >= 80:
        warnings.append("Try depth=1 first if you want a tighter neighborhood.")
    if "." not in target and "/" in target and edge_count >= 80:
        warnings.append("Try a symbol target instead of a file target for more focused graph results.")
    if relation is None and edge_count >= 80:
        warnings.append("Try filtering by relation such as CALLS, IMPORTS, or REFERENCES.")
    if mode == "full" and edge_count >= 80:
        warnings.append("Try mode='focused' or mode='direct' to reduce payload size.")
    if not suppress_common_hubs and edge_count >= 40:
        warnings.append("Try suppress_common_hubs=true to hide generic utility neighbors.")
    return warnings


def get_callers_and_callees(kuzu_store: KuzuStore, target: str) -> dict[str, object]:
    callers = kuzu_store.edges_for_target(target, relation="CALLS")
    callees = kuzu_store.edges_for_source(target, relation="CALLS")
    return {
        "target": target,
        "callers": callers,
        "callees": callees,
        "compact_summary": {
            "target": target,
            "caller_count": len(callers),
            "callee_count": len(callees),
            "top_callers": callers[:5],
            "top_callees": callees[:5],
            "all_related_symbol_count": len({str(edge.get("source", "")) for edge in callers} | {str(edge.get("target", "")) for edge in callees}),
        },
    }



def get_graph_neighborhood(kuzu_store: KuzuStore, target: str, depth: int = 1) -> dict[str, object]:
    return get_graph_neighborhood_with_options(kuzu_store, target=target, depth=depth)


def get_graph_neighborhood_with_options(
    kuzu_store: KuzuStore,
    target: str,
    depth: int = 1,
    relation: str | None = None,
    max_edges: int | None = None,
    mode: str = "full",
    suppress_common_hubs: bool = False,
) -> dict[str, object]:
    normalized_mode = mode if mode in {"full", "focused", "direct"} else "full"
    neighborhood = kuzu_store.neighborhood(target=target, depth=depth)
    all_edges = neighborhood.get("edges", [])
    filtered_edges = _filter_edges(all_edges, target=target, relation=relation, mode=normalized_mode, max_edges=max_edges, suppress_common_hubs=suppress_common_hubs)
    direct_edges = [edge for edge in filtered_edges if edge.get("source") == target or edge.get("target") == target]
    filtered_nodes = _nodes_for_edges(target, filtered_edges)
    return {
        "target": target,
        "depth": depth,
        "mode": normalized_mode,
        "relation_filter": relation,
        "max_edges": max_edges,
        "suppress_common_hubs": suppress_common_hubs,
        "nodes": filtered_nodes,
        "edges": filtered_edges,
        "raw_counts": {
            "node_count": len(neighborhood.get("nodes", [])),
            "edge_count": len(all_edges),
        },
        "compact_summary": {
            "target": target,
            "depth": depth,
            "mode": normalized_mode,
            "relation_filter": relation,
            "suppress_common_hubs": suppress_common_hubs,
            "node_count": len(filtered_nodes),
            "edge_count": len(filtered_edges),
            "direct_edge_count": len(direct_edges),
            "raw_node_count": len(neighborhood.get("nodes", [])),
            "raw_edge_count": len(all_edges),
            "top_edges": filtered_edges[:8],
            "top_direct_edges": direct_edges[:8],
            "top_neighbors": _top_neighbors(filtered_edges, target),
            "relation_breakdown": _relation_breakdown(filtered_edges),
            "warnings": _expansion_warnings(target, depth, len(filtered_nodes), len(filtered_edges), normalized_mode, relation, suppress_common_hubs),
        },
    }
