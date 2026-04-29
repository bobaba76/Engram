from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

import duckdb


class DuckDBConnectionManager:
    def __init__(self, database_path: Path, read_only: bool = False) -> None:
        self.database_path = database_path
        self.read_only = read_only
        self.connection = duckdb.connect(str(database_path), read_only=read_only)
        self._lock = RLock()

    def execute(self, query: str, parameters: list[Any] | tuple[Any, ...] | None = None):
        with self._lock:
            if parameters is None:
                return self.connection.execute(query)
            return self.connection.execute(query, parameters)

    def executemany(self, query: str, parameters: list[list[Any]] | list[tuple[Any, ...]]):
        with self._lock:
            return self.connection.executemany(query, parameters)

    def close(self) -> None:
        close = getattr(self.connection, "close", None)
        if callable(close):
            close()
