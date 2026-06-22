import logging

from storage.vector_store import VectorStore
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from indexing.embedding_providers import EmbeddingRequest, build_embedding_provider, embedding_provider_name
from services.rerank_service import rerank_with_diversity
from services.search_ranking import compact_result_payload, rerank_search_results
from services.symbol_resolution_service import resolve_candidates

logger = logging.getLogger(__name__)


def _task_variants(task: str, limit: int = 6) -> list[str]:
    normalized = str(task or "").strip()
    if not normalized:
        return []
    variants: list[str] = [normalized]
    if limit <= 1:
        return variants[:1]
    try:
        from services.investigation_service import _query_rewrite, _question_intent

        rewrite = _query_rewrite(normalized, _question_intent(normalized))
        for field in ("rewritten_queries", "search_seeds"):
            values = rewrite.get(field, [])
            if not isinstance(values, list):
                continue
            for value in values:
                text = str(value or "").strip()
                if text and text not in variants:
                    variants.append(text)
                if len(variants) >= limit:
                    return variants
    except Exception:
        logger.warning("semantic_search: query rewrite failed for task %r", normalized, exc_info=True)
    return variants[:limit]


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
        if existing is None:
            merged = dict(result)
            source = merged.get("retrieval_source")
            merged["retrieval_sources"] = [source] if source else []
            deduped[key] = merged
            continue
        existing_sources = existing.setdefault("retrieval_sources", [])
        if not isinstance(existing_sources, list):
            existing_sources = [existing_sources]
            existing["retrieval_sources"] = existing_sources
        source = result.get("retrieval_source")
        if source and source not in existing_sources:
            existing_sources.append(source)
        existing["_distance"] = max(float(existing.get("_distance", 0.0) or 0.0), float(result.get("_distance", 0.0) or 0.0))
        for field in ("content", "graph_seed", "graph_relation", "graph_distance", "token_hits"):
            if not existing.get(field) and result.get(field):
                existing[field] = result[field]
    return list(deduped.values())


def _public_result_payload(result: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in result.items() if key != "vector"}


def _embedding_backend_label(provider_name: str, model_name: str, *, include_vector: bool) -> str:
    if not include_vector:
        normalized_provider = (provider_name or "local").strip().lower()
        if normalized_provider in {"openai", "openai-compatible"}:
            provider_label = "openai-compatible"
        elif str(model_name or "").startswith("jinaai/"):
            provider_label = "local-jina"
        else:
            provider_label = "deterministic-fallback"
        return f"{provider_label}:vector_skipped"
    return embedding_provider_name(provider_name, model_name)


def _extract_search_terms(task: str, results: list[dict[str, object]], limit: int = 12) -> list[str]:
    values: list[str] = [str(task or "").strip()]
    for result in results:
        for field in ("qualified_name", "symbol_name"):
            value = str(result.get(field, "") or "").strip()
            if value:
                values.append(value)
    expanded: list[str] = []
    seen: set[str] = set()
    for value in values:
        for candidate in (value, value.split(".")[-1] if "." in value else ""):
            normalized = str(candidate or "").strip()
            if len(normalized) < 3:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            expanded.append(normalized)
            if len(expanded) >= limit:
                return expanded
    return expanded


def _expanded_regex_candidates(
    duckdb_store: DuckDBStore | None,
    task: str,
    seed_results: list[dict[str, object]],
    limit: int,
) -> list[dict[str, object]]:
    if duckdb_store is None:
        return []
    candidates: list[dict[str, object]] = []
    for term in _extract_search_terms(task, seed_results, limit=max(limit * 2, 8)):
        for chunk in duckdb_store.search_chunks_content(term, limit=max(limit * 2, 8)):
            token_hits = int(chunk.get("token_hits", 1) or 1)
            candidates.append(
                {
                    "file_path": chunk["file_path"],
                    "symbol_name": chunk.get("symbol_name", ""),
                    "qualified_name": chunk.get("qualified_name", chunk.get("symbol_name", "")),
                    "chunk_kind": chunk.get("chunk_kind", "chunk"),
                    "start_line": chunk.get("start_line"),
                    "end_line": chunk.get("end_line"),
                    "content": chunk.get("content", ""),
                    "_distance": min(0.14 + (token_hits * 0.04), 0.36),
                    "retrieval_source": "regex_expanded",
                    "token_hits": token_hits,
                }
            )
    return _dedupe_results(candidates)


def _neighboring_chunk_candidates(
    duckdb_store: DuckDBStore | None,
    seed_results: list[dict[str, object]],
    limit: int,
    window_lines: int = 60,
) -> list[dict[str, object]]:
    if duckdb_store is None:
        return []
    candidates: list[dict[str, object]] = []
    for result in seed_results[: max(limit * 2, 10)]:
        file_path = str(result.get("file_path", "") or "").strip()
        if not file_path:
            continue
        start_line = int(result.get("start_line", 1) or 1)
        end_line = int(result.get("end_line", start_line) or start_line)
        window_start = max(1, start_line - window_lines)
        window_end = max(end_line, end_line + window_lines)
        for chunk in duckdb_store.fetch_chunks_for_file_range(file_path, start_line=window_start, end_line=window_end, limit=4):
            candidates.append(
                {
                    "file_path": chunk["file_path"],
                    "symbol_name": chunk.get("symbol_name", ""),
                    "qualified_name": chunk.get("qualified_name", chunk.get("symbol_name", "")),
                    "chunk_kind": chunk.get("chunk_kind", "chunk"),
                    "start_line": chunk.get("start_line"),
                    "end_line": chunk.get("end_line"),
                    "content": chunk.get("content", ""),
                    "_distance": 0.18,
                    "retrieval_source": "window",
                }
            )
    return _dedupe_results(candidates)


def _symbol_candidates(duckdb_store: DuckDBStore | None, task: str, limit: int) -> list[dict[str, object]]:
    if duckdb_store is None:
        return []
    candidate_limit = max(limit * 6, 30)
    candidates: list[dict[str, object]] = []
    for symbol in duckdb_store.fetch_symbols_for_target(task, limit=candidate_limit):
        candidates.append(
            {
                "file_path": symbol["file_path"],
                "symbol_name": symbol["name"],
                "qualified_name": symbol["qualified_name"],
                "chunk_kind": symbol.get("kind", "symbol"),
                "start_line": symbol.get("start_line"),
                "end_line": symbol.get("end_line"),
                "content": "",
                "_distance": 0.2,
                "retrieval_source": "symbol",
            }
        )
    return _dedupe_results(candidates)


def _chunk_candidates(duckdb_store: DuckDBStore | None, task: str, limit: int) -> list[dict[str, object]]:
    if duckdb_store is None:
        return []
    candidate_limit = max(limit * 6, 30)
    candidates: list[dict[str, object]] = []
    for chunk in duckdb_store.fetch_chunks_for_target(task, limit=candidate_limit):
        candidates.append(
            {
                "file_path": chunk["file_path"],
                "symbol_name": chunk.get("symbol_name", ""),
                "qualified_name": chunk.get("qualified_name", chunk.get("symbol_name", "")),
                "chunk_kind": chunk.get("chunk_kind", "chunk"),
                "start_line": chunk.get("start_line"),
                "end_line": chunk.get("end_line"),
                "content": chunk.get("content", ""),
                "_distance": 0.16,
                "retrieval_source": "chunk",
            }
        )
    return _dedupe_results(candidates)


def _regex_candidates(duckdb_store: DuckDBStore | None, task: str, limit: int) -> list[dict[str, object]]:
    if duckdb_store is None:
        return []
    candidates: list[dict[str, object]] = []
    for chunk in duckdb_store.search_chunks_content(task, limit=max(limit * 8, 40)):
        token_hits = int(chunk.get("token_hits", 1) or 1)
        candidates.append(
            {
                "file_path": chunk["file_path"],
                "symbol_name": chunk.get("symbol_name", ""),
                "qualified_name": chunk.get("qualified_name", chunk.get("symbol_name", "")),
                "chunk_kind": chunk.get("chunk_kind", "chunk"),
                "start_line": chunk.get("start_line"),
                "end_line": chunk.get("end_line"),
                "content": chunk.get("content", ""),
                "_distance": min(0.12 + (token_hits * 0.04), 0.34),
                "retrieval_source": "regex",
                "token_hits": token_hits,
            }
        )
    return _dedupe_results(candidates)


def _graph_candidates(duckdb_store: DuckDBStore | None, kuzu_store: KuzuStore | None, task: str, limit: int) -> list[dict[str, object]]:
    if duckdb_store is None or kuzu_store is None:
        return []
    candidates: list[dict[str, object]] = []
    resolved = resolve_candidates(duckdb_store, target=task, limit=3)
    seen_targets: set[str] = set()
    for item in resolved:
        symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
        target = str(symbol.get("qualified_name", "") if isinstance(symbol, dict) else "")
        if not target or target in seen_targets:
            continue
        seen_targets.add(target)
        edges = []
        for relation, edge_limit in (
            ("CALLS", 8),
            ("REFERENCES", 6),
            ("INCLUDES", 6),
            ("IMPORTS", 4),
            ("ACCESSES", 4),
            ("FETCHES", 6),
            ("READS_FIELD", 6),
            ("HAS_METHOD", 4),
            ("HAS_PROPERTY", 4),
            ("EXTENDS", 4),
            ("IMPLEMENTS", 4),
            ("METHOD_OVERRIDES", 4),
            ("METHOD_IMPLEMENTS", 4),
            ("DECLARES", 4),
            ("ASSOCIATED_WITH", 4),
        ):
            edges.extend(kuzu_store.edges_for_target(target, relation=relation)[:edge_limit])
            edges.extend(kuzu_store.edges_for_source(target, relation=relation)[:edge_limit])
        neighbors: dict[str, dict[str, object]] = {}
        for edge in edges:
            source = str(edge.get("source", ""))
            edge_target = str(edge.get("target", ""))
            relation = str(edge.get("relation", ""))
            neighbor = edge_target if source == target else source
            if not neighbor or neighbor == target:
                continue
            entry = neighbors.setdefault(neighbor, {"relations": set(), "edge_count": 0})
            entry["edge_count"] = int(entry["edge_count"]) + 1
            relations = entry["relations"]
            if isinstance(relations, set):
                relations.add(relation)
        ranked_neighbors = sorted(
            neighbors.items(),
            key=lambda item: (int(item[1].get("edge_count", 0)), "CALLS" in item[1].get("relations", set()), item[0]),
            reverse=True,
        )
        for neighbor, meta in ranked_neighbors[: max(limit * 4, 12)]:
            relations = meta.get("relations", set())
            primary_relation = sorted(relations)[0] if isinstance(relations, set) and relations else "RELATED"
            for symbol_row in duckdb_store.fetch_symbols_for_target(neighbor, limit=2):
                for chunk in duckdb_store.fetch_chunks_for_file_range(
                    str(symbol_row.get("file_path", "")),
                    int(symbol_row.get("start_line", 1) or 1),
                    int(symbol_row.get("end_line", symbol_row.get("start_line", 1)) or 1),
                    limit=1,
                ):
                    candidates.append(
                        {
                            "file_path": chunk["file_path"],
                            "symbol_name": chunk.get("symbol_name", symbol_row.get("name", "")),
                            "qualified_name": chunk.get("qualified_name", symbol_row.get("qualified_name", "")),
                            "chunk_kind": chunk.get("chunk_kind", symbol_row.get("kind", "symbol")),
                            "start_line": chunk.get("start_line"),
                            "end_line": chunk.get("end_line"),
                            "content": chunk.get("content", ""),
                            "_distance": 0.24,
                            "retrieval_source": "graph",
                            "graph_seed": target,
                            "graph_relation": primary_relation,
                            "graph_distance": 1,
                        }
                    )
    return _dedupe_results(candidates)


def semantic_code_search(
    vector_store: VectorStore,
    task: str,
    model_name: str,
    limit: int = 5,
    duckdb_store: DuckDBStore | None = None,
    kuzu_store: KuzuStore | None = None,
    max_length: int = 512,
    device: str = "cpu",
    provider_name: str = "local",
    api_key: str = "",
    base_url: str = "",
    max_variants: int = 6,
    include_vector: bool = True,
    include_graph: bool = True,
    include_expansion: bool = True,
    extra_query_terms: list[str] | None = None,
) -> dict[str, object]:
    request = None
    provider = None
    if include_vector:
        request = EmbeddingRequest(
            model_name=model_name,
            provider_name=provider_name,
            max_length=max_length,
            device=device,
            api_key=api_key,
            base_url=base_url,
        )
        provider = build_embedding_provider(provider_name, model_name)
    task_variants = _task_variants(task, limit=max(1, max_variants))
    lexical_terms: list[str] = []
    for candidate in [task, *(extra_query_terms or [])]:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in lexical_terms:
            lexical_terms.append(normalized)
    vector_results: list[dict[str, object]] = []
    symbol_results: list[dict[str, object]] = []
    chunk_results: list[dict[str, object]] = []
    regex_results: list[dict[str, object]] = []
    graph_results: list[dict[str, object]] = []
    for index, variant in enumerate(task_variants or [task]):
        if include_vector:
            assert provider is not None
            assert request is not None
            try:
                embedding = provider.embed([variant], request=request)[0]
            except Exception as exc:
                logger.warning("semantic_code_search: vector embedding failed for variant %r: %s", variant, exc)
                continue
            raw_results = vector_store.search(task=variant, limit=max(limit * 4, 20), embedding=embedding)
            vector_results.extend(
                {
                    **result,
                    "retrieval_source": result.get("retrieval_source", "vector") if index == 0 else f"vector_variant",
                }
                for result in raw_results
            )
        symbol_results.extend(_symbol_candidates(duckdb_store, variant, limit))
        chunk_results.extend(_chunk_candidates(duckdb_store, variant, limit))
        regex_results.extend(_regex_candidates(duckdb_store, variant, limit))
        if include_graph:
            graph_results.extend(_graph_candidates(duckdb_store, kuzu_store, variant, limit))
    for term in lexical_terms:
        if term in task_variants:
            continue
        symbol_results.extend(_symbol_candidates(duckdb_store, term, limit))
        chunk_results.extend(_chunk_candidates(duckdb_store, term, limit))
        regex_results.extend(_regex_candidates(duckdb_store, term, limit))
    vector_results = _dedupe_results(vector_results)
    symbol_results = _dedupe_results(symbol_results)
    chunk_results = _dedupe_results(chunk_results)
    regex_results = _dedupe_results(regex_results)
    graph_results = _dedupe_results(graph_results)
    expansion_seed_results = _dedupe_results([
        *vector_results[: max(limit * 2, 8)],
        *symbol_results[: max(limit, 4)],
        *chunk_results[: max(limit, 4)],
        *graph_results[: max(limit, 4)],
    ])
    expanded_regex_results = _expanded_regex_candidates(duckdb_store, task, expansion_seed_results, limit) if include_expansion else []
    window_results = _neighboring_chunk_candidates(duckdb_store, expansion_seed_results + expanded_regex_results, limit) if include_expansion else []
    hybrid_results = _dedupe_results(
        [
            *vector_results,
            *symbol_results,
            *chunk_results,
            *regex_results,
            *graph_results,
            *expanded_regex_results,
            *window_results,
        ]
    )
    results = rerank_with_diversity(task, hybrid_results, limit=limit, base_reranker=rerank_search_results)
    source_counts: dict[str, int] = {}
    for result in hybrid_results:
        sources = result.get("retrieval_sources", [result.get("retrieval_source", "unknown")])
        if not isinstance(sources, list):
            sources = [sources]
        for source in sources:
            source_text = str(source or "unknown")
            source_counts[source_text] = source_counts.get(source_text, 0) + 1
    backend_name = _embedding_backend_label(provider_name, model_name, include_vector=include_vector)

    return {
        "task": task,
        "embedding_backend": backend_name,
        "retrieval_diagnostics": {
            "query_variants": task_variants,
            "lexical_terms": lexical_terms,
            "variant_count": len(task_variants),
            "include_vector": include_vector,
            "include_graph": include_graph,
            "include_expansion": include_expansion,
            "vector_candidates": len(vector_results),
            "symbol_candidates": len(symbol_results),
            "chunk_candidates": len(chunk_results),
            "regex_candidates": len(regex_results),
            "graph_candidates": len(graph_results),
            "expanded_regex_candidates": len(expanded_regex_results),
            "window_candidates": len(window_results),
            "deduped_candidates": len(hybrid_results),
            "source_counts": source_counts,
        },
        "results": [_public_result_payload(result) for result in results],
        "compact_results": [compact_result_payload(result) for result in results],
    }
