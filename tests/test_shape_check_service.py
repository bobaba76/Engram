from pathlib import Path

from services.shape_check_service import shape_check


class _Store:
    def __init__(self, paths):
        class _Files:
            def fetch_all(self_inner):
                return [{"path": path} for path in paths]

        self.files = _Files()

    def fetch_symbols_for_file(self, file_path):
        return [{"qualified_name": file_path.replace("/", ".")}]


def test_shape_check_reports_ok_route_contract(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'intransit_stock': 1}, 'chart_data': [{'stock': 1}]}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "ProductTrendModal.tsx"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const ProductTrendModal = async () => {\n"
        "  const response = await apiClient.get('/api/products/trends')\n"
        "  const data = response.data\n"
        "  return data.metrics.intransit_stock + data.chart_data.map(point => point.stock)\n"
        "}\n",
        encoding="utf-8",
    )

    payload = shape_check(tmp_path, _Store(["backend/routers/products.py", "frontend/src/ProductTrendModal.tsx"]), route="/products/trends")

    assert payload["status"] == "OK"
    assert payload["mismatch_count"] == 0
    assert payload["routes"][0]["status"] == "OK"
    assert "backend/routers/products.py" in payload["compact_summary"]["top_files"]
    assert "frontend/src/ProductTrendModal.tsx" in payload["compact_summary"]["top_files"]
    assert "get_product_trends" in payload["compact_summary"]["top_symbols"]
    assert "ProductTrendModal" in payload["compact_summary"]["top_symbols"]


def test_shape_check_reports_mismatched_route_contract(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@products_router.get('/products/trends')\n"
        "def get_product_trends():\n"
        "    return {'metrics': {'current_stock': 1}, 'chart_data': [{'stock': 1}]}\n",
        encoding="utf-8",
    )
    frontend = tmp_path / "frontend" / "src" / "ProductTrendModal.tsx"
    frontend.parent.mkdir(parents=True)
    frontend.write_text(
        "export const ProductTrendModal = async () => {\n"
        "  const response = await apiClient.get('/products/trends')\n"
        "  const data = response.data\n"
        "  return data.metrics.intransit_stock + data.chart_data.map(point => point.intransit_stock)\n"
        "}\n",
        encoding="utf-8",
    )

    payload = shape_check(tmp_path, _Store(["backend/routers/products.py", "frontend/src/ProductTrendModal.tsx"]), route="/api/products/trends")

    assert payload["status"] == "MISMATCH"
    assert payload["mismatch_count"] == 1
    assert payload["routes"][0]["nested_missing_fields"] == ["chart_data[].intransit_stock", "metrics.intransit_stock"]
    assert payload["compact_summary"]["mismatches"] == ["/products/trends"]
