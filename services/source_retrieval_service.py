from storage.duckdb_store import DuckDBStore


def get_source_context(duckdb_store: DuckDBStore, target: str, limit: int = 5) -> dict[str, object]:
    symbol_matches = [
        {
            "file_path": symbol["file_path"],
            "name": symbol["name"],
            "qualified_name": symbol["qualified_name"],
            "kind": symbol["kind"],
            "start_line": symbol["start_line"],
            "end_line": symbol["end_line"],
        }
        for symbol in duckdb_store.fetch_symbols_for_target(target, limit=max(limit * 3, 15))
    ]
    results = duckdb_store.fetch_chunks_for_target(target, limit=limit)
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
