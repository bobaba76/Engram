"""God-node / top-degree hub detection.

Surfaces the highest-fan-out symbols in the indexed graph in a single
call. Useful as a first-pass sanity check before deep traversals: a
god-node in the result set is a strong signal that a neighborhood query
against it will be noisy and should be filtered by relation or scoped to
``mode='direct'``.

The degree is computed from the union of inbound and outbound edges
across all symbol relations. ``COMMON_HUB_TOKENS`` from ``graph_service``
is reused so the penalty matches what neighborhood queries already use.
"""
from __future__ import annotations

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import SYMBOL_RELATIONS, KuzuStore

DEFAULT_LIMIT = 20
HARD_LIMIT = 100
# Minimum combined degree to be considered a god-node. Below this the
# symbol is just a normally-connected piece of the graph.
GOD_NODE_DEGREE_THRESHOLD = 40


def _bulk_degree(kuzu_store: KuzuStore) -> dict[str, dict[str, int]]:
    """Compute inbound/outbound/total degree for ALL symbols via Cypher aggregation.

    Uses one aggregation query per (relation, direction) instead of per-
    symbol queries. For a repo with ~2000 symbols and 19 relations, this
    reduces from ~76,000 queries to ~38 queries total.
    """
    degree: dict[str, dict[str, int]] = {}
    relations = ("DEFINES", *SYMBOL_RELATIONS)
    available = kuzu_store.available_relations()
    for rel in relations:
        if rel not in available:
            continue
        if rel == "DEFINES":
            # DEFINES is File->Symbol; only inbound makes sense for symbols.
            out_query = None
            in_query = "MATCH (f:File)-[:DEFINES]->(s:Symbol) RETURN s.qualified_name, COUNT(*)"
        else:
            out_query = f"MATCH (s1:Symbol)-[:{rel}]->(s2:Symbol) RETURN s1.qualified_name, COUNT(*)"
            in_query = f"MATCH (s1:Symbol)-[:{rel}]->(s2:Symbol) RETURN s2.qualified_name, COUNT(*)"
        if out_query:
            try:
                rows = kuzu_store._safe_execute(out_query).get_all()
            except RuntimeError:
                rows = []
            for row in rows:
                qn = str(row[0] or "").strip()
                if not qn:
                    continue
                entry = degree.setdefault(qn, {"inbound": 0, "outbound": 0, "total": 0})
                entry["outbound"] += int(row[1] or 0)
                entry["total"] = entry["inbound"] + entry["outbound"]
        try:
            rows = kuzu_store._safe_execute(in_query).get_all()
        except RuntimeError:
            rows = []
        for row in rows:
            qn = str(row[0] or "").strip()
            if not qn:
                continue
            entry = degree.setdefault(qn, {"inbound": 0, "outbound": 0, "total": 0})
            entry["inbound"] += int(row[1] or 0)
            entry["total"] = entry["inbound"] + entry["outbound"]
    return degree


def _hub_penalty(name: str) -> int:
    """Reuse the graph_service hub penalty so ranking matches neighborhood queries."""
    from services.graph_service import _hub_penalty as _ghp
    return _ghp(name)


def god_nodes(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    limit: int = DEFAULT_LIMIT,
    min_degree: int | None = None,
    include_files: bool = False,
) -> dict[str, object]:
    """Return the top-degree symbols in the indexed graph.

    Parameters
    ----------
    limit
        Maximum number of nodes to return. Capped at HARD_LIMIT.
    min_degree
        Optional override for the god-node threshold. Defaults to
        GOD_NODE_DEGREE_THRESHOLD. Nodes below the threshold are still
        returned in the ranking but flagged ``is_god_node=False``.
    include_files
        When True, also rank File nodes by DEFINES degree. Off by default
        because file-level hubs are usually less actionable than symbol
        hubs for blast-radius reasoning.
    """
    capped_limit = max(1, min(int(limit), HARD_LIMIT))
    threshold = int(min_degree) if min_degree is not None else GOD_NODE_DEGREE_THRESHOLD
    degree_map = _bulk_degree(kuzu_store)
    ranked: list[dict[str, object]] = []
    for qn, degree in degree_map.items():
        if degree["total"] == 0:
            continue
        ranked.append({
            "node": qn,
            "kind": "symbol",
            "inbound": degree["inbound"],
            "outbound": degree["outbound"],
            "total_degree": degree["total"],
            "hub_penalty": _hub_penalty(qn),
            "is_god_node": degree["total"] >= threshold,
        })
    ranked.sort(key=lambda item: (int(item["total_degree"]), -int(item["hub_penalty"])), reverse=True)
    top = ranked[:capped_limit]
    god_count = sum(1 for item in top if item["is_god_node"])
    file_hubs: list[dict[str, object]] = []
    if include_files:
        # File degree = number of DEFINES edges (one per defined symbol).
        file_rows = duckdb_store.execute(
            "SELECT file_path, COUNT(*) as sym_count FROM symbols GROUP BY file_path ORDER BY sym_count DESC LIMIT ?",
            [capped_limit],
        ).fetchall()
        for row in file_rows:
            file_hubs.append({
                "node": str(row[0] or ""),
                "kind": "file",
                "total_degree": int(row[1] or 0),
                "is_god_node": int(row[1] or 0) >= threshold,
            })
    warnings: list[str] = []
    if god_count > 0:
        warnings.append(
            f"{god_count} god-node(s) detected (degree >= {threshold}). "
            "Prefer relation filters or mode='direct' on neighborhood queries against these symbols."
        )
    return {
        "limit": capped_limit,
        "min_degree": threshold,
        "god_node_count": god_count,
        "god_node_threshold": threshold,
        "symbols": top,
        "file_hubs": file_hubs,
        "warnings": warnings,
        "compact_summary": {
            "god_node_count": god_count,
            "god_node_threshold": threshold,
            "top_symbols": [
                {"node": item["node"], "total_degree": item["total_degree"], "is_god_node": item["is_god_node"]}
                for item in top[:10]
            ],
            "warnings": warnings,
        },
    }
