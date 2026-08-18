"""Shortest-path / A<->B connection queries over the indexed KuzuDB graph.

Answers the direct question "how are A and B connected?" in a single call,
without requiring the caller to hand-write Cypher.

Resolution reuses the existing ``resolve_candidates`` plumbing so broad
source/target names get the same ambiguity handling as other tools. The
path itself is computed via KuzuDB's native variable-length Cypher pattern
matching (``-[*..N]-``), which is ~450x faster than a Python BFS for dense
graphs (0.08s vs 18s for a 3-hop path through a degree-1000 god-node).
A Python BFS fallback is kept for KuzuDB versions or edge cases where the
Cypher approach returns no results.
"""
from __future__ import annotations

from collections import deque

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore

DEFAULT_MAX_HOPS = 8
HARD_MAX_HOPS = 12
# Safety cap for the Python BFS fallback. The Cypher-native path query is
# always tried first and is not subject to these limits. MAX_NODES_VISITED
# prevents runaway BFS through god-nodes (a degree-1000 hub would otherwise
# expand 1000+ neighbors per level, turning a sub-second query into 18s).
MAX_NEIGHBORS_PER_NODE = 200
MAX_NODES_VISITED = 1000

# Relations that imply a real structural connection between two symbols.
# We deliberately exclude IMPORTS from the default traversal because it
# fans out to every importer of a shared module and produces noisy paths
# like ``a.py <--imports-- shared.py --imports--> b.py`` that rarely match
# what the caller means by "how are A and B connected?". Callers can opt
# back in via ``relation_types``.
DEFAULT_RELATION_TYPES: tuple[str, ...] = (
    "CALLS",
    "REFERENCES",
    "DECLARES",
    "ASSOCIATED_WITH",
    "ACCESSES",
    "INCLUDES",
    "DECLARES_IN_HEADER",
    "DEFINES_IMPLEMENTATION",
    "INJECTS",
    "USES_SERVICE",
    "FETCHES",
    "READS_FIELD",
    "HAS_METHOD",
    "HAS_PROPERTY",
    "EXTENDS",
    "IMPLEMENTS",
    "METHOD_OVERRIDES",
    "METHOD_IMPLEMENTS",
)


def _resolve_one(
    duckdb_store: DuckDBStore,
    target: str,
    file_path: str | None = None,
    kind: str | None = None,
    symbol_uid: str | None = None,
) -> tuple[str | None, list[dict[str, object]], bool]:
    """Resolve a single endpoint to a graph qualified_name.

    Returns ``(resolved_qn, candidates, ambiguous)``. ``resolved_qn`` is
    ``None`` when nothing matched. ``candidates`` is the raw resolution
    payload (score/file/kind) for surfacing in the tool output.
    """
    from services.symbol_resolution_service import resolve_candidates, symbol_uid_from_target

    resolved_uid = symbol_uid_from_target(target, symbol_uid)
    lookup = str(target or "").strip()
    if resolved_uid and resolved_uid == lookup:
        lookup = ""
    rows = resolve_candidates(
        duckdb_store,
        target=lookup,
        file_path=file_path,
        kind=kind,
        symbol_uid_value=resolved_uid,
        limit=5,
    )
    if not rows:
        return None, [], False
    primary = rows[0]
    symbol = primary.get("symbol", {}) if isinstance(primary, dict) else {}
    qn = str(symbol.get("qualified_name", "") or symbol.get("name", "") or "").strip()
    candidates = [
        {
            "qualified_name": (item.get("symbol", {}) if isinstance(item, dict) else {}).get("qualified_name", ""),
            "file_path": (item.get("symbol", {}) if isinstance(item, dict) else {}).get("file_path", ""),
            "kind": (item.get("symbol", {}) if isinstance(item, dict) else {}).get("kind", ""),
            "score": round(float(item.get("score", 0.0) or 0.0), 4),
            "confidence": item.get("confidence", "low"),
        }
        for item in rows
    ]
    # Ambiguity heuristic: top two scores within 10% of each other.
    ambiguous = False
    if len(rows) >= 2:
        top = float(rows[0].get("score", 0.0) or 0.0)
        runner = float(rows[1].get("score", 0.0) or 0.0)
        if top > 0 and (top - runner) / top < 0.10:
            ambiguous = True
    return qn or None, candidates, ambiguous


def _cypher_shortest_path(
    kuzu_store: KuzuStore,
    source: str,
    target: str,
    relation_types: tuple[str, ...] | None,
    max_hops: int,
) -> list[dict[str, object]] | None:
    """Find shortest path using KuzuDB variable-length Cypher queries.

    Tries ``*..1``, ``*..2``, ... up to ``max_hops`` and returns the first
    match, guaranteeing shortest path. Uses undirected traversal (``-``)
    so source/target order doesn't matter.

    Returns a list of hops ``[{source, relation, target}, ...]`` or
    ``None`` when no path exists or the Cypher approach is unavailable.
    """
    if source == target:
        return []
    allowed = relation_types if relation_types else DEFAULT_RELATION_TYPES
    # Build the relation alternation: [:CALLS|REFERENCES|...]
    # Only include relations that actually exist in the store to avoid
    # Cypher parse errors on non-existent relation tables.
    existing = set(kuzu_store.available_relations())
    rels_to_use = [r for r in allowed if r in existing]
    if not rels_to_use:
        return None
    rel_pattern = "|".join(rels_to_use)

    for depth in range(1, max_hops + 1):
        query = (
            f"MATCH p = (s:Symbol {{qualified_name: $src}})-[:{rel_pattern}*..{depth}]-(t:Symbol {{qualified_name: $tgt}}) "
            "RETURN nodes(p) AS ns, relationships(p) AS rs LIMIT 1"
        )
        try:
            result = kuzu_store._safe_execute(query, {"src": source, "tgt": target})
            rows = result.get_all() if result else []
        except Exception:
            continue
        if not rows:
            continue
        ns, rs = rows[0][0], rows[0][1]
        if not ns or not rs:
            continue
        # Build a lookup from _id -> qualified_name for edge endpoint resolution.
        id_to_qn: dict[str, str] = {}
        for n in ns:
            if isinstance(n, dict):
                nid = n.get("_id")
                qn = n.get("qualified_name", "")
                if nid is not None and qn:
                    id_to_qn[str(nid)] = qn
        # Reconstruct hops from relationships.
        hops: list[dict[str, object]] = []
        for rel in rs:
            if not isinstance(rel, dict):
                continue
            rel_type = str(rel.get("_label", "") or "")
            src_id = str(rel.get("_src", ""))
            dst_id = str(rel.get("_dst", ""))
            src_qn = id_to_qn.get(src_id, "")
            dst_qn = id_to_qn.get(dst_id, "")
            if src_qn and dst_qn:
                hops.append({"source": src_qn, "relation": rel_type, "target": dst_qn})
        if hops:
            return hops
    return None


def _bfs_shortest_path(
    kuzu_store: KuzuStore,
    source: str,
    target: str,
    relation_types: tuple[str, ...] | None,
    max_hops: int,
    max_neighbors_per_node: int = MAX_NEIGHBORS_PER_NODE,
    max_nodes_visited: int = MAX_NODES_VISITED,
) -> list[dict[str, object]] | str | None:
    """Bidirectional-agnostic BFS over the graph store.

    Returns a list of hops ``[{source, relation, target}, ...]``, ``None``
    when no path exists within ``max_hops``, or the string ``"capped"``
    when the search was terminated early due to safety limits.

    Uses 2 queries per node (all relations in one call) instead of 2 per
    relation per node, reducing query count by ~18x for the default
    relation set. Neighbor expansion is capped per node to prevent
    god-node explosion (a degree-1000 hub would otherwise expand 1000+
    neighbors per BFS level).
    """
    if source == target:
        return []
    allowed = set(relation_types) if relation_types else set(DEFAULT_RELATION_TYPES)
    # Predecessor map: node -> (prev_node, relation_into_node)
    prev: dict[str, tuple[str, str]] = {source: ("", "")}
    queue: deque[str] = deque([source])
    hops = 0
    visited_count = 0
    while queue and hops < max_hops:
        for _ in range(len(queue)):
            if visited_count >= max_nodes_visited:
                return "capped"
            node = queue.popleft()
            visited_count += 1
            # Gather undirected neighbors in 2 queries (not 2x len(relations)).
            neighbors: list[tuple[str, str]] = []
            for edge in kuzu_store.edges_for_source(node):
                rel = str(edge.get("relation", "") or "").upper()
                if rel not in allowed:
                    continue
                nb = str(edge.get("target", "") or "")
                if nb:
                    neighbors.append((nb, rel))
            for edge in kuzu_store.edges_for_target(node):
                rel = str(edge.get("relation", "") or "").upper()
                if rel not in allowed:
                    continue
                nb = str(edge.get("source", "") or "")
                if nb:
                    neighbors.append((nb, rel))
            # Cap neighbors per node to prevent god-node explosion.
            # Without this, a single degree-1000 hub adds 1000+ nodes to
            # the queue in one level, and the next level expands each of
            # those, leading to exponential blow-up.
            if len(neighbors) > max_neighbors_per_node:
                neighbors = neighbors[:max_neighbors_per_node]
            for nb, rel in neighbors:
                if nb in prev:
                    continue
                prev[nb] = (node, rel)
                if nb == target:
                    # Reconstruct path.
                    hops_chain: list[dict[str, object]] = []
                    cursor = target
                    while cursor != source:
                        prev_node, prev_rel = prev[cursor]
                        hops_chain.append({"source": prev_node, "relation": prev_rel, "target": cursor})
                        cursor = prev_node
                    hops_chain.reverse()
                    return hops_chain
                queue.append(nb)
        hops += 1
    return None


def shortest_path(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    source: str,
    target: str,
    source_file: str | None = None,
    source_kind: str | None = None,
    source_uid: str | None = None,
    target_file: str | None = None,
    target_kind: str | None = None,
    target_uid: str | None = None,
    max_hops: int = DEFAULT_MAX_HOPS,
    relation_types: tuple[str, ...] | None = None,
) -> dict[str, object]:
    if not source or not target:
        raise ValueError("source and target are required")
    capped_hops = max(1, min(int(max_hops), HARD_MAX_HOPS))
    src_qn, src_candidates, src_ambiguous = _resolve_one(
        duckdb_store, source, file_path=source_file, kind=source_kind, symbol_uid=source_uid
    )
    tgt_qn, tgt_candidates, tgt_ambiguous = _resolve_one(
        duckdb_store, target, file_path=target_file, kind=target_kind, symbol_uid=target_uid
    )
    warnings: list[str] = []
    if src_ambiguous:
        warnings.append(f"source '{source}' was ambiguous; top match used. Pass source_file/source_kind to narrow.")
    if tgt_ambiguous:
        warnings.append(f"target '{target}' was ambiguous; top match used. Pass target_file/target_kind to narrow.")
    if src_qn is None:
        return {
            "source": source,
            "target": target,
            "status": "source_not_found",
            "path": [],
            "hop_count": 0,
            "warnings": warnings,
            "source_candidates": src_candidates,
            "target_candidates": tgt_candidates,
            "compact_summary": {
                "source": source,
                "target": target,
                "status": "source_not_found",
                "hop_count": 0,
                "warnings": warnings,
            },
        }
    if tgt_qn is None:
        return {
            "source": source,
            "target": target,
            "status": "target_not_found",
            "path": [],
            "hop_count": 0,
            "warnings": warnings,
            "source_candidates": src_candidates,
            "target_candidates": tgt_candidates,
            "compact_summary": {
                "source": source,
                "target": target,
                "status": "target_not_found",
                "hop_count": 0,
                "warnings": warnings,
            },
        }
    if src_qn == tgt_qn:
        warnings.append(f"source '{source}' and target '{target}' resolved to the same node. Use a more specific name or file_path to disambiguate.")
        return {
            "source": source,
            "target": target,
            "resolved_source": src_qn,
            "resolved_target": tgt_qn,
            "status": "same_node",
            "path": [],
            "hop_count": 0,
            "warnings": warnings,
            "source_candidates": src_candidates,
            "target_candidates": tgt_candidates,
            "compact_summary": {
                "source": source,
                "target": target,
                "resolved_source": src_qn,
                "resolved_target": tgt_qn,
                "status": "same_node",
                "hop_count": 0,
                "warnings": warnings,
            },
        }
    # Strategy: try Cypher-native variable-length path first (450x faster
    # for dense graphs), fall back to Python BFS if Cypher returns nothing.
    path = _cypher_shortest_path(kuzu_store, src_qn, tgt_qn, relation_types, capped_hops)
    if path is None:
        path = _bfs_shortest_path(kuzu_store, src_qn, tgt_qn, relation_types, capped_hops)
    if path == "capped":
        warnings.append(
            f"Search was terminated early after visiting {MAX_NODES_VISITED} nodes. "
            "The graph is too dense around the source/target (likely a god-node). "
            "Try reducing max_hops, or use get_graph_neighborhood with mode='direct' for a focused view."
        )
        return {
            "source": source,
            "target": target,
            "resolved_source": src_qn,
            "resolved_target": tgt_qn,
            "status": "capped",
            "path": [],
            "hop_count": 0,
            "max_hops": capped_hops,
            "warnings": warnings,
            "source_candidates": src_candidates,
            "target_candidates": tgt_candidates,
            "compact_summary": {
                "source": source,
                "target": target,
                "resolved_source": src_qn,
                "resolved_target": tgt_qn,
                "status": "capped",
                "hop_count": 0,
                "max_hops": capped_hops,
                "warnings": warnings,
            },
        }
    if path is None:
        return {
            "source": source,
            "target": target,
            "resolved_source": src_qn,
            "resolved_target": tgt_qn,
            "status": "no_path",
            "path": [],
            "hop_count": 0,
            "max_hops": capped_hops,
            "warnings": warnings,
            "source_candidates": src_candidates,
            "target_candidates": tgt_candidates,
            "compact_summary": {
                "source": source,
                "target": target,
                "resolved_source": src_qn,
                "resolved_target": tgt_qn,
                "status": "no_path",
                "hop_count": 0,
                "max_hops": capped_hops,
                "warnings": warnings,
            },
        }
    return {
        "source": source,
        "target": target,
        "resolved_source": src_qn,
        "resolved_target": tgt_qn,
        "status": "found",
        "path": path,
        "hop_count": len(path),
        "max_hops": capped_hops,
        "warnings": warnings,
        "source_candidates": src_candidates,
        "target_candidates": tgt_candidates,
        "compact_summary": {
            "source": source,
            "target": target,
            "resolved_source": src_qn,
            "resolved_target": tgt_qn,
            "status": "found",
            "hop_count": len(path),
            "max_hops": capped_hops,
            "path": path,
            "warnings": warnings,
        },
    }
