import re

from storage.duckdb_store import DuckDBStore
from services.search_ranking import compact_result_payload
from services.symbol_resolution_service import resolve_candidates, attach_symbol_uid, candidate_sort_key
from services.search_ranking import score_symbol_relevance, classify_confidence, summarize_relevance


def _fuzzy_symbol_search(
    duckdb_store: DuckDBStore,
    query: str,
    limit: int = 10,
    file_path: str | None = None,
    kind: str | None = None,
) -> list[dict[str, object]]:
    tokens = [t for t in re.split(r"[^a-zA-Z0-9_]+", query.lower()) if t]
    if len(tokens) < 2:
        return []
    candidates: dict[str, dict[str, object]] = {}
    for token in tokens:
        for symbol in duckdb_store.fetch_symbols_for_target(token, limit=max(limit * 4, 25)):
            enriched = attach_symbol_uid(symbol)
            uid = str(enriched.get("uid", ""))
            if not uid or uid in candidates:
                continue
            name = str(enriched.get("name", "")).lower()
            qualified = str(enriched.get("qualified_name", "")).lower()
            matched = sum(1 for token in tokens if token in name or token in qualified)
            if matched >= max(2, len(tokens) - 1):
                score, reasons = score_symbol_relevance(
                    query,
                    str(enriched.get("name", "")),
                    str(enriched.get("qualified_name", "")),
                    str(enriched.get("file_path", "")),
                    str(enriched.get("kind", "")),
                )
                candidates[uid] = {
                    "score": round(score, 4),
                    "confidence": classify_confidence(score),
                    "relevance": summarize_relevance(reasons) or "fuzzy token match",
                    "symbol": enriched,
                    "file_match": 0,
                    "kind_match": 0,
                }
    return sorted(candidates.values(), key=candidate_sort_key, reverse=True)[:limit]


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
    if not results and not symbol_uid:
        for item in _fuzzy_symbol_search(duckdb_store, query, limit=limit, file_path=file_path, kind=kind):
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
