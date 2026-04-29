from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass(slots=True)
class TreeCacheEntry:
    tree: Any
    modified_time_ns: int
    size_bytes: int
    language: str


class TreeCache:
    def __init__(self, max_entries: int = 512) -> None:
        self.max_entries = max(max_entries, 1)
        self._items: OrderedDict[str, TreeCacheEntry] = OrderedDict()
        self._lock = RLock()

    def get(self, file_path: Path, language: str) -> Any | None:
        try:
            stat = file_path.stat()
        except OSError:
            return None
        key = str(file_path.resolve())
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            if entry.language != language or entry.modified_time_ns != stat.st_mtime_ns or entry.size_bytes != stat.st_size:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return entry.tree

    def put(self, file_path: Path, language: str, tree: Any) -> None:
        if tree is None:
            return
        try:
            stat = file_path.stat()
        except OSError:
            return
        key = str(file_path.resolve())
        with self._lock:
            self._items[key] = TreeCacheEntry(
                tree=tree,
                modified_time_ns=stat.st_mtime_ns,
                size_bytes=stat.st_size,
                language=language,
            )
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


DEFAULT_TREE_CACHE = TreeCache()


def parse_with_cache(file_path: Path, language: str, parser: Any, source_bytes: bytes) -> Any:
    cached = DEFAULT_TREE_CACHE.get(file_path, language)
    if cached is not None:
        return cached
    tree = parser.parse(source_bytes)
    DEFAULT_TREE_CACHE.put(file_path, language, tree)
    return tree
