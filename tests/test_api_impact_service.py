from pathlib import Path

from services.api_impact_service import api_impact


class _Store:
    def __init__(self, paths):
        class _Files:
            def fetch_all(self_inner):
                return [{"path": path} for path in paths]

        self.files = _Files()

    def fetch_symbols_for_file(self, file_path):
        rows = {
            "frontend/src/services/api.ts": [
                {
                    "qualified_name": "services.api.getProductTrends",
                    "name": "getProductTrends",
                    "file_path": "frontend/src/services/api.ts",
                    "kind": "function",
                }
            ],
            "frontend/src/ProductTrendModal.tsx": [
                {
                    "qualified_name": "components.ProductTrendModal.ProductTrendModal",
                    "name": "ProductTrendModal",
                    "file_path": "frontend/src/ProductTrendModal.tsx",
                    "kind": "component",
                }
            ],
        }
        return rows.get(file_path, [{"qualified_name": file_path.replace("/", "."), "name": Path(file_path).stem, "file_path": file_path}])

    def fetch_symbols_for_target(self, target, limit=1):
        rows = {
            "get_product_trends": {
                "qualified_name": "get_product_trends",
                "name": "get_product_trends",
                "file_path": "backend/routers/products.py",
                "kind": "function",
            },
            "get_product_trend_data": {
                "qualified_name": "get_product_trend_data",
                "name": "get_product_trend_data",
                "file_path": "backend/services/product_trends.py",
                "kind": "function",
            },
            "services.api.getProductTrends": {
                "qualified_name": "services.api.getProductTrends",
                "name": "getProductTrends",
                "file_path": "frontend/src/services/api.ts",
                "kind": "function",
            },
            "components.ProductTrendModal.ProductTrendModal": {
                "qualified_name": "components.ProductTrendModal.ProductTrendModal",
                "name": "ProductTrendModal",
                "file_path": "frontend/src/ProductTrendModal.tsx",
                "kind": "component",
            },
        }
        return [rows[target]] if target in rows else []


class _Kuzu:
    def edges_for_target(self, target, relation=None):
        if relation == "FETCHES" and target == "route:/products/trends":
            return [
                {"source": "services.api.response", "relation": "FETCHES", "target": target},
                {"source": "services.api.getProductTrends", "relation": "FETCHES", "target": target},
            ]
        return []

    def edges_for_source(self, source, relation=None):
        if relation == "CALLS" and source == "get_product_trends":
            return [{"source": "get_product_trends", "relation": "CALLS", "target": "get_product_trend_data"}]
        if relation == "READS_FIELD" and source == "components.ProductTrendModal.ProductTrendModal":
            return [
                {"source": source, "relation": "READS_FIELD", "target": "field:metrics.intransit_stock"},
                {"source": source, "relation": "READS_FIELD", "target": "field:chart_data[].intransit_stock"},
            ]
        return []


def test_api_impact_reports_ok_nested_shape(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'intransit_stock': 1, 'effective_stock': 2}, 'chart_data': []}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "api.ts"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const getProductTrends = async () => {\n"
        "  const response = await apiClient.get('/api/products/trends')\n"
        "  return response.data.metrics.intransit_stock\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(tmp_path, _Store(["backend/routers/products.py", "frontend/src/api.ts"]), route="/products/trends")

    route_payload = payload["routes"][0]
    assert route_payload["response_shape"]["nested_keys"]["metrics"] == ["effective_stock", "intransit_stock"]
    assert route_payload["shape_check"]["status"] == "OK"
    assert route_payload["risk"] == "MEDIUM"


def test_api_impact_reports_nested_shape_mismatch(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'current_stock': 1}, 'chart_data': []}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "api.ts"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const getProductTrends = async () => {\n"
        "  const response = await apiClient.get('/products/trends')\n"
        "  return response.data.metrics.intransit_stock\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(tmp_path, _Store(["backend/routers/products.py", "frontend/src/api.ts"]), route="/api/products/trends")

    route_payload = payload["routes"][0]
    assert route_payload["shape_check"]["status"] == "MISMATCH"
    assert route_payload["shape_check"]["nested_missing_fields"] == ["metrics.intransit_stock"]
    assert route_payload["risk"] == "HIGH"
    assert payload["compact_summary"]["mismatches"] == ["/products/trends"]


def test_api_impact_detects_component_style_data_and_array_reads(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'intransit_stock': 1}, 'chart_data': [{'intransit_stock': 1}]}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "ProductTrendModal.tsx"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const ProductTrendModal = async () => {\n"
        "  const response = await apiClient.get('/api/products/trends')\n"
        "  const data = response.data\n"
        "  const payload = response.data\n"
        "  data.chart_data.map(point => point.intransit_stock)\n"
        "  return data.metrics.intransit_stock + payload.metrics.intransit_stock\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(tmp_path, _Store(["backend/routers/products.py", "frontend/src/ProductTrendModal.tsx"]), route="/products/trends")

    route_payload = payload["routes"][0]
    assert "metrics.intransit_stock" in route_payload["consumer_field_reads"]
    assert "chart_data[].intransit_stock" in route_payload["consumer_field_reads"]
    assert route_payload["shape_check"]["status"] == "OK"


def test_api_impact_links_wrapper_calls_to_component_reads(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'intransit_stock': 1}, 'chart_data': []}\n",
        encoding="utf-8",
    )
    api_file = tmp_path / "frontend" / "src" / "services" / "api.ts"
    api_file.parent.mkdir(parents=True)
    api_file.write_text(
        "export const getProductTrends = async () => {\n"
        "  const response = await apiClient.get('/api/products/trends')\n"
        "  return response.data\n"
        "}\n",
        encoding="utf-8",
    )
    component = tmp_path / "frontend" / "src" / "ProductTrendModal.tsx"
    component.write_text(
        "export const ProductTrendModal = async () => {\n"
        "  const data = await getProductTrends()\n"
        "  return data.metrics.intransit_stock\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(
        tmp_path,
        _Store(["backend/routers/products.py", "frontend/src/services/api.ts", "frontend/src/ProductTrendModal.tsx"]),
        route="/products/trends",
    )

    consumers = payload["routes"][0]["consumers"]
    wrapper_consumers = [consumer for consumer in consumers if consumer.get("consumer_type") == "wrapper_call"]
    assert wrapper_consumers[0]["function"] == "ProductTrendModal"
    assert wrapper_consumers[0]["calls_wrapper"] == "getProductTrends"
    assert "metrics.intransit_stock" in wrapper_consumers[0]["nested_accesses"]
    assert payload["routes"][0]["shape_check"]["status"] == "OK"


def test_api_impact_links_wrappers_with_typescript_return_annotations(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'avg_ros': 1}, 'chart_data': []}\n",
        encoding="utf-8",
    )
    api_file = tmp_path / "frontend" / "src" / "services" / "api.ts"
    api_file.parent.mkdir(parents=True)
    api_file.write_text(
        "export const getProductTrends = async (productCode: string): Promise<any> => {\n"
        "  const response = await apiClient.get('/api/products/trends', { params: { product_code: productCode } })\n"
        "  return response.data\n"
        "}\n",
        encoding="utf-8",
    )
    component = tmp_path / "frontend" / "src" / "ProductTrendModal.tsx"
    component.write_text(
        "export const ProductTrendModal = async () => {\n"
        "  const data = await getProductTrends('A')\n"
        "  return data?.metrics?.avg_ros\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(
        tmp_path,
        _Store(["backend/routers/products.py", "frontend/src/services/api.ts", "frontend/src/ProductTrendModal.tsx"]),
        route="/products/trends",
    )

    consumers = payload["routes"][0]["consumers"]
    wrapper_consumers = [consumer for consumer in consumers if consumer.get("consumer_type") == "wrapper_call"]
    assert wrapper_consumers[0]["calls_wrapper"] == "getProductTrends"
    assert "metrics.avg_ros" in wrapper_consumers[0]["nested_accesses"]
    assert payload["routes"][0]["shape_check"]["status"] == "OK"


def test_api_impact_reports_array_item_shape_mismatch(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'chart_data': [{'stock': 1}]}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "ProductTrendModal.tsx"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const ProductTrendModal = async () => {\n"
        "  const response = await apiClient.get('/api/products/trends')\n"
        "  const data = response.data\n"
        "  return data.chart_data.map(point => point.intransit_stock)\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(tmp_path, _Store(["backend/routers/products.py", "frontend/src/ProductTrendModal.tsx"]), route="/products/trends")

    route_payload = payload["routes"][0]
    assert route_payload["response_shape"]["nested_keys"]["chart_data[]"] == ["stock"]
    assert route_payload["shape_check"]["nested_missing_fields"] == ["chart_data[].intransit_stock"]
    assert route_payload["shape_check"]["status"] == "MISMATCH"


def test_api_impact_uses_response_model_fields(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "from pydantic import BaseModel\n"
        "class TrendResponse(BaseModel):\n"
        "    product_code: str\n"
        "    chart_data: list\n"
        "\n"
        "@products_router.get('/products/trends', response_model=TrendResponse)\n"
        "def get_product_trends():\n"
        "    return build_payload()\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "api.ts"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const getProductTrends = async () => {\n"
        "  const response = await apiClient.get('/products/trends')\n"
        "  return response.data.product_code + response.data.chart_data.length\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(tmp_path, _Store(["backend/routers/products.py", "frontend/src/api.ts"]), route="/products/trends")

    route_payload = payload["routes"][0]
    assert route_payload["handlers"][0]["response_model"] == "TrendResponse"
    assert route_payload["response_shape"]["top_level_keys"] == ["chart_data", "product_code"]
    assert route_payload["shape_check"]["status"] == "OK"


def test_api_impact_uses_nested_response_model_fields(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "from pydantic import BaseModel\n"
        "class MetricPayload(BaseModel):\n"
        "    avg_ros: float\n"
        "    effective_stock: int\n"
        "class TrendPoint(BaseModel):\n"
        "    intransit_stock: int\n"
        "    stock: int\n"
        "class TrendResponse(BaseModel):\n"
        "    metrics: MetricPayload\n"
        "    chart_data: list[TrendPoint]\n"
        "\n"
        "@products_router.get('/products/trends', response_model=TrendResponse)\n"
        "def get_product_trends():\n"
        "    return build_payload()\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "api.ts"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const getProductTrends = async () => {\n"
        "  const response = await apiClient.get('/products/trends')\n"
        "  const data = response.data\n"
        "  return data.metrics.avg_ros + data.chart_data.map(point => point.intransit_stock)\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(tmp_path, _Store(["backend/routers/products.py", "frontend/src/api.ts"]), route="/products/trends")

    shape = payload["routes"][0]["response_shape"]
    assert shape["top_level_keys"] == ["chart_data", "metrics"]
    assert shape["nested_keys"]["metrics"] == ["avg_ros", "effective_stock"]
    assert shape["nested_keys"]["chart_data[]"] == ["intransit_stock", "stock"]
    assert payload["routes"][0]["shape_check"]["status"] == "OK"


def test_api_impact_extracts_returned_payload_variable_shape(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    payload = {'metrics': {'avg_ros': 1}, 'chart_data': [{'stock': 1}]}\n"
        "    return payload\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "api.ts"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const getProductTrends = async () => {\n"
        "  const response = await apiClient.get('/products/trends')\n"
        "  const data = response.data\n"
        "  return data.metrics.avg_ros + data.chart_data.map(point => point.stock)\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(tmp_path, _Store(["backend/routers/products.py", "frontend/src/api.ts"]), route="/products/trends")

    assert payload["routes"][0]["response_shape"]["nested_keys"]["metrics"] == ["avg_ros"]
    assert payload["routes"][0]["response_shape"]["nested_keys"]["chart_data[]"] == ["stock"]
    assert payload["routes"][0]["shape_check"]["status"] == "OK"


def test_api_impact_tracks_destructured_and_aliased_consumer_reads(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'intransit_stock': 1, 'effective_stock': 2}}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "ProductTrendModal.tsx"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const ProductTrendModal = async () => {\n"
        "  const response = await apiClient.get('/products/trends')\n"
        "  const data = response.data\n"
        "  const { metrics } = data\n"
        "  const totals = data.metrics\n"
        "  return metrics.intransit_stock + totals.effective_stock\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(tmp_path, _Store(["backend/routers/products.py", "frontend/src/ProductTrendModal.tsx"]), route="/products/trends")

    reads = payload["routes"][0]["consumer_field_reads"]
    assert "metrics.intransit_stock" in reads
    assert "metrics.effective_stock" in reads
    assert payload["routes"][0]["shape_check"]["status"] == "OK"


def test_api_impact_tracks_react_query_and_chart_datakey_reads(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'chart_data': [{'intransit_stock': 1}], 'metrics': {'avg_ros': 1}}\n",
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
        "export const ProductTrendModal = () => {\n"
        "  const { data } = useQuery({ queryKey: ['trend'], queryFn: () => getProductTrends() })\n"
        "  const chartRows = data.chart_data\n"
        "  return <LineChart data={data.chart_data}><Line dataKey=\"intransit_stock\" /></LineChart>\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(
        tmp_path,
        _Store(["backend/routers/products.py", "frontend/src/services/api.ts", "frontend/src/ProductTrendModal.tsx"]),
        route="/products/trends",
    )

    reads = payload["routes"][0]["consumer_field_reads"]
    assert "chart_data[].intransit_stock" in reads
    assert payload["routes"][0]["shape_check"]["status"] == "OK"


def test_api_impact_tracks_chart_datakey_through_chart_rows_alias(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'chart_data': [{'qty_sold': 1, 'incoming_known': 2, 'incoming_unknown': 3}]}\n",
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
        "export const ProductTrendModal = async () => {\n"
        "  const data = await getProductTrends()\n"
        "  const chartRows = data.chart_data\n"
        "  return <BarChart data={chartRows}><Bar dataKey=\"qty_sold\" /><Bar dataKey=\"incoming_known\" /><Bar dataKey=\"incoming_unknown\" /></BarChart>\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(
        tmp_path,
        _Store(["backend/routers/products.py", "frontend/src/services/api.ts", "frontend/src/ProductTrendModal.tsx"]),
        route="/products/trends",
    )

    reads = payload["routes"][0]["consumer_field_reads"]
    assert "chart_data[].qty_sold" in reads
    assert "chart_data[].incoming_known" in reads
    assert "chart_data[].incoming_unknown" in reads
    assert payload["routes"][0]["shape_check"]["status"] == "OK"


def test_api_impact_surfaces_rich_product_trend_consumer_reads(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'current_stock': 1, 'intransit_stock': 2}, 'chart_data': [{'qty_sold': 1}]}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "ProductTrendModal.tsx"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const ProductTrendModal = async () => {\n"
        "  const response = await apiClient.get('/products/trends')\n"
        "  const data = response.data\n"
        "  const { metrics, chart_data: chartData } = data\n"
        "  const { current_stock } = metrics\n"
        "  chartData.map(point => point.qty_sold + point.intransit_stock)\n"
        "  return <BarChart data={chartData}><Bar dataKey=\"qty_sold\" /><Bar dataKey=\"intransit_stock\" /></BarChart>\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(tmp_path, _Store(["backend/routers/products.py", "frontend/src/ProductTrendModal.tsx"]), route="/products/trends")

    route_payload = payload["routes"][0]
    reads = route_payload["consumer_field_reads"]
    assert "metrics.current_stock" in reads
    assert "chart_data[].qty_sold" in reads
    assert "chart_data[].intransit_stock" in reads
    assert route_payload["shape_check"]["nested_missing_fields"] == ["chart_data[].intransit_stock"]
    assert route_payload["shape_check"]["status"] == "MISMATCH"


def test_api_impact_includes_process_flows_when_graph_is_available(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'intransit_stock': 1}}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "api.ts"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const getProductTrends = async () => {\n"
        "  const response = await apiClient.get('/products/trends')\n"
        "  return response.data.metrics.intransit_stock\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(
        tmp_path,
        _Store(["backend/routers/products.py", "frontend/src/api.ts"]),
        route="/products/trends",
        kuzu_store=_Kuzu(),
    )

    processes = payload["routes"][0]["processes"]
    assert processes[0]["name"] == "GET /products/trends -> get_product_trends -> get_product_trend_data"
    assert processes[0]["flow_name"] == "backend: get_product_trends -> get_product_trend_data"
    assert processes[0]["entry_symbol"] == "get_product_trends"
    assert processes[0]["symbols"] == ["get_product_trends", "get_product_trend_data"]
    assert payload["routes"][0]["risk"] == "MEDIUM"
    assert "1 traced execution flows" in payload["routes"][0]["risk_factors"]
    assert "get_product_trends" in payload["compact_summary"]["top_processes"][0]
    assert "get_product_trend_data" in payload["compact_summary"]["top_processes"][0]


def test_api_impact_uses_graph_fetches_and_field_readers(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'intransit_stock': 1}, 'chart_data': [{'intransit_stock': 1}]}\n",
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
        "export const ProductTrendModal = async () => {\n"
        "  const data = await getProductTrends()\n"
        "  return data.metrics.intransit_stock\n"
        "}\n",
        encoding="utf-8",
    )

    payload = api_impact(
        tmp_path,
        _Store(["backend/routers/products.py", "frontend/src/services/api.ts", "frontend/src/ProductTrendModal.tsx"]),
        route="/products/trends",
        kuzu_store=_Kuzu(),
    )

    route_payload = payload["routes"][0]
    assert route_payload["graph_contract"]["fetchers"][0]["symbol"] == "services.api.getProductTrends"
    assert all(fetcher["symbol"] != "services.api.response" for fetcher in route_payload["graph_contract"]["fetchers"])
    assert {
        "metrics.intransit_stock",
        "chart_data[].intransit_stock",
    }.issubset(set(route_payload["graph_contract"]["field_reads"]))
    assert "chart_data[].intransit_stock" in route_payload["consumer_field_reads"]
    assert "This route is fetched by services.api.getProductTrends" in route_payload["blast_radius"]["summary"]
    assert "components.ProductTrendModal.ProductTrendModal" in route_payload["blast_radius"]["summary"]
    assert payload["compact_summary"]["graph_fetchers"] == ["services.api.getProductTrends"]
    assert payload["compact_summary"]["graph_field_readers"] == ["components.ProductTrendModal.ProductTrendModal"]
    assert payload["compact_summary"]["graph_field_count"] == 2
    assert "backend/routers/products.py" in payload["compact_summary"]["top_files"]
    assert "frontend/src/services/api.ts" in payload["compact_summary"]["top_files"]
    assert "get_product_trends" in payload["compact_summary"]["top_symbols"]
    assert "services.api.getProductTrends" in payload["compact_summary"]["top_symbols"]
