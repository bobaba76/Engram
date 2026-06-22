from services.graph_service import get_callers_and_callees, get_graph_neighborhood_with_options


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

    def neighborhood(self, target, depth=1):
        nodes = {target}
        edges = []
        for edge in self.edges:
            if edge["source"] == target or edge["target"] == target:
                edges.append(edge)
                nodes.add(edge["source"])
                nodes.add(edge["target"])
        return {"nodes": sorted(nodes), "edges": edges}


def test_get_callers_and_callees_returns_categorized_references() -> None:
    payload = get_callers_and_callees(_Kuzu(), "services.products.loadProduct")

    assert payload["callers"] == [
        {"source": "ui.ProductView", "relation": "CALLS", "target": "services.products.loadProduct"}
    ]
    assert payload["callees"] == [
        {"source": "services.products.loadProduct", "relation": "CALLS", "target": "repositories.products.fetchProduct"}
    ]
    assert "IMPORTS" not in payload["relation_counts"]
    assert payload["relation_counts"]["REFERENCES"] == {"incoming": 1, "outgoing": 0}
    assert payload["relation_counts"]["ASSOCIATED_WITH"] == {"incoming": 0, "outgoing": 1}
    assert payload["related_symbols_by_relation"]["CALLS"] == ["repositories.products.fetchProduct", "ui.ProductView"]
    assert payload["compact_summary"]["all_related_symbol_count"] == 4


def test_graph_neighborhood_returns_hub_summary_for_broad_targets() -> None:
    kuzu = _Kuzu()
    kuzu.edges = [
        {"source": f"ui.Component{i}", "relation": "READS_FIELD", "target": "data"}
        for i in range(90)
    ] + [
        {"source": "services.products.loadProduct", "relation": "CALLS", "target": "data"},
        {"source": "data", "relation": "FETCHES", "target": "/products/trends"},
    ]

    payload = get_graph_neighborhood_with_options(kuzu, "data", max_edges=12)
    summary = payload["hub_summary"]

    assert payload["partial"] is True
    assert summary["is_hub"] is True
    assert summary["raw_edge_count"] == 92
    assert summary["filtered_edge_count"] == 12
    assert summary["truncated_edge_count"] == 80
    assert summary["relation_counts"]["READS_FIELD"] == 90
    assert payload["compact_summary"]["warnings"][0].startswith("This target behaves like a graph hub")
