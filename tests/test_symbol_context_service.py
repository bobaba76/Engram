from services.symbol_context_service import get_symbol_context


class _Store:
    def fetch_symbols_for_target(self, target, limit=1):
        rows = {
            "components.ProductTrendModal.ProductTrendModal": {
                "file_path": "frontend/src/components/ProductTrendModal.tsx",
                "name": "ProductTrendModal",
                "qualified_name": "components.ProductTrendModal.ProductTrendModal",
                "kind": "component",
            }
        }
        return [rows[target]] if target in rows else []


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


class _Kuzu:
    edges = [
        {"source": "Caller", "relation": "CALLS", "target": "QueryBuilder.build_period_filter"},
        {"source": "Importer", "relation": "IMPORTS", "target": "QueryBuilder.build_period_filter"},
    ]

    def edges_for_target(self, target, relation=None):
        return [edge for edge in self.edges if edge["target"] == target and (relation is None or edge["relation"] == relation)]

    def edges_for_source(self, source, relation=None):
        return [edge for edge in self.edges if edge["source"] == source and (relation is None or edge["relation"] == relation)]


def test_get_symbol_context_includes_graph_context_when_kuzu_store_is_available(monkeypatch) -> None:
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

    payload = get_symbol_context(duckdb_store=_Store(), kuzu_store=_Kuzu(), target="QueryBuilder.build_period_filter")

    assert payload["relation_counts"]["CALLS"] == {"incoming": 1, "outgoing": 0}
    assert payload["relation_counts"]["IMPORTS"] == {"incoming": 1, "outgoing": 0}
    assert payload["compact_summary"]["caller_count"] == 1


class _FieldKuzu:
    def edges_for_target(self, target, relation=None):
        if target == "field:chart_data[].intransit_stock" and relation == "READS_FIELD":
            return [
                {
                    "source": "components.ProductTrendModal.ProductTrendModal",
                    "relation": "READS_FIELD",
                    "target": target,
                }
            ]
        return []


def test_get_symbol_context_can_resolve_field_readers_from_graph() -> None:
    payload = get_symbol_context(
        duckdb_store=_Store(),
        kuzu_store=_FieldKuzu(),
        target="chart_data[].intransit_stock",
    )

    assert payload["status"] == "found"
    assert payload["resolved_graph_target"] == "field:chart_data[].intransit_stock"
    assert payload["field_readers"][0]["qualified_name"] == "components.ProductTrendModal.ProductTrendModal"
    assert payload["compact_summary"]["reader_count"] == 1
