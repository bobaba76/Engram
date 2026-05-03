from services.symbol_context_service import get_symbol_context


class _Store:
    pass


def test_get_symbol_context_uses_resolved_candidates(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.symbol_context_service.resolve_candidates",
        lambda duckdb_store, target="", symbol_uid_value=None, limit=12: [
            {
                "score": 1.25,
                "confidence": "high",
                "relevance": "exact symbol match",
                "symbol": {
                    "file_path": "backend/utils/database.py",
                    "name": "build_period_filter",
                    "qualified_name": "QueryBuilder.build_period_filter",
                    "kind": "method",
                    "start_line": 449,
                    "end_line": 518,
                },
            }
        ],
    )

    payload = get_symbol_context(duckdb_store=_Store(), target="QueryBuilder.build_period_filter")

    assert payload["status"] == "found"
    assert payload["matches"][0]["qualified_name"] == "QueryBuilder.build_period_filter"
    assert payload["compact_summary"]["top_files"] == ["backend/utils/database.py"]
