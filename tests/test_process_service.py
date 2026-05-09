from services.process_service import trace_execution_flows


class _CSharpDuck:
    rows = {
        "MyApp.ProductsController.GetTrend": {"qualified_name": "MyApp.ProductsController.GetTrend", "name": "GetTrend", "file_path": "Controllers/ProductsController.cs", "kind": "method"},
        "MyApp.IProductService": {"qualified_name": "MyApp.IProductService", "name": "IProductService", "file_path": "Services/IProductService.cs", "kind": "interface"},
        "MyApp.ProductService": {"qualified_name": "MyApp.ProductService", "name": "ProductService", "file_path": "Services/ProductService.cs", "kind": "class"},
        "MyApp.ProductService.GetTrend": {"qualified_name": "MyApp.ProductService.GetTrend", "name": "GetTrend", "file_path": "Services/ProductService.cs", "kind": "method"},
    }

    def fetch_symbols_for_target(self, target, limit=25):
        return [self.rows[target]] if target in self.rows else []


class _CSharpKuzu:
    def edges_for_target(self, target, relation=None):
        return []

    def edges_for_source(self, source, relation=None):
        edges = {
            ("MyApp.ProductsController.GetTrend", "USES_SERVICE"): [
                {"source": source, "relation": "USES_SERVICE", "target": "MyApp.IProductService"}
            ],
            ("MyApp.IProductService", "INJECTS"): [
                {"source": source, "relation": "INJECTS", "target": "MyApp.ProductService"}
            ],
            ("MyApp.ProductService", "CALLS"): [
                {"source": source, "relation": "CALLS", "target": "MyApp.ProductService.GetTrend"}
            ],
        }
        return edges.get((source, relation), [])


def test_trace_execution_flows_follows_csharp_di_service_edges() -> None:
    payload = trace_execution_flows(
        _CSharpDuck(),
        _CSharpKuzu(),
        target="MyApp.ProductsController.GetTrend",
        max_depth=4,
        max_flows=4,
    )

    assert payload["flows"][0]["symbols"] == [
        "MyApp.ProductsController.GetTrend",
        "MyApp.IProductService",
        "MyApp.ProductService",
        "MyApp.ProductService.GetTrend",
    ]


class _Duck:
    rows = {
        "route_handler": {"qualified_name": "route_handler", "name": "route_handler", "file_path": "backend/routers/products.py", "kind": "function"},
        "service_step": {"qualified_name": "service_step", "name": "service_step", "file_path": "backend/services/products.py", "kind": "function"},
        "repository_step": {"qualified_name": "repository_step", "name": "repository_step", "file_path": "backend/repositories/products.py", "kind": "function"},
    }

    def fetch_symbols_for_target(self, target, limit=25):
        return [self.rows[target]] if target in self.rows else []


class _Kuzu:
    def edges_for_target(self, target, relation=None):
        return []

    def edges_for_source(self, source, relation=None):
        edges = {
            "route_handler": [
                {"source": "route_handler", "relation": "CALLS", "target": "max"},
                {"source": "route_handler", "relation": "CALLS", "target": "service_step"},
            ],
            "service_step": [
                {"source": "service_step", "relation": "CALLS", "target": "values"},
                {"source": "service_step", "relation": "CALLS", "target": "repository_step"},
            ],
        }
        return edges.get(source, []) if relation == "CALLS" else []


def test_trace_execution_flows_prefers_project_paths_over_generic_terminals() -> None:
    payload = trace_execution_flows(_Duck(), _Kuzu(), target="route_handler", max_depth=2, max_flows=2)

    assert payload["flows"][0]["symbols"] == ["route_handler", "service_step", "repository_step"]
    assert payload["flows"][0]["name"] == "backend: route_handler -> repository_step"
    assert payload["flows"][0]["terminal_symbol"] == "repository_step"
    assert payload["flows"][0]["files"] == [
        "backend/routers/products.py",
        "backend/services/products.py",
        "backend/repositories/products.py",
    ]
    assert payload["flows"][0]["changed_symbols"] == []
    assert payload["flows"][0]["step_details"][0]["changed"] is False
    assert payload["flows"][0]["step_details"][0]["file"] == "backend/routers/products.py"
    assert payload["flows"][0]["risk"] == "LOW"
    assert payload["compact_summary"]["top_flows"][0]["entry_symbol"] == "route_handler"
    assert payload["compact_summary"]["top_flows"][0]["terminal_symbol"] == "repository_step"
    assert payload["compact_summary"]["top_files"] == [
        "backend/routers/products.py",
        "backend/services/products.py",
        "backend/repositories/products.py",
    ]
    assert payload["compact_summary"]["top_symbols"][:3] == ["route_handler", "service_step", "repository_step"]
    assert payload["compact_summary"]["route_context"] == ["backend/routers/products.py"]


class _EntryDuck:
    rows = {
        "get_product_trend_data": {"qualified_name": "get_product_trend_data", "name": "get_product_trend_data", "file_path": "backend/services/product_trends.py", "kind": "function"},
        "get_product_trends": {"qualified_name": "get_product_trends", "name": "get_product_trends", "file_path": "backend/routers/products.py", "kind": "function"},
        "get_pricelist_sold_out_report": {"qualified_name": "get_pricelist_sold_out_report", "name": "get_pricelist_sold_out_report", "file_path": "backend/routers/export.py", "kind": "function"},
        "test_get_product_trend_data": {"qualified_name": "test_get_product_trend_data", "name": "test_get_product_trend_data", "file_path": "backend/tests/test_product_trends.py", "kind": "function"},
        "repo_step": {"qualified_name": "repo_step", "name": "repo_step", "file_path": "backend/repositories/products.py", "kind": "function"},
    }

    def fetch_symbols_for_target(self, target, limit=25):
        return [self.rows[target]] if target in self.rows else []


class _EntryKuzu:
    def edges_for_target(self, target, relation=None):
        if relation == "CALLS" and target == "get_product_trend_data":
            return [
                {"source": "get_pricelist_sold_out_report", "relation": "CALLS", "target": target},
                {"source": "test_get_product_trend_data", "relation": "CALLS", "target": target},
                {"source": "get_product_trends", "relation": "CALLS", "target": target},
            ]
        return []

    def edges_for_source(self, source, relation=None):
        if relation == "CALLS" and source in {"get_product_trends", "get_pricelist_sold_out_report", "test_get_product_trend_data"}:
            return [
                {"source": source, "relation": "CALLS", "target": "unrelated_helper"},
                {"source": source, "relation": "CALLS", "target": "get_product_trend_data"},
            ]
        if relation == "CALLS" and source == "get_product_trend_data":
            return [{"source": source, "relation": "CALLS", "target": "repo_step"}]
        return []


def test_trace_execution_flows_prefers_route_entrypoints_over_report_and_tests() -> None:
    payload = trace_execution_flows(
        _EntryDuck(),
        _EntryKuzu(),
        target="get_product_trend_data",
        file_path="backend/services/product_trends.py",
        max_depth=2,
        max_flows=3,
    )

    assert payload["entrypoints"][0] == "get_product_trends"
    assert payload["flows"][0]["entry_symbol"] == "get_product_trends"
    assert all("get_product_trend_data" in flow["symbols"] for flow in payload["flows"])


def test_trace_execution_flows_overlays_explicit_changed_symbols() -> None:
    payload = trace_execution_flows(
        _EntryDuck(),
        _EntryKuzu(),
        target="get_product_trend_data",
        file_path="backend/services/product_trends.py",
        max_depth=2,
        max_flows=1,
        changed_symbols=["repo_step"],
    )

    assert payload["flows"][0]["changed_symbols"] == ["repo_step"]
    assert payload["flows"][0]["step_details"][-1]["changed"] is True
    assert payload["flows"][0]["risk"] == "MEDIUM"
    assert payload["compact_summary"]["highest_risk"] == "MEDIUM"
