from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import lancedb
except ImportError:
    lancedb = None


DELETE_BATCH_SIZE = 50


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


class VectorStore:
    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.data_path / "embedding_cache.json"
        self.items: list[dict[str, Any]] | None = []
        self.embedding_cache: dict[str, list[float]] = {}
        self.db = lancedb.connect(str(self.data_path)) if lancedb is not None else None
        self.table = None
        if self.db is not None:
            self.items = None
            table_names = set(self.db.table_names())
            if "chunks" in table_names:
                self.table = self.db.open_table("chunks")
        if self.cache_path.exists():
            self.embedding_cache = json.loads(self.cache_path.read_text(encoding="utf-8"))

    def reset(self) -> None:
        if self.items is not None:
            self.items = []
        if self.db is not None:
            table_names = set(self.db.table_names())
            if "chunks" in table_names:
                self.db.drop_table("chunks")
            self.table = None
        self.embedding_cache = {}
        self.cache_path.unlink(missing_ok=True)

    def get_cached_vectors(self, content_hashes: list[str]) -> dict[str, list[float]]:
        return {
            content_hash: self.embedding_cache[content_hash]
            for content_hash in content_hashes
            if content_hash in self.embedding_cache
        }

    def cache_embedding(self, content_hash: str, vector: list[float]) -> None:
        if content_hash in self.embedding_cache:
            return
        self.embedding_cache[content_hash] = vector
        self.cache_path.write_text(json.dumps(self.embedding_cache), encoding="utf-8")

    def cache_embeddings(self, items: dict[str, list[float]]) -> None:
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
        if self.items is not None:
            self.items = [item for item in self.items if item.get("file_path") not in file_path_set]
        if self.table is None:
            return
        for predicate in _batched_file_path_predicates(sorted(file_path_set)):
            self.table.delete(predicate)

    def delete_items_for_chunk_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        chunk_id_set = set(chunk_ids)
        if self.items is not None:
            self.items = [item for item in self.items if item.get("chunk_id") not in chunk_id_set]
        if self.table is None:
            return
        for predicate in _batched_chunk_id_predicates(sorted(chunk_id_set)):
            self.table.delete(predicate)

    def add_item(self, item: dict[str, Any]) -> None:
        if self.items is not None:
            self.items.append(item)
        if self.db is None:
            return
        row = dict(item)
        if self.table is None:
            self.table = self.db.create_table("chunks", data=[row], mode="overwrite")
        else:
            self.table.add([row])

    def add_items(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        if self.items is not None:
            self.items.extend(items)
        if self.db is None:
            return
        rows = [dict(item) for item in items]
        if self.table is None:
            self.table = self.db.create_table("chunks", data=rows, mode="overwrite")
        else:
            self.table.add(rows)

    def search(self, task: str, limit: int = 5, embedding: list[float] | None = None) -> list[dict[str, Any]]:
        if self.db is not None and self.table is not None and embedding is not None:
            results = self.table.search(embedding).limit(limit).to_list()
            return [dict(row) for row in results]
        if self.items is None:
            return []
        lowered = task.lower()
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in self.items:
            haystack = f"{item.get('file_path', '')} {item.get('symbol_name', '')} {item.get('content', '')}".lower()
            score = sum(1 for token in lowered.split() if token in haystack)
            scored.append((score, item))
        scored.sort(key=lambda value: value[0], reverse=True)
        return [item for _, item in scored[:limit]]
