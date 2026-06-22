"""Tests for storage/connection_manager.py — thread safety and connection handling."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from storage.connection_manager import DuckDBConnectionManager


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_conn.duckdb"


def test_write_mode_uses_shared_connection(db_path: Path) -> None:
    mgr = DuckDBConnectionManager(db_path, read_only=False)
    mgr.execute("CREATE TABLE t (x INTEGER)")
    mgr.execute("INSERT INTO t VALUES (1), (2), (3)")
    result = mgr.execute("SELECT COUNT(*) FROM t")
    assert result.fetchone()[0] == 3
    mgr.close()


def test_read_only_mode_creates_per_thread_connection(db_path: Path) -> None:
    # First, create and populate with a write connection
    writer = DuckDBConnectionManager(db_path, read_only=False)
    writer.execute("CREATE TABLE t (x INTEGER)")
    writer.execute("INSERT INTO t VALUES (10), (20)")
    writer.close()

    reader = DuckDBConnectionManager(db_path, read_only=True)
    result = reader.execute("SELECT SUM(x) FROM t")
    assert result.fetchone()[0] == 30
    reader.close()


def test_concurrent_writes_are_serialized(db_path: Path) -> None:
    mgr = DuckDBConnectionManager(db_path, read_only=False)
    mgr.execute("CREATE TABLE counter (n INTEGER)")
    mgr.execute("INSERT INTO counter VALUES (0)")

    errors: list[Exception] = []

    def increment():
        try:
            for _ in range(50):
                mgr.execute("UPDATE counter SET n = n + 1")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=increment) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    result = mgr.execute("SELECT n FROM counter")
    assert result.fetchone()[0] == 200
    mgr.close()


def test_concurrent_reads_in_read_only_mode(db_path: Path) -> None:
    writer = DuckDBConnectionManager(db_path, read_only=False)
    writer.execute("CREATE TABLE t (x INTEGER)")
    writer.executemany("INSERT INTO t VALUES (?)", [[i] for i in range(100)])
    writer.close()

    reader = DuckDBConnectionManager(db_path, read_only=True)
    results: list[int] = []
    lock = threading.Lock()

    def query_sum():
        result = reader.execute("SELECT SUM(x) FROM t")
        val = result.fetchone()[0]
        with lock:
            results.append(val)

    threads = [threading.Thread(target=query_sum) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    assert all(r == 4950 for r in results)
    reader.close()


def test_close_cleans_up_connections(db_path: Path) -> None:
    mgr = DuckDBConnectionManager(db_path, read_only=False)
    mgr.execute("CREATE TABLE t (x INTEGER)")
    mgr.close()

    # After close, executing should fail
    with pytest.raises(Exception):
        mgr.execute("SELECT 1")


def test_executemany_batch_insert(db_path: Path) -> None:
    mgr = DuckDBConnectionManager(db_path, read_only=False)
    mgr.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    mgr.executemany(
        "INSERT INTO t VALUES (?, ?)",
        [[1, "one"], [2, "two"], [3, "three"]],
    )
    result = mgr.execute("SELECT COUNT(*) FROM t")
    assert result.fetchone()[0] == 3
    mgr.close()


def test_read_only_thread_local_connections_are_independent(db_path: Path) -> None:
    writer = DuckDBConnectionManager(db_path, read_only=False)
    writer.execute("CREATE TABLE t (x INTEGER)")
    writer.execute("INSERT INTO t VALUES (42)")
    writer.close()

    reader = DuckDBConnectionManager(db_path, read_only=True)
    conn1 = reader.connection
    conn2 = reader.connection
    # Same thread should get same connection
    assert conn1 is conn2
    reader.close()
