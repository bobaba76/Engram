from storage.duckdb_store import DuckDBStore
from services.search_ranking import classify_confidence, compact_result_payload, score_symbol_relevance, summarize_relevance


def find_symbols(duckdb_store: DuckDBStore, query: str, limit: int = 10) -> dict[str, object]:
    scored = []
    candidate_limit = max(limit * 5, 25)
    for symbol in duckdb_store.fetch_symbols_for_target(query, limit=candidate_limit):
        name = symbol["name"] or ""
        qualified_name = symbol["qualified_name"] or ""
        score, reasons = score_symbol_relevance(query, name, qualified_name, symbol["file_path"], symbol.get("kind", ""))
        scored.append(
            {
                "score": round(score, 4),
                "confidence": classify_confidence(score),
                "relevance": summarize_relevance(reasons),
                "file_path": symbol["file_path"],
                "name": name,
                "qualified_name": qualified_name,
                "kind": symbol["kind"],
                "start_line": symbol["start_line"],
                "end_line": symbol["end_line"],
            }
        )
    scored.sort(key=lambda item: (item["score"], item["qualified_name"]), reverse=True)
    results = scored[:limit]
    return {
        "query": query,
        "results": results,
        "compact_results": [compact_result_payload(result) for result in results],
    }
