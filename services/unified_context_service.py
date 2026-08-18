from __future__ import annotations

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from services.dependency_service import get_dependencies
from services.graph_service import get_callers_and_callees, get_graph_neighborhood_with_options
from services.search_ranking import compact_result_payload
from services.symbol_resolution_service import ambiguity_status, resolve_candidates, symbol_uid_from_target


def _dependency_counts(dependencies: dict[str, object]) -> dict[str, int]:
    compact_summary = dependencies.get("compact_summary", {}) if isinstance(dependencies, dict) else {}
    groups = compact_summary.get("groups", {}) if isinstance(compact_summary, dict) else {}
    counts: dict[str, int] = {}
    if isinstance(groups, dict):
        for name, value in groups.items():
            if isinstance(value, dict):
                counts[name] = int(value.get("count", 0) or 0)
    return counts


def _strip_categorized_internal_duplication(categorized: dict[str, object]) -> dict[str, object]:
    """Remove internal duplication fields from categorized_references.

    Each relation entry contains:
    - incoming/outgoing: full edge lists (keep)
    - top_incoming/top_outgoing: subsets of incoming/outgoing (remove)
    - _related_sources/_related_targets: deduped names from incoming/outgoing (remove)
    - incoming_count/outgoing_count: counts (keep, small)

    This removes ~5.6K bytes of pure duplication per response.
    """
    stripped: dict[str, object] = {}
    for rel, payload in categorized.items():
        if isinstance(payload, dict):
            clean = {k: v for k, v in payload.items() if k not in (
                "top_incoming", "top_outgoing", "_related_sources", "_related_targets"
            )}
            stripped[rel] = clean
        else:
            stripped[rel] = payload
    return stripped


def get_unified_context(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    target: str,
    max_matches: int = 5,
    neighborhood_depth: int = 1,
    file_path: str | None = None,
    kind: str | None = None,
    symbol_uid: str | None = None,
    compact: bool = True,
) -> dict[str, object]:
    top_matches = []
    resolved_symbol_uid = symbol_uid_from_target(target, symbol_uid)
    lookup_target = str(target or "").strip()
    if resolved_symbol_uid and resolved_symbol_uid == lookup_target:
        lookup_target = ""
    for item in resolve_candidates(
        duckdb_store,
        target=lookup_target,
        file_path=file_path,
        kind=kind,
        symbol_uid_value=resolved_symbol_uid,
        limit=max_matches,
    ):
        symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
        top_matches.append(
            {
                "score": round(float(item.get("score", 0.0) or 0.0), 4),
                "confidence": item.get("confidence", "low"),
                "relevance": item.get("relevance", ""),
                "uid": symbol.get("uid", ""),
                "file_path": symbol.get("file_path", ""),
                "name": symbol.get("name", ""),
                "qualified_name": symbol.get("qualified_name", ""),
                "kind": symbol.get("kind", ""),
                "start_line": symbol.get("start_line"),
                "end_line": symbol.get("end_line"),
            }
        )
    if not top_matches:
        return {
            "target": target,
            "status": "not_found",
            "resolved_target": target,
            "matches": [],
            "compact_summary": {
                "target": target,
                "status": "not_found",
                "match_count": 0,
            },
        }
    primary_match = top_matches[0]
    ambiguous = ambiguity_status(top_matches)
    primary_target = primary_match["qualified_name"]
    callers_and_callees = get_callers_and_callees(kuzu_store, primary_target)
    dependencies = get_dependencies(kuzu_store, primary_target)
    neighborhood = get_graph_neighborhood_with_options(
        kuzu_store,
        target=primary_target,
        depth=neighborhood_depth,
        relation="CALLS",
        mode="focused",
        max_edges=24,
        suppress_common_hubs=True,
    )
    raw_categorized = callers_and_callees.get("categorized_references", {})
    # Filter out empty relation categories to reduce output noise
    filtered_categorized = {
        rel: payload for rel, payload in raw_categorized.items()
        if isinstance(payload, dict) and (payload.get("incoming_count", 0) or payload.get("outgoing_count", 0))
    } if isinstance(raw_categorized, dict) else raw_categorized
    # Strip internal duplication (top_incoming, _related_sources, etc.)
    filtered_categorized = _strip_categorized_internal_duplication(filtered_categorized)

    result: dict[str, object] = {
        "target": target,
        "status": "ambiguous" if ambiguous else "found",
        "resolved_target": primary_target,
        "warnings": ["Target resolution is ambiguous; pass file_path or kind to narrow it."] if ambiguous else [],
        "matches": top_matches,
        "categorized_references": filtered_categorized,
        "relation_counts": callers_and_callees.get("relation_counts", {}),
        "dependencies": dependencies,
        "neighborhood": neighborhood,
        "compact_summary": {
            "target": primary_target,
            "status": "ambiguous" if ambiguous else "found",
            "match_count": len(top_matches),
            "caller_count": len(callers_and_callees.get("callers", [])),
            "callee_count": len(callers_and_callees.get("callees", [])),
            "relation_counts": callers_and_callees.get("relation_counts", {}),
            "dependency_counts": _dependency_counts(dependencies),
            "top_neighbors": neighborhood.get("compact_summary", {}).get("top_neighbors", []),
            "top_matches": [result.get("qualified_name") or result.get("name") for result in top_matches[:5]],
        },
    }

    if compact:
        # Strip nested compact_summary from neighborhood and dependencies.
        # These sub-objects each carry their own compact_summary that
        # duplicates their top-level fields (hub_summary, edges, inbound, etc.).
        # The unified compact_summary above already extracts the key counts
        # and top items, so the nested ones are pure overhead (~19.8K bytes).
        if isinstance(result.get("neighborhood"), dict) and "compact_summary" in result["neighborhood"]:
            result["neighborhood"] = {k: v for k, v in result["neighborhood"].items() if k != "compact_summary"}
        if isinstance(result.get("dependencies"), dict) and "compact_summary" in result["dependencies"]:
            result["dependencies"] = {k: v for k, v in result["dependencies"].items() if k != "compact_summary"}

    if not compact:
        # Full mode: include the redundant convenience fields that duplicate
        # categorized_references. These are kept for backward compatibility
        # but are not needed by the model — categorized_references already
        # contains all caller/callee data.
        result["primary_match"] = primary_match
        result["callers"] = callers_and_callees.get("callers", [])
        result["callees"] = callers_and_callees.get("callees", [])
        result["compact_results"] = [compact_result_payload(r) for r in top_matches]
        raw_related = callers_and_callees.get("related_symbols_by_relation", {})
        result["related_symbols_by_relation"] = {
            rel: symbols for rel, symbols in raw_related.items()
            if isinstance(symbols, list) and len(symbols) > 0
        } if isinstance(raw_related, dict) else raw_related

    return result
