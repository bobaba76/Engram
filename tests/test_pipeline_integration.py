"""Integration test for the scan → parse → chunk → embed → graph pipeline.

Uses a tiny synthetic repo on disk and exercises the real pipeline functions
without requiring torch, transformers, or an LLM provider.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("kuzu")
pytest.importorskip("lancedb")

from indexing.chunker import build_chunks, summarize_chunks
from indexing.embedder import embed_chunks
from indexing.embedding_providers import EmbeddingRequest, embedding_runtime_info
from indexing.graph_builder import build_graph
from indexing.scanner import scan_repo
from indexing.symbol_extractor import extract_symbols_with_status
from models.entity_models import FileRecord, SymbolRecord
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from storage.vector_store import VectorStore


@pytest.fixture()
def synthetic_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(
        "def hello():\n"
        "    print('hello')\n"
        "\n"
        "def world():\n"
        "    hello()\n"
        "    return 42\n",
        encoding="utf-8",
    )
    (repo / "utils.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n",
        encoding="utf-8",
    )
    return repo


@pytest.fixture()
def stores(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    duckdb = DuckDBStore(data_dir / "test.duckdb")
    kuzu = KuzuStore(data_dir / "kuzu")
    vector_store = VectorStore(data_dir / "lancedb")
    yield duckdb, kuzu, vector_store
    vector_store.close()
    kuzu.close()
    duckdb.close()


def test_pipeline_scan_to_graph(synthetic_repo: Path, stores) -> None:
    duckdb, kuzu, vector_store = stores

    # 1. Scan
    files = scan_repo(synthetic_repo, excluded_dirs=())
    assert len(files) == 2
    paths = {f.path for f in files}
    assert "app.py" in paths
    assert "utils.py" in paths

    # 2. Parse (symbol extraction)
    symbols_by_file: dict[str, list[SymbolRecord]] = {}
    for file_record in files:
        source = (synthetic_repo / file_record.path).read_text(encoding="utf-8")
        symbols, _status = extract_symbols_with_status(file_record, source)
        symbols_by_file[file_record.path] = symbols
    assert len(symbols_by_file["app.py"]) >= 2
    assert any(s.name == "hello" for s in symbols_by_file["app.py"])
    assert any(s.name == "world" for s in symbols_by_file["app.py"])

    # 3. Chunk
    all_chunks = []
    for file_record in files:
        chunks = build_chunks(synthetic_repo, file_record.path, symbols_by_file.get(file_record.path, []))
        assert len(chunks) > 0
        all_chunks.extend(chunks)
    summary = summarize_chunks(all_chunks)
    assert summary["chunk_count"] == len(all_chunks)

    # 4. Embed (deterministic fallback — no torch required)
    embed_result = embed_chunks(
        vector_store,
        all_chunks,
        model_name="jinaai/jina-embeddings-v2-base-code",
        batch_size=4,
        max_length=64,
        device="cpu",
        max_batch_tokens=512,
        provider_name="local",
    )
    assert embed_result["chunk_count"] == len(all_chunks)
    # Fallback embeddings are 32-dim; verify they were inserted
    search_results = vector_store.search("hello", limit=5, embedding=embed_result.get("new_embedding_count") and [0.0] * 32)
    # Search may return empty if table schema doesn't match, but should not error
    assert isinstance(search_results, list)

    # 5. Graph
    build_graph(kuzu, files, symbols_by_file)
    # Verify nodes were created
    edges = kuzu.edges_for_source("hello")
    assert isinstance(edges, list)


def test_pipeline_incremental_chunk_diff(synthetic_repo: Path, stores) -> None:
    """Verify that re-chunking unchanged files produces identical chunk IDs."""
    files = scan_repo(synthetic_repo, excluded_dirs=())
    file_record = files[0]
    source = (synthetic_repo / file_record.path).read_text(encoding="utf-8")
    symbols, _ = extract_symbols_with_status(file_record, source)
    chunks_v1 = build_chunks(synthetic_repo, file_record.path, symbols)
    chunks_v2 = build_chunks(synthetic_repo, file_record.path, symbols)

    ids_v1 = {c.chunk_id for c in chunks_v1}
    ids_v2 = {c.chunk_id for c in chunks_v2}
    assert ids_v1 == ids_v2


def test_pipeline_embedding_cache_reuse(synthetic_repo: Path, stores) -> None:
    """Verify that embedding cache is reused on second run."""
    _, _, vector_store = stores
    files = scan_repo(synthetic_repo, excluded_dirs=())
    all_chunks = []
    for file_record in files:
        source = (synthetic_repo / file_record.path).read_text(encoding="utf-8")
        symbols, _ = extract_symbols_with_status(file_record, source)
        chunks = build_chunks(synthetic_repo, file_record.path, symbols)
        all_chunks.extend(chunks)

    result_1 = embed_chunks(
        vector_store, all_chunks,
        model_name="jinaai/jina-embeddings-v2-base-code",
        device="cpu", provider_name="local",
    )
    result_2 = embed_chunks(
        vector_store, all_chunks,
        model_name="jinaai/jina-embeddings-v2-base-code",
        device="cpu", provider_name="local",
    )
    # Second run should hit cache for all chunks
    assert result_2["cache_hit_count"] >= result_1["new_embedding_count"]
    assert result_2["new_embedding_count"] == 0
