from pathlib import Path

from services.field_impact_service import field_impact


class _Store:
    def __init__(self, files):
        self._files = files

    class _Files:
        def __init__(self, rows):
            self._rows = rows

        def fetch_all(self):
            return [{"path": item} for item in self._rows]

    @property
    def files(self):
        return self._Files(self._files)

    def fetch_symbols_for_file(self, file_path):
        rows = {
            "backend/routers/products.py": [
                {"qualified_name": "get_product_trends", "name": "get_product_trends", "file_path": file_path}
            ],
            "frontend/src/services/api.ts": [
                {"qualified_name": "services.api.getProductTrends", "name": "getProductTrends", "file_path": file_path}
            ],
            "frontend/src/ProductTrendModal.tsx": [
                {"qualified_name": "components.ProductTrendModal.ProductTrendModal", "name": "ProductTrendModal", "file_path": file_path}
            ],
        }
        return rows.get(file_path, [])

    def fetch_symbols_for_target(self, target, limit=1):
        for file_path in self._files:
            for row in self.fetch_symbols_for_file(file_path):
                if row["qualified_name"] == target or row["name"] == target:
                    return [row]
        return []


class _Kuzu:
    def edges_for_target(self, target, relation=None):
        if relation == "FETCHES" and target == "route:/products/trends":
            return [
                {"source": "services.api.getProductTrends", "relation": "FETCHES", "target": target},
            ]
        return []

    def edges_for_source(self, source, relation=None):
        if relation == "READS_FIELD" and source == "components.ProductTrendModal.ProductTrendModal":
            return [
                {"source": source, "relation": "READS_FIELD", "target": "field:metrics.intransit_stock"},
                {"source": source, "relation": "READS_FIELD", "target": "field:chart_data[].intransit_stock"},
            ]
        return []


def test_field_impact_reports_consumers_for_response_field(tmp_path: Path) -> None:
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
        "  return data.chart_data.map((point) => point.intransit_stock)\n"
        "}\n",
        encoding="utf-8",
    )

    payload = field_impact(
        tmp_path,
        _Store(["backend/routers/products.py", "frontend/src/services/api.ts", "frontend/src/ProductTrendModal.tsx"]),
        field="chart_data[].intransit_stock",
        route="/products/trends",
        kuzu_store=_Kuzu(),
    )

    assert payload["risk"] == "MEDIUM"
    assert payload["matches"][0]["route"] == "/products/trends"
    assert "components.ProductTrendModal.ProductTrendModal" in payload["matches"][0]["readers"]
    assert "frontend/src/ProductTrendModal.tsx" in payload["matches"][0]["files"]
    assert payload["compact_summary"]["top_symbols"] == ["components.ProductTrendModal.ProductTrendModal"]


def test_field_impact_reports_missing_response_field(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'chart_data': [{'stock': 1}]}\n",
        encoding="utf-8",
    )
    component = tmp_path / "frontend" / "src" / "ProductTrendModal.tsx"
    component.parent.mkdir(parents=True)
    component.write_text(
        "export const ProductTrendModal = async () => {\n"
        "  const response = await apiClient.get('/products/trends')\n"
        "  return response.data.chart_data.map((point) => point.intransit_stock)\n"
        "}\n",
        encoding="utf-8",
    )

    payload = field_impact(
        tmp_path,
        _Store(["backend/routers/products.py", "frontend/src/ProductTrendModal.tsx"]),
        field="chart_data[].intransit_stock",
        route="/products/trends",
    )

    assert payload["risk"] == "HIGH"
    assert payload["matches"][0]["missing_from_response"] == ["chart_data[].intransit_stock"]
    assert payload["compact_summary"]["missing_from_response"] == ["chart_data[].intransit_stock"]
