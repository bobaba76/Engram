from __future__ import annotations

from storage.duckdb_store import DuckDBStore
from services.search_ranking import classify_confidence, score_symbol_relevance, summarize_relevance


def symbol_uid(file_path: str, qualified_name: str, kind: str) -> str:
    normalized_kind = str(kind or "symbol").strip().lower() or "symbol"
    return f"{normalized_kind}:{file_path}:{qualified_name}"


def attach_symbol_uid(symbol: dict[str, object]) -> dict[str, object]:
    enriched = dict(symbol)
    enriched["uid"] = symbol_uid(
        str(symbol.get("file_path", "")),
        str(symbol.get("qualified_name", "") or symbol.get("name", "")),
        str(symbol.get("kind", "")),
    )
    return enriched


def candidate_sort_key(item: dict[str, object]) -> tuple[float, int, int, str, str]:
    symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
    return (
        float(item.get("score", 0.0) or 0.0),
        int(item.get("file_match", 0) or 0),
        int(item.get("kind_match", 0) or 0),
        str(symbol.get("file_path", "")),
        str(symbol.get("qualified_name", "")),
    )


def resolve_candidates(
    duckdb_store: DuckDBStore,
    target: str = "",
    file_path: str | None = None,
    kind: str | None = None,
    symbol_uid_value: str | None = None,
    limit: int = 25,
) -> list[dict[str, object]]:
    normalized_file = str(file_path or "").replace("\\", "/").lower()
    normalized_kind = str(kind or "").strip().lower()
    candidates: list[dict[str, object]] = []
    if symbol_uid_value:
        direct = duckdb_store.fetch_symbol_by_uid(symbol_uid_value)
        if direct is not None:
            symbol = attach_symbol_uid(direct)
            score, reasons = score_symbol_relevance(
                target or str(symbol.get("name", "")),
                str(symbol.get("name", "")),
                str(symbol.get("qualified_name", "")),
                str(symbol.get("file_path", "")),
                str(symbol.get("kind", "")),
            )
            return [
                {
                    "score": score + 1.0,
                    "confidence": "high",
                    "relevance": "uid exact match" if not reasons else summarize_relevance(reasons),
                    "symbol": symbol,
                    "file_match": 1,
                    "kind_match": 1,
                }
            ]
    seed = target or ""
    for symbol in duckdb_store.fetch_symbols_for_target(seed, limit=max(limit * 4, 25)):
        enriched = attach_symbol_uid(symbol)
        score, reasons = score_symbol_relevance(
            seed,
            str(enriched.get("name", "")),
            str(enriched.get("qualified_name", "")),
            str(enriched.get("file_path", "")),
            str(enriched.get("kind", "")),
        )
        symbol_file = str(enriched.get("file_path", "")).replace("\\", "/").lower()
        symbol_kind = str(enriched.get("kind", "")).strip().lower()
        file_match = int(bool(normalized_file) and symbol_file == normalized_file)
        kind_match = int(bool(normalized_kind) and symbol_kind == normalized_kind)
        if symbol_uid_value and enriched.get("uid") == symbol_uid_value:
            score += 1.0
        score += 0.45 if file_match else 0.0
        score += 0.18 if kind_match else 0.0
        candidates.append(
            {
                "score": round(score, 4),
                "confidence": classify_confidence(score),
                "relevance": summarize_relevance(reasons),
                "symbol": enriched,
                "file_match": file_match,
                "kind_match": kind_match,
            }
        )
    deduped: dict[str, dict[str, object]] = {}
    for item in candidates:
        symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
        uid = str(symbol.get("uid", ""))
        if uid and (uid not in deduped or candidate_sort_key(item) > candidate_sort_key(deduped[uid])):
            deduped[uid] = item
    rows = sorted(deduped.values(), key=candidate_sort_key, reverse=True)
    return rows[:limit]


def ambiguity_status(candidates: list[dict[str, object]]) -> bool:
    if len(candidates) <= 1:
        return False
    first = float(candidates[0].get("score", 0.0) or 0.0)
    second = float(candidates[1].get("score", 0.0) or 0.0)
    return second >= first - 0.08
