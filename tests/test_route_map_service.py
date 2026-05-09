from pathlib import Path

from services.route_map_service import route_map


class _FilesRepo:
    def fetch_all(self):
        return [{"path": "src/page.tsx"}]


class _Store:
    files = _FilesRepo()

    def fetch_symbols_for_file(self, file_path):
        return [{"qualified_name": "page.component"}]


def test_route_map_uses_indexed_files_before_repo_walk(tmp_path: Path) -> None:
    indexed = tmp_path / "src" / "page.tsx"
    indexed.parent.mkdir()
    indexed.write_text("const apiClient = { get: () => null };\napiClient.get('/api/regional/company-overview')\n", encoding="utf-8")

    noisy = tmp_path / "node_modules" / "pkg" / "noise.js"
    noisy.parent.mkdir(parents=True)
    noisy.write_text("fetch('/api/regional/company-overview')\n", encoding="utf-8")

    payload = route_map(tmp_path, _Store(), route="/api/regional/company-overview")

    assert payload["total"] == 1
    route_payload = payload["routes"][0]
    assert [consumer["file_path"] for consumer in route_payload["consumers"]] == ["src/page.tsx"]



def test_route_map_normalizes_api_prefix_and_reports_consumer_metadata(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'product_code': 'A', 'metrics': {'intransit_stock': 1}, 'chart_data': []}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "services" / "api.ts"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const getProductTrends = async () => {\n"
        "  const response = await axios.get('/api/products/trends')\n"
        "  return response.data.metrics.intransit_stock\n"
        "}\n",
        encoding="utf-8",
    )

    class _FilesRepoWithRoutes:
        def fetch_all(self):
            return [{"path": "backend/routers/products.py"}, {"path": "frontend/src/services/api.ts"}]

    class _StoreWithRoutes(_Store):
        files = _FilesRepoWithRoutes()

    payload = route_map(tmp_path, _StoreWithRoutes(), route="products/trends")

    assert payload["total"] == 1
    route_payload = payload["routes"][0]
    assert route_payload["route"] == "/products/trends"
    assert route_payload["handlers"][0]["handler"] == "get_product_trends"
    assert route_payload["handlers"][0]["normalized_route"] == "/products/trends"
    assert route_payload["consumers"][0]["method"] == "GET"
    assert route_payload["consumers"][0]["function"] == "getProductTrends"
    assert route_payload["consumers"][0]["normalized_route"] == "/products/trends"
    assert route_payload["consumers"][0]["parser"] == "tree_sitter"
    assert payload["compact_summary"]["top_files"] == ["backend/routers/products.py", "frontend/src/services/api.ts"]
    assert "get_product_trends" in payload["compact_summary"]["top_symbols"]
    assert "getProductTrends" in payload["compact_summary"]["top_symbols"]


def test_route_map_extracts_flask_route_decorators(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "app.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@app.route('/reports/export', methods=['POST'])\n"
        "def export_report():\n"
        "    return {'status': 'ok'}\n",
        encoding="utf-8",
    )

    class _FilesRepoWithFlaskRoute:
        def fetch_all(self):
            return [{"path": "backend/app.py"}]

    class _StoreWithFlaskRoute(_Store):
        files = _FilesRepoWithFlaskRoute()

    payload = route_map(tmp_path, _StoreWithFlaskRoute(), route="/reports/export")

    assert payload["routes"][0]["route"] == "/reports/export"
    assert payload["routes"][0]["handlers"][0]["method"] == "POST"
    assert payload["routes"][0]["handlers"][0]["handler"] == "export_report"


def test_route_map_extracts_django_path_mappings(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "urls.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "from django.urls import path\n\n"
        "def product_trends(request):\n"
        "    return JsonResponse({'product_code': 'A', 'metrics': {'intransit_stock': 1}})\n\n"
        "urlpatterns = [\n"
        "    path('products/trends/', product_trends, name='product-trends'),\n"
        "]\n",
        encoding="utf-8",
    )

    class _FilesRepoWithDjangoRoute:
        def fetch_all(self):
            return [{"path": "backend/urls.py"}]

    class _StoreWithDjangoRoute(_Store):
        files = _FilesRepoWithDjangoRoute()

    payload = route_map(tmp_path, _StoreWithDjangoRoute(), route="/products/trends")

    assert payload["routes"][0]["route"] == "/products/trends"
    assert payload["routes"][0]["handlers"][0]["router"] == "path"
    assert payload["routes"][0]["handlers"][0]["handler"] == "product_trends"
    assert payload["routes"][0]["handlers"][0]["response_keys"] == ["intransit_stock", "metrics", "product_code"]


def test_route_map_uses_ast_for_optional_api_client_member_calls(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend" / "src" / "services" / "api.ts"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export async function loadPricing() {\n"
        "  const response = await apiClient?.post('/settings/channel-pricing', { enabled: true })\n"
        "  return response.data.updated\n"
        "}\n",
        encoding="utf-8",
    )

    class _FilesRepoWithAstRoute:
        def fetch_all(self):
            return [{"path": "frontend/src/services/api.ts"}]

    class _StoreWithAstRoute(_Store):
        files = _FilesRepoWithAstRoute()

    payload = route_map(tmp_path, _StoreWithAstRoute(), route="/settings/channel-pricing")

    assert payload["routes"][0]["route"] == "/settings/channel-pricing"
    assert payload["routes"][0]["consumers"][0]["method"] == "POST"
    assert payload["routes"][0]["consumers"][0]["parser"] == "tree_sitter"


def test_route_map_resolves_frontend_route_constants(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend" / "src" / "services" / "api.ts"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "const PRODUCT_TRENDS_ROUTE = '/api/products/trends'\n"
        "export async function loadTrends() {\n"
        "  const response = await apiClient.get(PRODUCT_TRENDS_ROUTE)\n"
        "  return response.data.metrics.intransit_stock\n"
        "}\n",
        encoding="utf-8",
    )

    class _FilesRepoWithConstantRoute:
        def fetch_all(self):
            return [{"path": "frontend/src/services/api.ts"}]

    class _StoreWithConstantRoute(_Store):
        files = _FilesRepoWithConstantRoute()

    payload = route_map(tmp_path, _StoreWithConstantRoute(), route="/products/trends")

    assert payload["routes"][0]["route"] == "/products/trends"
    assert payload["routes"][0]["consumers"][0]["function"] == "loadTrends"
    assert payload["routes"][0]["consumers"][0]["parser"] == "tree_sitter"


def test_route_map_extracts_express_routes_from_backend_scripts(tmp_path: Path) -> None:
    backend = tmp_path / "server" / "routes.ts"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "function productTrends(req, res) {\n"
        "  return res.json({ product_code: 'A', metrics: { intransit_stock: 1 } })\n"
        "}\n"
        "router.get('/products/trends', productTrends)\n",
        encoding="utf-8",
    )

    class _FilesRepoWithExpressRoute:
        def fetch_all(self):
            return [{"path": "server/routes.ts"}]

    class _StoreWithExpressRoute(_Store):
        files = _FilesRepoWithExpressRoute()

    payload = route_map(tmp_path, _StoreWithExpressRoute(), route="/products/trends")

    assert payload["routes"][0]["route"] == "/products/trends"
    assert payload["routes"][0]["handlers"][0]["method"] == "GET"
    assert payload["routes"][0]["handlers"][0]["handler"] == "productTrends"
    assert "metrics" in payload["routes"][0]["handlers"][0]["response_keys"]


def test_route_map_extracts_aspnet_controller_routes(tmp_path: Path) -> None:
    controller = tmp_path / "backend" / "Controllers" / "ProductsController.cs"
    controller.parent.mkdir(parents=True)
    controller.write_text(
        "using Microsoft.AspNetCore.Mvc;\n"
        "[ApiController]\n"
        "[Route(\"api/[controller]\")]\n"
        "public class ProductsController : ControllerBase {\n"
        "  [HttpGet(\"trends/{id:int}\")]\n"
        "  public IActionResult GetTrend(int id) {\n"
        "    return Ok(new { product_code = id, metrics = new { intransit_stock = 1 } });\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    class _FilesRepoWithAspNetController:
        def fetch_all(self):
            return [{"path": "backend/Controllers/ProductsController.cs"}]

    class _StoreWithAspNetController(_Store):
        files = _FilesRepoWithAspNetController()

    payload = route_map(tmp_path, _StoreWithAspNetController(), route="/api/products/trends/{id}")

    handler = payload["routes"][0]["handlers"][0]
    assert payload["routes"][0]["route"] == "/products/trends/{id}"
    assert handler["method"] == "GET"
    assert handler["handler"] == "GetTrend"
    assert handler["router"] == "ProductsController"
    assert handler["framework"] == "aspnet_controller"
    assert "metrics" in handler["response_keys"]


def test_route_map_extracts_aspnet_minimal_api_routes(tmp_path: Path) -> None:
    program = tmp_path / "backend" / "Program.cs"
    program.parent.mkdir(parents=True)
    program.write_text(
        "var app = WebApplication.CreateBuilder(args).Build();\n"
        "app.MapPost(\"/api/orders/reprice\", RepriceOrder);\n"
        "IResult RepriceOrder(OrderRequest request) => Results.Json(new { status = \"ok\", total = 10 });\n",
        encoding="utf-8",
    )

    class _FilesRepoWithMinimalApi:
        def fetch_all(self):
            return [{"path": "backend/Program.cs"}]

    class _StoreWithMinimalApi(_Store):
        files = _FilesRepoWithMinimalApi()

    payload = route_map(tmp_path, _StoreWithMinimalApi(), route="/orders/reprice")

    handler = payload["routes"][0]["handlers"][0]
    assert payload["routes"][0]["route"] == "/orders/reprice"
    assert handler["method"] == "POST"
    assert handler["handler"] == "RepriceOrder"
    assert handler["framework"] == "aspnet_minimal_api"
    assert "status" in handler["response_keys"]


def test_route_map_extracts_aspnet_dto_response_shape(tmp_path: Path) -> None:
    controller = tmp_path / "backend" / "Controllers" / "ProductsController.cs"
    controller.parent.mkdir(parents=True)
    controller.write_text(
        "using Microsoft.AspNetCore.Mvc;\n"
        "public record TrendMetricsDto(int IntransitStock, int EffectiveStock);\n"
        "public record ProductTrendDto(string ProductCode, TrendMetricsDto Metrics);\n"
        "[ApiController]\n"
        "[Route(\"api/[controller]\")]\n"
        "public class ProductsController : ControllerBase {\n"
        "  [HttpGet(\"trends\")]\n"
        "  public ActionResult<ProductTrendDto> GetTrend() {\n"
        "    return Ok(new ProductTrendDto(\"A\", new TrendMetricsDto(1, 2)));\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    class _FilesRepoWithAspNetDto:
        def fetch_all(self):
            return [{"path": "backend/Controllers/ProductsController.cs"}]

    class _StoreWithAspNetDto(_Store):
        files = _FilesRepoWithAspNetDto()

    payload = route_map(tmp_path, _StoreWithAspNetDto(), route="/products/trends")
    handler = payload["routes"][0]["handlers"][0]

    assert handler["response_model"] == "ProductTrendDto"
    assert handler["response_keys"] == ["metrics", "productCode"]
    assert handler["nested_response_keys"] == {"metrics": ["effectiveStock", "intransitStock"]}


def test_route_map_extracts_rich_frontend_field_reads(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'current_stock': 1, 'intransit_stock': 2, 'effective_stock': 3}, 'chart_data': [{'intransit_stock': 1, 'qty_sold': 2, 'incoming_known': 3}]}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "components" / "ProductTrendModal.tsx"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export function ProductTrendModal() {\n"
        "  const response = await apiClient?.get('/api/products/trends')\n"
        "  const data = response.data\n"
        "  const { metrics, chart_data: chartData } = data\n"
        "  const { effective_stock } = metrics\n"
        "  const rows = chartData.map(point => ({ sold: point.qty_sold, transit: point.intransit_stock, known: point.incoming_known }))\n"
        "  return <BarChart data={chartData}><Bar dataKey=\"intransit_stock\" /><Line dataKey=\"qty_sold\" /></BarChart>\n"
        "}\n",
        encoding="utf-8",
    )

    class _FilesRepoWithRichReads:
        def fetch_all(self):
            return [{"path": "backend/routers/products.py"}, {"path": "frontend/src/components/ProductTrendModal.tsx"}]

    class _StoreWithRichReads(_Store):
        files = _FilesRepoWithRichReads()

    payload = route_map(tmp_path, _StoreWithRichReads(), route="/products/trends")
    consumer = payload["routes"][0]["consumers"][0]

    assert consumer["parser"] == "tree_sitter"
    assert "metrics" in consumer["accessed_keys"]
    assert "chart_data" in consumer["accessed_keys"]
    assert "metrics.effective_stock" in consumer["nested_accesses"]
    assert "chart_data[].qty_sold" in consumer["nested_accesses"]
    assert "chart_data[].intransit_stock" in consumer["nested_accesses"]
    assert "chart_data[].incoming_known" in consumer["nested_accesses"]


def test_route_map_names_typed_react_component_wrapper_consumers(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'avg_ros': 1}}\n",
        encoding="utf-8",
    )
    api_file = tmp_path / "frontend" / "src" / "services" / "api.ts"
    api_file.parent.mkdir(parents=True)
    api_file.write_text(
        "export const getProductTrends = async () => {\n"
        "  const response = await apiClient.get('/products/trends')\n"
        "  return response.data\n"
        "}\n",
        encoding="utf-8",
    )
    component = tmp_path / "frontend" / "src" / "ProductTrendModal.tsx"
    component.write_text(
        "const ProductTrendModal: React.FC<ProductTrendModalProps> = ({ productCode }) => {\n"
        "  const { data } = useQuery({ queryFn: () => getProductTrends(productCode) })\n"
        "  return data?.metrics?.avg_ros\n"
        "}\n",
        encoding="utf-8",
    )

    class _FilesRepoWithTypedComponent:
        def fetch_all(self):
            return [
                {"path": "backend/routers/products.py"},
                {"path": "frontend/src/services/api.ts"},
                {"path": "frontend/src/ProductTrendModal.tsx"},
            ]

    class _StoreWithTypedComponent(_Store):
        files = _FilesRepoWithTypedComponent()

    payload = route_map(tmp_path, _StoreWithTypedComponent(), route="/products/trends")
    wrapper = [consumer for consumer in payload["routes"][0]["consumers"] if consumer.get("consumer_type") == "wrapper_call"][0]

    assert wrapper["function"] == "ProductTrendModal"
    assert "metrics.avg_ros" in wrapper["nested_accesses"]


def test_route_map_ignores_test_fixture_routes(tmp_path: Path) -> None:
    app_route = tmp_path / "backend" / "routers" / "customers.py"
    app_route.parent.mkdir(parents=True)
    app_route.write_text(
        "@router.get('/customers')\n"
        "def get_customers():\n"
        "    return {'customers': []}\n",
        encoding="utf-8",
    )
    test_route = tmp_path / "tests" / "test_customers.py"
    test_route.parent.mkdir()
    test_route.write_text(
        "@router.get('/fixture-only')\n"
        "def fixture_route():\n"
        "    return {'fixture': True}\n",
        encoding="utf-8",
    )

    class _FilesRepoWithTests:
        def fetch_all(self):
            return [{"path": "backend/routers/customers.py"}, {"path": "tests/test_customers.py"}]

    class _StoreWithTests(_Store):
        files = _FilesRepoWithTests()

    payload = route_map(tmp_path, _StoreWithTests())

    assert [item["route"] for item in payload["routes"]] == ["/customers"]
