from __future__ import annotations

from typing import TYPE_CHECKING

from services.graph_service import _normalize_graph_target, _symbol_to_file_map
from services.symbol_resolution_service import resolve_candidates

if TYPE_CHECKING:
    from pathlib import Path
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


DATA_FLOW_RELATIONS = (
    "READS_FIELD",
    "ACCESSES",
    "FETCHES",
    "REFERENCES",
    "HAS_PROPERTY",
    "HAS_METHOD",
    "EXTENDS",
    "IMPLEMENTS",
    "ASSOCIATED_WITH",
    "DECLARES",
)


def _field_matches(candidate: str, requested: str) -> bool:
    candidate = str(candidate or "").strip()
    requested = str(requested or "").strip()
    if not candidate or not requested:
        return False
    return (
        candidate == requested
        or candidate.endswith("." + requested)
        or requested.endswith("." + candidate)
        or requested in candidate
        or candidate in requested
    )


def trace_data_flow(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    field: str,
    target: str = "",
    max_depth: int = 3,
    limit: int = 30,
) -> dict[str, object]:
    """Trace how a field or type propagates through the codebase.

    Starting from *target* (a symbol or type name), follows data-flow relations
    (READS_FIELD, ACCESSES, FETCHES, REFERENCES, HAS_PROPERTY, EXTENDS, etc.)
    to find all symbols that read, write, transform, or carry the *field*.

    If *target* is empty, searches by field name across all symbols.
    """
    requested_field = str(field or "").strip()
    if not requested_field:
        return {
            "field": "",
            "status": "error",
            "error": "field parameter is required",
        }

    # Phase 1: Find seed symbols — either from the target or by searching for the field name
    seed_symbols: list[str] = []
    if target:
        resolved_target = _normalize_graph_target(target)
        seed_symbols.append(resolved_target)
        # Also resolve via DuckDB for broader matches
        candidates = resolve_candidates(duckdb_store, target=target, limit=5)
        for item in candidates if isinstance(candidates, list) else []:
            sym = item.get("symbol", {}) if isinstance(item, dict) else {}
            qn = str(sym.get("qualified_name", "") or "").strip()
            if qn and qn not in seed_symbols:
                seed_symbols.append(qn)
    else:
        # Search by field name in symbols
        candidates = resolve_candidates(duckdb_store, target=requested_field, limit=5)
        for item in candidates if isinstance(candidates, list) else []:
            sym = item.get("symbol", {}) if isinstance(item, dict) else {}
            qn = str(sym.get("qualified_name", "") or "").strip()
            if qn:
                seed_symbols.append(qn)

    if not seed_symbols:
        return {
            "field": requested_field,
            "status": "not_found",
            "seed_symbols": [],
            "flows": [],
            "compact_summary": {
                "field": requested_field,
                "status": "not_found",
                "flow_count": 0,
            },
        }

    # Phase 2: BFS through data-flow relations up to max_depth
    visited: set[str] = set()
    all_edges: list[dict[str, object]] = []
    frontier: set[str] = set(seed_symbols)
    max_frontier = 15
    max_edges_per_relation = 10

    for depth in range(max_depth):
        next_frontier: set[str] = set()
        for node in frontier:
            if node in visited:
                continue
            visited.add(node)
            for rel in DATA_FLOW_RELATIONS:
                incoming = kuzu_store.edges_for_target(node, relation=rel, limit=max_edges_per_relation)
                outgoing = kuzu_store.edges_for_source(node, relation=rel, limit=max_edges_per_relation)
                for edge in (incoming + outgoing)[:max_edges_per_relation * 2]:
                    edge_with_depth = dict(edge)
                    edge_with_depth["_depth"] = depth + 1
                    all_edges.append(edge_with_depth)
                    # Add connected nodes to next frontier
                    src = str(edge.get("source", "") or "")
                    tgt = str(edge.get("target", "") or "")
                    if src and src not in visited:
                        next_frontier.add(src)
                    if tgt and tgt not in visited:
                        next_frontier.add(tgt)
        # Cap frontier to prevent explosion
        frontier = set(list(next_frontier)[:max_frontier])
        if not frontier:
            break

    # Phase 3: Filter edges to those involving the requested field
    field_edges: list[dict[str, object]] = []
    for edge in all_edges:
        src = str(edge.get("source", "") or "")
        tgt = str(edge.get("target", "") or "")
        rel = str(edge.get("relation", "") or "")
        # Check if the field name appears in source, target, or relation
        if _field_matches(src, requested_field) or _field_matches(tgt, requested_field):
            field_edges.append(edge)
            continue
        # Also check if any symbol name contains the field as a substring
        if requested_field.lower() in src.lower() or requested_field.lower() in tgt.lower():
            field_edges.append(edge)

    # If no field-specific edges found, keep all edges (the field might be
    # embedded in the symbol structure rather than explicitly named)
    if not field_edges:
        field_edges = all_edges

    # Phase 4: Map symbols to files and build flow chains
    all_symbols: set[str] = set()
    for edge in field_edges:
        all_symbols.add(str(edge.get("source", "") or ""))
        all_symbols.add(str(edge.get("target", "") or ""))
    all_symbols.discard("")

    sym_to_file = _symbol_to_file_map(duckdb_store, all_symbols)

    # Group edges by relation
    by_relation: dict[str, list[dict[str, object]]] = {}
    for edge in field_edges:
        rel = str(edge.get("relation", "UNKNOWN") or "UNKNOWN")
        by_relation.setdefault(rel, []).append(edge)

    # Build flow entries
    flows: list[dict[str, object]] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for edge in field_edges:
        src = str(edge.get("source", "") or "")
        tgt = str(edge.get("target", "") or "")
        rel = str(edge.get("relation", "") or "")
        depth = int(edge.get("_depth", 0) or 0)
        key = (src, tgt, rel)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        flows.append({
            "source": src,
            "target": tgt,
            "relation": rel,
            "depth": depth,
            "source_file": sym_to_file.get(src, ""),
            "target_file": sym_to_file.get(tgt, ""),
        })
        if len(flows) >= limit:
            break

    # Collect involved files
    involved_files: dict[str, int] = {}
    for flow in flows:
        for fp in (flow.get("source_file", ""), flow.get("target_file", "")):
            fp = str(fp or "")
            if fp:
                involved_files[fp] = involved_files.get(fp, 0) + 1

    sorted_files = sorted(involved_files.items(), key=lambda x: x[1], reverse=True)

    relation_counts = {rel: len(edges) for rel, edges in by_relation.items()}

    return {
        "field": requested_field,
        "target": target or "",
        "status": "ok",
        "seed_symbols": seed_symbols[:10],
        "flow_count": len(flows),
        "flows": flows,
        "involved_files": [{"file_path": fp, "flow_count": count} for fp, count in sorted_files[:20]],
        "relation_counts": dict(sorted(relation_counts.items())),
        "unresolved_symbols": sorted(all_symbols - set(sym_to_file.keys()))[:20],
        "compact_summary": {
            "field": requested_field,
            "target": target or "",
            "status": "ok",
            "seed_symbol_count": len(seed_symbols),
            "flow_count": len(flows),
            "involved_file_count": len(involved_files),
            "top_involved_files": [fp for fp, _ in sorted_files[:8]],
            "relation_counts": dict(sorted(relation_counts.items())),
        },
    }
