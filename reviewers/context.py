from __future__ import annotations

from pathlib import Path

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore



def build_review_context(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    file_path: Path,
    target: str,
) -> dict[str, object]:
    relative_path = str(target).replace('\\', '/')
    source_text = file_path.read_text(encoding="utf-8", errors="replace")
    symbols = [row for row in duckdb_store.fetch_all("symbols") if row["file_path"] == relative_path]
    chunks = duckdb_store.fetch_chunks_for_target(relative_path, limit=20)
    findings = duckdb_store.fetch_findings_for_target(relative_path)
    graph_context = {
        "dependencies": kuzu_store.edges_for_source(relative_path),
        "dependents": kuzu_store.edges_for_target(relative_path),
        "neighborhood": kuzu_store.neighborhood(relative_path, depth=1),
    }
    return {
        "file_path": relative_path,
        "absolute_path": str(file_path),
        "source_text": source_text,
        "symbols": symbols,
        "chunks": chunks,
        "prior_findings": findings,
        "graph_context": graph_context,
    }
