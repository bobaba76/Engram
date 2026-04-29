from pathlib import Path

from mcp_server.resolvers import resolve_tool_target


class _Store:
    def fetch_symbol_by_uid(self, symbol_uid):
        return None

    def fetch_symbols_for_target(self, target, limit=25):
        return [
            {
                "file_path": "pkg/service.py",
                "name": "do_work",
                "qualified_name": "pkg.service.do_work",
                "kind": "function",
                "start_line": 10,
                "end_line": 12,
            }
        ]


def test_resolve_tool_target_reports_primary_match(tmp_path: Path) -> None:
    payload = resolve_tool_target(_Store(), tmp_path, target="do_work", limit=3)

    assert payload["status"] == "found"
    assert payload["confidence"] == "high"
    assert payload["partial"] is False
    assert payload["resolved_target"] == "pkg.service.do_work"
    assert payload["resolved_uid"] == "function:pkg/service.py:pkg.service.do_work"
    assert payload["compact_summary"]["match_count"] == 1
    assert payload["compact_summary"]["top_files"] == ["pkg/service.py"]
    assert payload["compact_summary"]["top_symbols"] == ["pkg.service.do_work"]
    assert payload["next_tools"][0]["tool"] == "get_source_context"
