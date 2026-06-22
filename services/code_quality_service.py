from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from services.test_intelligence_service import _is_test_path

if TYPE_CHECKING:
    from pathlib import Path
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore
    from storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


def detect_duplicate_code(
    duckdb_store: DuckDBStore,
    vector_store: VectorStore,
    limit: int = 20,
    similarity_threshold: float = 0.85,
    max_chunks: int = 100,
    model_name: str = "jinaai/jina-embeddings-v2-base-code",
) -> dict[str, object]:
    """Detect duplicate or near-duplicate code using vector similarity.

    Samples chunks from the vector store, embeds each one, and searches for
    similar chunks above the similarity threshold. Returns pairs of similar
    chunks grouped by file.
    """
    from indexing.embeddings import embed_texts, is_model_ready, get_model_load_error

    if not is_model_ready(model_name):
        return {
            "status": "error",
            "error": f"Embedding model not ready: {get_model_load_error(model_name)}",
            "duplicate_pair_count": 0,
            "duplicates": [],
            "compact_summary": {
                "status": "error",
                "duplicate_pair_count": 0,
            },
        }

    # Fetch all chunks from DuckDB to get content for embedding
    all_chunks = duckdb_store.fetch_all("chunks")
    if not all_chunks:
        return {
            "status": "ok",
            "duplicate_pair_count": 0,
            "duplicates": [],
            "compact_summary": {
                "status": "ok",
                "duplicate_pair_count": 0,
            },
        }

    # Sample chunks to process (avoid O(n²) blowup)
    import random
    sample_size = min(len(all_chunks), max_chunks)
    sampled = random.sample(all_chunks, sample_size) if len(all_chunks) > sample_size else all_chunks

    # Embed sampled chunks
    texts = []
    chunk_meta = []
    for chunk in sampled:
        content = str(chunk.get("content", "") or chunk.get("text", "") or "")
        if not content.strip() or len(content.strip()) < 20:
            continue
        texts.append(content[:512])  # Truncate to avoid token limit
        chunk_meta.append(chunk)

    if not texts:
        return {
            "status": "ok",
            "duplicate_pair_count": 0,
            "duplicates": [],
            "compact_summary": {
                "status": "ok",
                "duplicate_pair_count": 0,
            },
        }

    # Embed the sampled chunks
    try:
        embeddings = embed_texts(texts, model_name=model_name, allow_fallback=True)
    except Exception as exc:
        return {
            "status": "error",
            "error": f"Embedding failed: {exc}",
            "duplicate_pair_count": 0,
            "duplicates": [],
            "compact_summary": {
                "status": "error",
                "duplicate_pair_count": 0,
            },
        }

    # For each embedded chunk, search the vector store for similar chunks
    duplicate_pairs: list[dict[str, object]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for i, (embedding, chunk) in enumerate(zip(embeddings, chunk_meta)):
        if embedding is None or len(embedding) == 0:
            continue
        chunk_id = str(chunk.get("chunk_id", "") or chunk.get("id", "") or f"chunk_{i}")
        chunk_file = str(chunk.get("file_path", "") or "")
        chunk_start = chunk.get("start_line")
        chunk_end = chunk.get("end_line")

        results = vector_store.search("", limit=5, embedding=embedding)
        for result in results:
            result_id = str(result.get("chunk_id", "") or result.get("id", "") or "")
            result_file = str(result.get("file_path", "") or "")
            result_start = result.get("start_line")
            result_end = result.get("end_line")
            score = float(result.get("_distance", 1.0))

            # Convert Lance distance to similarity (lower distance = higher similarity)
            similarity = 1.0 - score

            if similarity < similarity_threshold:
                continue
            if not result_id or result_id == chunk_id:
                continue
            if not result_file or result_file == chunk_file:
                continue  # Skip same-file duplicates

            # Dedupe pairs (A,B) == (B,A)
            pair_key = tuple(sorted([chunk_id, result_id]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            duplicate_pairs.append({
                "similarity": round(similarity, 3),
                "chunk_a": {
                    "file_path": chunk_file,
                    "start_line": chunk_start,
                    "end_line": chunk_end,
                    "chunk_id": chunk_id,
                },
                "chunk_b": {
                    "file_path": result_file,
                    "start_line": result_start,
                    "end_line": result_end,
                    "chunk_id": result_id,
                },
            })

    # Sort by similarity descending
    duplicate_pairs.sort(key=lambda p: p["similarity"], reverse=True)
    duplicate_pairs = duplicate_pairs[:limit]

    # Group by file pairs
    file_pairs: dict[str, int] = {}
    for pair in duplicate_pairs:
        files = tuple(sorted([pair["chunk_a"]["file_path"], pair["chunk_b"]["file_path"]]))
        key = f"{files[0]} <-> {files[1]}"
        file_pairs[key] = file_pairs.get(key, 0) + 1

    hotspot_pairs = sorted(file_pairs.items(), key=lambda x: x[1], reverse=True)

    return {
        "status": "ok",
        "duplicate_pair_count": len(duplicate_pairs),
        "similarity_threshold": similarity_threshold,
        "chunks_scanned": len(chunk_meta),
        "duplicates": duplicate_pairs,
        "hotspot_file_pairs": [{"files": key, "pair_count": count} for key, count in hotspot_pairs[:15]],
        "compact_summary": {
            "status": "ok",
            "duplicate_pair_count": len(duplicate_pairs),
            "similarity_threshold": similarity_threshold,
            "chunks_scanned": len(chunk_meta),
            "top_file_pairs": [key for key, _ in hotspot_pairs[:8]],
        },
    }


def test_coverage_gaps(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore | None = None,
    limit: int = 50,
) -> dict[str, object]:
    """Identify symbols and files with no associated test coverage.

    Cross-references all non-test symbols against test files to find
    untested code. Uses naming conventions and graph edges to map
    tests to source files.
    """
    all_symbols = duckdb_store.fetch_all("symbols")
    all_files = duckdb_store.files.fetch_all()

    if not all_symbols:
        return {
            "status": "ok",
            "untested_symbol_count": 0,
            "untested_file_count": 0,
            "compact_summary": {
                "status": "ok",
                "untested_symbol_count": 0,
                "untested_file_count": 0,
            },
        }

    # Separate test files from source files
    test_files: set[str] = set()
    source_files: set[str] = set()
    for file_row in all_files:
        path = str(file_row.get("path", "") or "")
        if not path:
            continue
        if _is_test_path(path):
            test_files.add(path)
        else:
            source_files.add(path)

    # Build a mapping: source file -> test files that reference it
    # Strategy: for each test file, find symbols it references via the graph,
    # and map those symbols back to source files.
    tested_source_files: set[str] = set()
    tested_symbols: set[str] = set()

    if kuzu_store is not None:
        # For each test file's symbols, find what they call/reference
        for test_file in test_files:
            test_syms = duckdb_store.fetch_symbols_for_file(test_file)
            for sym in test_syms:
                qn = str(sym.get("qualified_name", "") or "")
                if not qn:
                    continue
                # Find outgoing edges (what does this test reference?)
                for rel in ("CALLS", "REFERENCES", "IMPORTS", "USES_SERVICE", "INJECTS"):
                    outgoing = kuzu_store.edges_for_source(qn, relation=rel, limit=20)
                    for edge in outgoing:
                        tgt = str(edge.get("target", "") or "")
                        if tgt:
                            tested_symbols.add(tgt)

    # Also use naming conventions: test_foo.py -> foo.py, foo.test.ts -> foo.ts
    for test_file in test_files:
        normalized = test_file.replace("\\", "/")
        name = normalized.rsplit("/", 1)[-1]
        # Strip test markers
        base = name
        for marker in (".test.", ".tests.", ".spec.", "test_", "_test."):
            if marker in base:
                base = base.replace(marker, ".")
                break
        base = base.replace("test_", "").replace("_test", "")
        # Try to find a matching source file
        for src_file in source_files:
            src_normalized = src_file.replace("\\", "/")
            src_name = src_normalized.rsplit("/", 1)[-1]
            if src_name == base or src_name.rsplit(".", 1)[0] == base.rsplit(".", 1)[0]:
                tested_source_files.add(src_file)

    # Map tested symbols to their source files
    if kuzu_store is not None:
        for sym_qn in tested_symbols:
            sym_data = duckdb_store.fetch_symbols_for_target(sym_qn, limit=1)
            for s in sym_data:
                fp = str(s.get("file_path", "") or "")
                if fp and fp not in test_files:
                    tested_source_files.add(fp)

    # Find untested source files
    untested_files = sorted(source_files - tested_source_files)

    # Find untested symbols (non-test, not in tested_symbols)
    untested_symbols: list[dict[str, object]] = []
    for sym in all_symbols:
        qn = str(sym.get("qualified_name", "") or "")
        fp = str(sym.get("file_path", "") or "")
        if not qn or not fp:
            continue
        if _is_test_path(fp):
            continue
        if qn in tested_symbols:
            continue
        if fp in tested_source_files:
            # File is tested, but this specific symbol might not be
            # Still count it as potentially untested at the symbol level
            pass
        kind = str(sym.get("kind", "") or "")
        # Only count functions, classes, methods — not variables or imports
        if kind.lower() not in ("function", "class", "method", "async_function", "generator", "decorator"):
            continue
        untested_symbols.append({
            "qualified_name": qn,
            "name": str(sym.get("name", "") or ""),
            "kind": kind,
            "file_path": fp,
            "start_line": sym.get("start_line"),
        })

    untested_symbols.sort(key=lambda s: (s.get("file_path", ""), s.get("qualified_name", "")))

    # Group untested symbols by file
    untested_by_file: dict[str, list[str]] = {}
    for sym in untested_symbols:
        fp = sym.get("file_path", "")
        untested_by_file.setdefault(fp, []).append(sym["qualified_name"])

    file_gaps = sorted(
        [{"file_path": fp, "untested_count": len(syms), "symbols": syms[:5]} for fp, syms in untested_by_file.items()],
        key=lambda x: x["untested_count"],
        reverse=True,
    )

    total_source_files = len(source_files)
    untested_file_count = len(untested_files)
    untested_pct = (untested_file_count / total_source_files * 100) if total_source_files > 0 else 0.0

    return {
        "status": "ok",
        "total_source_files": total_source_files,
        "tested_file_count": total_source_files - untested_file_count,
        "untested_file_count": untested_file_count,
        "untested_file_percentage": round(untested_pct, 1),
        "untested_files": untested_files[:limit],
        "untested_symbol_count": len(untested_symbols),
        "untested_symbols": untested_symbols[:limit],
        "untested_by_file": file_gaps[:30],
        "test_file_count": len(test_files),
        "compact_summary": {
            "status": "ok",
            "total_source_files": total_source_files,
            "tested_file_count": total_source_files - untested_file_count,
            "untested_file_count": untested_file_count,
            "untested_file_percentage": round(untested_pct, 1),
            "untested_symbol_count": len(untested_symbols),
            "test_file_count": len(test_files),
            "top_untested_files": [item["file_path"] for item in file_gaps[:8]],
        },
    }
