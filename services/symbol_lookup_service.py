from storage.duckdb_store import DuckDBStore
from services.search_ranking import compact_result_payload
from services.symbol_resolution_service import resolve_candidates


def find_symbols(
    duckdb_store: DuckDBStore,
    query: str,
    limit: int = 10,
    file_path: str | None = None,
    kind: str | None = None,
    symbol_uid: str | None = None,
) -> dict[str, object]:
    results = []
    for item in resolve_candidates(duckdb_store, target=query, file_path=file_path, kind=kind, symbol_uid_value=symbol_uid, limit=limit):
        symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
        results.append(
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
    return {
        "query": query,
        "results": results,
        "compact_results": [compact_result_payload(result) for result in results],
    }
