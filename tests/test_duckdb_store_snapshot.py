import shutil

import duckdb

from storage import duckdb_store
from storage.duckdb_store import DuckDBStore


def test_duckdb_read_only_lock_fallback_records_snapshot_metadata(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "index.duckdb"
    database_path.write_bytes(b"placeholder")
    calls = {"count": 0}

    class _Manager:
        def __init__(self, path, read_only=False):
            calls["count"] += 1
            if calls["count"] == 1:
                raise duckdb.IOException("locked")
            self.path = path
            self.read_only = read_only

        @property
        def connection(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(duckdb_store, "DuckDBConnectionManager", _Manager)
    monkeypatch.setattr(shutil, "copy2", lambda source, target: target.write_bytes(database_path.read_bytes()))

    store = DuckDBStore(database_path, read_only=True)

    assert calls["count"] == 2
    assert store.read_only_snapshot_metadata["active"] is True
    assert store.read_only_snapshot_metadata["stale_read_risk"] is True
    assert store.read_only_snapshot_metadata["source_database_path"] == str(database_path)
    assert str(store._temp_database_path).endswith("index.duckdb")
