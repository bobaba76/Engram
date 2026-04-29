from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


def _count(duckdb_store: DuckDBStore, table: str) -> int:
    try:
        return int(duckdb_store.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except Exception:
        return 0


def _group_counts(duckdb_store: DuckDBStore, table: str, column: str, limit: int = 12) -> dict[str, int]:
    try:
        rows = duckdb_store.execute(
            f"SELECT {column}, COUNT(*) AS count FROM {table} GROUP BY {column} ORDER BY count DESC LIMIT ?",
            [limit],
        ).fetchall()
        return {str(row[0] or ""): int(row[1] or 0) for row in rows}
    except Exception:
        return {}


def index_health(repo_root: Path, duckdb_store: DuckDBStore, kuzu_store: KuzuStore | None = None) -> dict[str, object]:
    file_count = _count(duckdb_store, "files")
    symbol_count = _count(duckdb_store, "symbols")
    chunk_count = _count(duckdb_store, "chunks")
    finding_count = _count(duckdb_store, "findings")
    parser_counts = _group_counts(duckdb_store, "chunks", "parser_name")
    chunk_kind_counts = _group_counts(duckdb_store, "chunks", "chunk_kind")
    largest_chunks = []
    try:
        rows = duckdb_store.execute(
            """
            SELECT file_path, qualified_name, chunk_kind, start_line, end_line, length(content) AS content_length
            FROM chunks
            ORDER BY content_length DESC
            LIMIT 10
            """
        ).fetchall()
        largest_chunks = [
            {
                "file_path": row[0],
                "target": row[1],
                "chunk_kind": row[2],
                "start_line": row[3],
                "end_line": row[4],
                "content_length": row[5],
            }
            for row in rows
        ]
    except Exception:
        largest_chunks = []
    recent_runs = []
    try:
        rows = duckdb_store.execute(
            "SELECT run_id, run_mode, status, file_count, symbol_count, chunk_count, finding_count, stage_results_json FROM index_runs ORDER BY created_at DESC LIMIT 3"
        ).fetchall()
        for row in rows:
            stage_results = []
            try:
                stage_results = json.loads(row[7] or "[]")
            except json.JSONDecodeError:
                stage_results = []
            recent_runs.append(
                {
                    "run_id": row[0],
                    "run_mode": row[1],
                    "status": row[2],
                    "file_count": row[3],
                    "symbol_count": row[4],
                    "chunk_count": row[5],
                    "finding_count": row[6],
                    "stage_results": stage_results,
                }
            )
    except Exception:
        recent_runs = []
    warnings = []
    if file_count and chunk_count / max(file_count, 1) > 25:
        warnings.append("Chunk density is high; check oversized generated/test files.")
    if parser_counts.get("", 0):
        warnings.append("Some chunks have missing parser metadata.")
    if not recent_runs:
        warnings.append("No persisted index runs found.")
    return {
        "target": str(repo_root.resolve()),
        "counts": {
            "files": file_count,
            "symbols": symbol_count,
            "chunks": chunk_count,
            "findings": finding_count,
        },
        "parser_counts": parser_counts,
        "chunk_kind_counts": chunk_kind_counts,
        "largest_chunks": largest_chunks,
        "recent_runs": recent_runs,
        "warnings": warnings,
        "compact_summary": {
            "target": repo_root.name,
            "file_count": file_count,
            "symbol_count": symbol_count,
            "chunk_count": chunk_count,
            "finding_count": finding_count,
            "parser_counts": parser_counts,
            "top_files": [item.get("file_path", "") for item in largest_chunks[:5]],
            "warnings": warnings,
        },
    }
