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
