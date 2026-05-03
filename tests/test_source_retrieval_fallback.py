from pathlib import Path

from services.source_retrieval_service import get_source_context


class _Chunks:
    def __init__(self):
        self.calls = []

    def fetch_for_target(self, target, limit=5):
        self.calls.append(("target", target))
        return []

    def fetch_for_file_range(self, file_path, start_line=None, end_line=None, limit=5):
        self.calls.append(("range", file_path, start_line, end_line))
        return []


class _Store:
    chunks = _Chunks()

    def fetch_symbol_by_uid(self, symbol_uid):
        return None

    def fetch_symbols_for_target(self, target, limit=25):
        return [
            {
                "file_path": "pkg/service.py",
                "name": "do_work",
                "qualified_name": "pkg.service.do_work",
                "kind": "function",
                "start_line": 3,
                "end_line": 4,
            }
        ]


def test_source_context_falls_back_to_direct_file_snippet(tmp_path: Path) -> None:
    source_file = tmp_path / "pkg" / "service.py"
    source_file.parent.mkdir()
    source_file.write_text("import x\n\n" "def do_work():\n" "    return x.value\n", encoding="utf-8")

    payload = get_source_context(_Store(), "do_work", limit=3, repo_root=tmp_path)

    assert payload["snippet_results"]
    snippet = payload["snippet_results"][0]
    assert snippet["retrieval_source"] == "direct_file_fallback"
    assert snippet["file_path"] == "pkg/service.py"
    assert "def do_work" in snippet["content"]
    assert payload["compact_results"][0]["retrieval_source"] == "direct_file_fallback"


class _ExactChunks(_Chunks):
    def fetch_for_file_range(self, file_path, start_line=None, end_line=None, limit=5):
        self.calls.append(("range", file_path, start_line, end_line))
        return [
            {
                "file_path": file_path,
                "qualified_name": "pkg.service.do_work",
                "symbol_name": "do_work",
                "chunk_kind": "function",
                "start_line": start_line,
                "end_line": end_line,
                "content": "def do_work():\n    return x.value\n",
            }
        ]


class _ExactStore(_Store):
    chunks = _ExactChunks()


def test_source_context_prefers_symbol_file_range_before_costly_target_scan(tmp_path: Path) -> None:
    source_file = tmp_path / "pkg" / "service.py"
    source_file.parent.mkdir()
    source_file.write_text("import x\n\n" "def do_work():\n" "    return x.value\n", encoding="utf-8")

    payload = get_source_context(_ExactStore(), "do_work", limit=3, repo_root=tmp_path)

    assert payload["snippet_results"]
    assert payload["snippet_results"][0]["retrieval_source"] == "chunk_index"
    assert _ExactStore.chunks.calls == [("range", "pkg/service.py", 3, 4)]
