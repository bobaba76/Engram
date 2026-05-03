from __future__ import annotations

from pathlib import Path
from threading import RLock, local
from typing import Any

import duckdb


class DuckDBConnectionManager:
    def __init__(self, database_path: Path, read_only: bool = False) -> None:
        self.database_path = database_path
        self.read_only = read_only
        self._lock = RLock()
        self._local = local()
        
        # The shared connection is used for writes (or fallback for single-threaded read-write)
        self.shared_connection = duckdb.connect(str(database_path), read_only=read_only)

    @property
    def connection(self):
        if not self.read_only:
            return self.shared_connection
        
        # For read-only mode, create a new connection per thread to allow true concurrency
        # and prevent cursor overlap issues when fetchall() is called outside the lock.
        if not hasattr(self._local, "conn"):
            self._local.conn = duckdb.connect(str(self.database_path), read_only=True)
        return self._local.conn

    def execute(self, query: str, parameters: list[Any] | tuple[Any, ...] | None = None):
        if not self.read_only:
            with self._lock:
                if parameters is None:
                    return self.shared_connection.execute(query)
                return self.shared_connection.execute(query, parameters)
        
        # Read-only path: thread-safe, no lock needed
        conn = self.connection
        if parameters is None:
            return conn.execute(query)
        return conn.execute(query, parameters)

    def executemany(self, query: str, parameters: list[list[Any]] | list[tuple[Any, ...]]):
        if not self.read_only:
            with self._lock:
                return self.shared_connection.executemany(query, parameters)
                
        # Read-only path: thread-safe, no lock needed
        conn = self.connection
        return conn.executemany(query, parameters)

    def close(self) -> None:
        close_shared = getattr(self.shared_connection, "close", None)
        if callable(close_shared):
            close_shared()
        # Thread-local connections will be cleaned up automatically by GC
