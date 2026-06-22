from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import lancedb
except ImportError:
    lancedb = None


DELETE_BATCH_SIZE = 50
VECTOR_DIMENSION_ERROR_MARKERS = ("FixedSizeList", "Cannot cast", "value at index 0 has length")


def _quote_lancedb_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _batched_file_path_predicates(file_paths: list[str], batch_size: int = DELETE_BATCH_SIZE) -> list[str]:
    predicates: list[str] = []
    for start in range(0, len(file_paths), batch_size):
        batch = file_paths[start:start + batch_size]
        if not batch:
            continue
        predicates.append(" OR ".join(f"file_path = {_quote_lancedb_string(file_path)}" for file_path in batch))
    return predicates


def _batched_chunk_id_predicates(chunk_ids: list[str], batch_size: int = DELETE_BATCH_SIZE) -> list[str]:
    predicates: list[str] = []
    for start in range(0, len(chunk_ids), batch_size):
        batch = chunk_ids[start:start + batch_size]
        if not batch:
            continue
        predicates.append(" OR ".join(f"chunk_id = {_quote_lancedb_string(chunk_id)}" for chunk_id in batch))
    return predicates


def _is_vector_dimension_error(exc: Exception) -> bool:
    message = str(exc)
    return all(marker in message for marker in VECTOR_DIMENSION_ERROR_MARKERS)


class VectorStore:
    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.data_path / "embedding_cache.json"
        self.cache_db_path = self.data_path / "embedding_cache.sqlite"
        self.embedding_cache: dict[str, list[float]] = {}
        self.cache_db: sqlite3.Connection | None = None
        self.db = lancedb.connect(str(self.data_path)) if lancedb is not None else None
        self.table = None
        if self.db is not None:
            table_names = set(self.db.table_names())
            if "chunks" in table_names:
                self.table = self.db.open_table("chunks")
        self._open_embedding_cache()

    def close(self) -> None:
        if self.cache_db is not None:
            self.cache_db.close()
            self.cache_db = None

    def _open_embedding_cache(self) -> None:
        try:
            self.cache_db = sqlite3.connect(str(self.cache_db_path))
            self.cache_db.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    content_hash TEXT PRIMARY KEY,
                    vector_json TEXT NOT NULL
                )
                """
            )
            self.cache_db.commit()
            self._migrate_legacy_embedding_cache()
        except sqlite3.Error:
            self.cache_db = None
            if self.cache_path.exists():
                try:
                    self.embedding_cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    self.embedding_cache = {}

    def _migrate_legacy_embedding_cache(self) -> None:
        if self.cache_db is None or not self.cache_path.exists():
            return
        try:
            legacy = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(legacy, dict):
            return
        rows = [
            (str(content_hash), json.dumps(vector))
            for content_hash, vector in legacy.items()
            if isinstance(vector, list)
        ]
        if rows:
            self.cache_db.executemany(
                "INSERT OR IGNORE INTO embedding_cache(content_hash, vector_json) VALUES (?, ?)",
                rows,
            )
            self.cache_db.commit()
        try:
            self.cache_path.unlink(missing_ok=True)
        except OSError:
            return

    def _clear_embedding_cache(self) -> None:
        self.embedding_cache = {}
        if self.cache_db is not None:
            try:
                self.cache_db.execute("DELETE FROM embedding_cache")
                self.cache_db.commit()
            except sqlite3.Error:
                logger.warning("vector_store: failed to clear embedding cache", exc_info=True)
        self.cache_path.unlink(missing_ok=True)

    def reset(self) -> None:
        if self.db is not None:
            table_names = set(self.db.table_names())
            if "chunks" in table_names:
                self.db.drop_table("chunks")
            self.table = None
        self._clear_embedding_cache()

    def get_cached_vectors(self, content_hashes: list[str]) -> dict[str, list[float]]:
        if self.cache_db is not None and content_hashes:
            cached: dict[str, list[float]] = {}
            unique_hashes = list(dict.fromkeys(content_hashes))
            for start in range(0, len(unique_hashes), 500):
                batch = unique_hashes[start:start + 500]
                placeholders = ", ".join("?" for _ in batch)
                try:
                    rows = self.cache_db.execute(
                        f"SELECT content_hash, vector_json FROM embedding_cache WHERE content_hash IN ({placeholders})",
                        batch,
                    ).fetchall()
                except sqlite3.Error:
                    logger.warning("vector_store: failed to read embedding cache batch", exc_info=True)
                    return {}
                for content_hash, vector_json in rows:
                    try:
                        vector = json.loads(vector_json)
                    except json.JSONDecodeError:
                        logger.debug("vector_store: corrupted cache entry for hash %s", content_hash, exc_info=True)
                        continue
                    if isinstance(vector, list):
                        cached[str(content_hash)] = vector
            return cached
        return {
            content_hash: self.embedding_cache[content_hash]
            for content_hash in content_hashes
            if content_hash in self.embedding_cache
        }

    def cache_embedding(self, content_hash: str, vector: list[float]) -> None:
        if self.cache_db is not None:
            try:
                self.cache_db.execute(
                    "INSERT OR IGNORE INTO embedding_cache(content_hash, vector_json) VALUES (?, ?)",
                    (content_hash, json.dumps(vector)),
                )
                self.cache_db.commit()
            except sqlite3.Error:
                logger.warning("vector_store: failed to store embedding in cache for hash %s", content_hash, exc_info=True)
            return
        if content_hash in self.embedding_cache:
            return
        self.embedding_cache[content_hash] = vector
        self.cache_path.write_text(json.dumps(self.embedding_cache), encoding="utf-8")

    def cache_embeddings(self, items: dict[str, list[float]]) -> None:
        if self.cache_db is not None:
            rows = [(content_hash, json.dumps(vector)) for content_hash, vector in items.items()]
            if rows:
                try:
                    self.cache_db.executemany(
                        "INSERT OR IGNORE INTO embedding_cache(content_hash, vector_json) VALUES (?, ?)",
                        rows,
                    )
                    self.cache_db.commit()
                except sqlite3.Error:
                    logger.warning("vector_store: failed to bulk store embeddings in cache", exc_info=True)
            return
        updated = False
        for content_hash, vector in items.items():
            if content_hash in self.embedding_cache:
                continue
            self.embedding_cache[content_hash] = vector
            updated = True
        if updated:
            self.cache_path.write_text(json.dumps(self.embedding_cache), encoding="utf-8")

    def delete_items_for_files(self, file_paths: list[str]) -> None:
        if not file_paths:
            return
        file_path_set = set(file_paths)
        if self.table is None:
            return
        for predicate in _batched_file_path_predicates(sorted(file_path_set)):
            self.table.delete(predicate)

    def delete_items_for_chunk_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        chunk_id_set = set(chunk_ids)
        if self.table is None:
            return
        for predicate in _batched_chunk_id_predicates(sorted(chunk_id_set)):
            self.table.delete(predicate)

    def add_item(self, item: dict[str, Any]) -> None:
        if self.db is None:
            return
        row = dict(item)
        vector = row.get("vector")
        if isinstance(vector, list) and len(vector) <= 64:
            logger.warning(
                "vector_store: inserting suspiciously small embedding (dim=%d) — "
                "this may be a deterministic fallback; semantic search quality will degrade",
                len(vector),
            )
        if self.table is None:
            self.table = self.db.create_table("chunks", data=[row], mode="overwrite")
        else:
            try:
                self.table.add([row])
            except ValueError as exc:
                if not _is_vector_dimension_error(exc):
                    raise
                self.db.drop_table("chunks")
                self.table = self.db.create_table("chunks", data=[row], mode="overwrite")
                self._clear_embedding_cache()

    def add_items(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        if self.db is None:
            return
        rows = [dict(item) for item in items]
        for row in rows:
            vector = row.get("vector")
            if isinstance(vector, list) and len(vector) <= 64:
                logger.warning(
                    "vector_store: inserting suspiciously small embedding (dim=%d) for chunk %s — "
                    "this may be a deterministic fallback; semantic search quality will degrade",
                    len(vector),
                    row.get("chunk_id", "?"),
                )
                break
        if self.table is None:
            self.table = self.db.create_table("chunks", data=rows, mode="overwrite")
        else:
            try:
                self.table.add(rows)
            except ValueError as exc:
                if not _is_vector_dimension_error(exc):
                    raise
                self.db.drop_table("chunks")
                self.table = self.db.create_table("chunks", data=rows, mode="overwrite")
                self._clear_embedding_cache()

    def search(self, task: str, limit: int = 5, embedding: list[float] | None = None) -> list[dict[str, Any]]:
        if self.db is not None and self.table is not None and embedding is not None:
            results = self.table.search(embedding).limit(limit).to_list()
            return [dict(row) for row in results]
        return []
