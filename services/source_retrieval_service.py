from storage.duckdb_store import DuckDBStore
from services.symbol_resolution_service import resolve_candidates, symbol_uid_from_target


def get_source_context(duckdb_store: DuckDBStore, target: str, limit: int = 5) -> dict[str, object]:
    resolved_symbol_uid = symbol_uid_from_target(target)
    lookup_target = str(target or "").strip()
    if resolved_symbol_uid and resolved_symbol_uid == lookup_target:
        lookup_target = ""
    resolved_candidates = resolve_candidates(duckdb_store, target=lookup_target, symbol_uid_value=resolved_symbol_uid, limit=max(limit * 3, 15))
    symbol_matches = []
    for item in resolved_candidates:
        symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
        symbol_matches.append(
            {
                "file_path": symbol.get("file_path", ""),
                "name": symbol.get("name", ""),
                "qualified_name": symbol.get("qualified_name", ""),
                "kind": symbol.get("kind", ""),
                "start_line": symbol.get("start_line"),
                "end_line": symbol.get("end_line"),
            }
        )

    results = duckdb_store.fetch_chunks_for_target(lookup_target or target, limit=limit)
    if not results:
        fallback_targets: list[str] = []
        for symbol in symbol_matches[:limit]:
            qualified_name = str(symbol.get("qualified_name", "") or "").strip()
            file_path = str(symbol.get("file_path", "") or "").strip()
            name = str(symbol.get("name", "") or "").strip()
            for value in (qualified_name, file_path, name):
                if value and value not in fallback_targets:
                    fallback_targets.append(value)
        for fallback_target in fallback_targets:
            results = duckdb_store.fetch_chunks_for_target(fallback_target, limit=limit)
            if results:
                break

    snippet_results = [
        {
            "file_path": chunk["file_path"],
            "target": chunk.get("qualified_name") or chunk.get("symbol_name") or chunk["file_path"],
            "chunk_kind": chunk.get("chunk_kind"),
            "start_line": chunk.get("start_line"),
            "end_line": chunk.get("end_line"),
            "content": chunk.get("content", ""),
            "preview": "\n".join(chunk.get("content", "").splitlines()[:12]),
        }
        for chunk in results
    ]
    return {
        "target": target,
        "symbol_matches": symbol_matches[:limit],
        "results": results,
        "snippet_results": snippet_results,
        "compact_results": [
            {
                "file": chunk["file_path"],
                "target": chunk.get("qualified_name") or chunk.get("symbol_name") or chunk["file_path"],
                "lines": [chunk.get("start_line"), chunk.get("end_line")],
                "chunk_kind": chunk.get("chunk_kind"),
            }
            for chunk in results
        ],
    }
