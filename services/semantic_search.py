from storage.vector_store import VectorStore
from storage.duckdb_store import DuckDBStore
from indexing.embeddings import embed_texts, embedding_backend_name
from services.search_ranking import compact_result_payload, rerank_search_results


def _dedupe_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: dict[tuple[object, object, object, object], dict[str, object]] = {}
    for result in results:
        key = (
            result.get("file_path"),
            result.get("qualified_name") or result.get("symbol_name"),
            result.get("start_line"),
            result.get("end_line"),
        )
        existing = deduped.get(key)
        if existing is None or float(result.get("_distance", 0.0) or 0.0) > float(existing.get("_distance", 0.0) or 0.0):
            deduped[key] = result
    return list(deduped.values())


def _fallback_candidates(duckdb_store: DuckDBStore | None, task: str, limit: int) -> list[dict[str, object]]:
    if duckdb_store is None:
        return []
    candidate_limit = max(limit * 6, 30)
    fallback: list[dict[str, object]] = []
    for symbol in duckdb_store.fetch_symbols_for_target(task, limit=candidate_limit):
        fallback.append(
            {
                "file_path": symbol["file_path"],
                "symbol_name": symbol["name"],
                "qualified_name": symbol["qualified_name"],
                "chunk_kind": symbol.get("kind", "symbol"),
                "start_line": symbol.get("start_line"),
                "end_line": symbol.get("end_line"),
                "content": "",
                "_distance": 0.18,
                "retrieval_source": "symbol_fallback",
            }
        )
    for chunk in duckdb_store.fetch_chunks_for_target(task, limit=candidate_limit):
        fallback.append(
            {
                "file_path": chunk["file_path"],
                "symbol_name": chunk.get("symbol_name", ""),
                "qualified_name": chunk.get("qualified_name", chunk.get("symbol_name", "")),
                "chunk_kind": chunk.get("chunk_kind", "chunk"),
                "start_line": chunk.get("start_line"),
                "end_line": chunk.get("end_line"),
                "content": chunk.get("content", ""),
                "_distance": 0.16,
                "retrieval_source": "chunk_fallback",
            }
        )
    return _dedupe_results(fallback)


def semantic_code_search(vector_store: VectorStore, task: str, model_name: str, limit: int = 5, duckdb_store: DuckDBStore | None = None) -> dict[str, object]:
    embedding = embed_texts([task], model_name=model_name)[0]
    raw_results = vector_store.search(task=task, limit=max(limit * 4, 20), embedding=embedding)
    hybrid_results = _dedupe_results([*raw_results, *_fallback_candidates(duckdb_store, task, limit)])
    results = rerank_search_results(task, hybrid_results, limit=limit)
    return {
        "task": task,
        "embedding_backend": embedding_backend_name(model_name),
        "results": results,
        "compact_results": [compact_result_payload(result) for result in results],
    }
