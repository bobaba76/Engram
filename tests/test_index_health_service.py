from pathlib import Path

from services.index_health_service import index_health


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else (0,)

    def fetchall(self):
        return self._rows


class _Duck:
    def execute(self, query, params=None):
        text = str(query)
        if "COUNT(*)" in text:
            return _Rows([(0,)])
        return _Rows([])


def test_index_health_surfaces_native_build_context(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "services.index_health_service.summarize_native_build_context",
        lambda repo_root: {
            "confidence": "high",
            "build_systems": ["compile_commands", "cmake"],
            "compile_entry_count": 3,
            "targets": ["app"],
            "warnings": [],
        },
    )

    payload = index_health(tmp_path, _Duck())

    assert payload["native_build_context"]["confidence"] == "high"
    assert payload["compact_summary"]["native_build_context"] == {
        "confidence": "high",
        "build_systems": ["compile_commands", "cmake"],
        "compile_entry_count": 3,
        "targets": ["app"],
    }


def test_index_health_surfaces_graph_integrity_warnings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "services.index_health_service.summarize_native_build_context",
        lambda repo_root: {"confidence": "low", "warnings": []},
    )

    class _Kuzu:
        def graph_integrity_report(self):
            return {
                "ok": False,
                "symbols_missing_file_node": [{"qualified_name": "ghost", "file_path": "deleted.py"}],
                "symbols_missing_defines_edge": [],
            }

    payload = index_health(tmp_path, _Duck(), _Kuzu())

    assert payload["graph_integrity"]["ok"] is False
    assert payload["compact_summary"]["graph_integrity"]["symbols_missing_file_node_count"] == 1
    assert any("Graph integrity check found symbols" in warning for warning in payload["warnings"])


def test_index_health_surfaces_duckdb_snapshot_warning(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "services.index_health_service.summarize_native_build_context",
        lambda repo_root: {"confidence": "low", "warnings": []},
    )

    class _SnapshotDuck(_Duck):
        read_only_snapshot_metadata = {
            "active": True,
            "stale_read_risk": True,
            "copied_at": 123.0,
            "source_database_path": "primary.duckdb",
            "snapshot_database_path": "snapshot.duckdb",
        }

    payload = index_health(tmp_path, _SnapshotDuck())

    assert payload["duckdb_snapshot"]["active"] is True
    assert payload["compact_summary"]["duckdb_snapshot"]["stale_read_risk"] is True
    assert any("copied snapshot" in warning for warning in payload["warnings"])
