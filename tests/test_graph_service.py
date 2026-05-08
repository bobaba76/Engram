from services.graph_service import get_callers_and_callees


class _Kuzu:
    def __init__(self):
        self.edges = [
            {"source": "ui.ProductView", "relation": "CALLS", "target": "services.products.loadProduct"},
            {"source": "services.products.loadProduct", "relation": "CALLS", "target": "repositories.products.fetchProduct"},
            {"source": "ui.ProductView", "relation": "IMPORTS", "target": "services.products.loadProduct"},
            {"source": "tests.products.test_loadProduct", "relation": "REFERENCES", "target": "services.products.loadProduct"},
            {"source": "services.products.loadProduct", "relation": "ASSOCIATED_WITH", "target": "services.products.loadProductImpl"},
        ]

    def edges_for_target(self, target, relation=None):
        return [
            edge
            for edge in self.edges
            if edge["target"] == target and (relation is None or edge["relation"] == relation)
        ]

    def edges_for_source(self, source, relation=None):
        return [
            edge
            for edge in self.edges
            if edge["source"] == source and (relation is None or edge["relation"] == relation)
        ]


def test_get_callers_and_callees_returns_categorized_references() -> None:
    payload = get_callers_and_callees(_Kuzu(), "services.products.loadProduct")

    assert payload["callers"] == [
        {"source": "ui.ProductView", "relation": "CALLS", "target": "services.products.loadProduct"}
    ]
    assert payload["callees"] == [
        {"source": "services.products.loadProduct", "relation": "CALLS", "target": "repositories.products.fetchProduct"}
    ]
    assert payload["relation_counts"]["IMPORTS"] == {"incoming": 1, "outgoing": 0}
    assert payload["relation_counts"]["REFERENCES"] == {"incoming": 1, "outgoing": 0}
    assert payload["relation_counts"]["ASSOCIATED_WITH"] == {"incoming": 0, "outgoing": 1}
    assert payload["related_symbols_by_relation"]["CALLS"] == ["repositories.products.fetchProduct", "ui.ProductView"]
    assert payload["compact_summary"]["all_related_symbol_count"] == 4
