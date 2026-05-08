from services.unified_context_service import get_unified_context


class _Duck:
    pass


class _Kuzu:
    edges = [
        {"source": "ui.ProductView", "relation": "CALLS", "target": "services.products.loadProduct"},
        {"source": "services.products.loadProduct", "relation": "CALLS", "target": "repositories.products.fetchProduct"},
        {"source": "ui.ProductView", "relation": "IMPORTS", "target": "services.products.loadProduct"},
    ]

    def edges_for_target(self, target, relation=None):
        return [edge for edge in self.edges if edge["target"] == target and (relation is None or edge["relation"] == relation)]

    def edges_for_source(self, source, relation=None):
        return [edge for edge in self.edges if edge["source"] == source and (relation is None or edge["relation"] == relation)]

    def neighborhood(self, target, depth=1):
        return {"target": target, "depth": depth, "nodes": [target], "edges": []}


def test_unified_context_exposes_categorized_graph_references(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.unified_context_service.resolve_candidates",
        lambda duckdb_store, target="", file_path=None, kind=None, symbol_uid_value=None, limit=5: [
            {
                "score": 1.0,
                "confidence": "high",
                "relevance": "exact",
                "symbol": {
                    "uid": "sym-1",
                    "file_path": "services/products.py",
                    "name": "loadProduct",
                    "qualified_name": "services.products.loadProduct",
                    "kind": "Function",
                    "start_line": 1,
                    "end_line": 4,
                },
            }
        ],
    )
    monkeypatch.setattr("services.unified_context_service.get_dependencies", lambda kuzu_store, target: {"compact_summary": {"groups": {}}})

    payload = get_unified_context(_Duck(), _Kuzu(), "loadProduct")

    assert payload["relation_counts"]["CALLS"] == {"incoming": 1, "outgoing": 1}
    assert payload["relation_counts"]["IMPORTS"] == {"incoming": 1, "outgoing": 0}
    assert payload["categorized_references"]["CALLS"]["incoming_count"] == 1
    assert payload["compact_summary"]["relation_counts"]["CALLS"] == {"incoming": 1, "outgoing": 1}
