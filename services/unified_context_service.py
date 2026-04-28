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


def get_unified_context(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    target: str,
    max_matches: int = 5,
    neighborhood_depth: int = 1,
    file_path: str | None = None,
    kind: str | None = None,
    symbol_uid: str | None = None,
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
            "callers": [],
            "callees": [],
            "dependencies": {},
            "neighborhood": {},
            "compact_results": [],
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
    return {
        "target": target,
        "status": "ambiguous" if ambiguous else "found",
        "resolved_target": primary_target,
        "primary_match": primary_match,
        "warnings": ["Target resolution is ambiguous; pass file_path or kind to narrow it."] if ambiguous else [],
        "matches": top_matches,
        "callers": callers_and_callees.get("callers", []),
        "callees": callers_and_callees.get("callees", []),
        "dependencies": dependencies,
        "neighborhood": neighborhood,
        "compact_results": [compact_result_payload(result) for result in top_matches],
        "compact_summary": {
            "target": primary_target,
            "status": "ambiguous" if ambiguous else "found",
            "match_count": len(top_matches),
            "caller_count": len(callers_and_callees.get("callers", [])),
            "callee_count": len(callers_and_callees.get("callees", [])),
            "dependency_counts": _dependency_counts(dependencies),
            "top_neighbors": neighborhood.get("compact_summary", {}).get("top_neighbors", []),
            "top_matches": [result.get("qualified_name") or result.get("name") for result in top_matches[:5]],
        },
    }
