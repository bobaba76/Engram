from pathlib import Path

from indexing.symbol_extractor import extract_symbols_with_status


def test_python_parser_module_is_registered(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "class CustomerService:\n"
        "    def assign(self):\n"
        "        return helper()\n"
        "\n"
        "def helper():\n"
        "    return 1\n",
        encoding="utf-8",
    )

    symbols, status = extract_symbols_with_status(source)

    assert status["parser"] == "ast"
    assert status["language"] == "python"
    assert {symbol.qualified_name for symbol in symbols} >= {"CustomerService", "CustomerService.assign", "helper"}


def test_python_parser_accepts_utf8_bom(tmp_path: Path) -> None:
    source = tmp_path / "bom_sample.py"
    source.write_text(
        "\ufeff"
        "class Dashboard:\n"
        "    def render(self):\n"
        "        return helper()\n"
        "\n"
        "def helper():\n"
        "    return 1\n",
        encoding="utf-8",
    )

    symbols, status = extract_symbols_with_status(source)

    assert status["parser"] == "ast"
    assert status["language"] == "python"
    assert {symbol.qualified_name for symbol in symbols} >= {"Dashboard", "Dashboard.render", "helper"}


def test_python_parser_tracks_base_classes(tmp_path: Path) -> None:
    source = tmp_path / "inheritance.py"
    source.write_text(
        "class BaseService:\n"
        "    def run(self):\n"
        "        return 1\n"
        "\n"
        "class CustomerService(BaseService):\n"
        "    def run(self):\n"
        "        return super().run()\n",
        encoding="utf-8",
    )

    symbols, _ = extract_symbols_with_status(source)
    customer_service = next(symbol for symbol in symbols if symbol.name == "CustomerService")

    assert customer_service.metadata.get("extends") == ["BaseService"]


def test_python_parser_tracks_import_aliases(tmp_path: Path) -> None:
    source = tmp_path / "products.py"
    source.write_text(
        "from backend.services.product_trends import get_product_trend_data as svc_get_product_trend_data\n"
        "\n"
        "def get_product_trends():\n"
        "    return svc_get_product_trend_data()\n",
        encoding="utf-8",
    )

    symbols, _ = extract_symbols_with_status(source)
    handler = next(symbol for symbol in symbols if symbol.name == "get_product_trends")

    assert handler.metadata.get("import_aliases", {}).get("svc_get_product_trend_data") == "get_product_trend_data"
    assert "svc_get_product_trend_data" in handler.metadata.get("calls", [])


def test_typescript_parser_module_falls_back_to_regex(tmp_path: Path) -> None:
    source = tmp_path / "sample.ts"
    source.write_text(
        "export interface Customer { id: string }\n"
        "export function normalizeCustomer(customer: Customer) {\n"
        "  return customer.id\n"
        "}\n",
        encoding="utf-8",
    )

    symbols, status = extract_symbols_with_status(source)

    assert status["language"] == "typescript"
    assert {symbol.name for symbol in symbols} >= {"Customer", "normalizeCustomer"}


def test_typescript_parser_records_module_qualified_names(tmp_path: Path) -> None:
    source = tmp_path / "ui" / "CustomerView.tsx"
    source.parent.mkdir()
    source.write_text(
        "import CustomerPanel, { useCustomer as useBoundCustomer } from '../hooks/useCustomer'\n"
        "export class CustomerView {\n"
        "  renderCard() {\n"
        "    return useBoundCustomer() + CustomerPanel();\n"
        "  }\n"
        "}\n"
        "export default function useCustomer() {\n"
        "  return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    symbols, status = extract_symbols_with_status(source)
    qualified_names = {symbol.qualified_name for symbol in symbols}
    customer_view = next(symbol for symbol in symbols if symbol.name == "CustomerView")

    assert status["language"] == "typescript"
    assert "ui.CustomerView.CustomerView" in qualified_names or "ui.CustomerView" in qualified_names
    assert "ui.CustomerView.renderCard" in qualified_names
    assert any(symbol.name == "useCustomer" and symbol.metadata.get("module") == "ui.CustomerView" for symbol in symbols)
    assert "../hooks/useCustomer" in customer_view.metadata.get("imports", [])
    assert "useCustomer" in customer_view.metadata.get("imports", [])
    assert "useBoundCustomer" in customer_view.metadata.get("imports", [])
    assert "CustomerPanel" in customer_view.metadata.get("imports", [])
    assert customer_view.metadata.get("import_aliases", {}).get("useBoundCustomer") == "useCustomer"


def test_typescript_parser_tracks_extends_and_implements(tmp_path: Path) -> None:
    source = tmp_path / "ui" / "CustomerView.tsx"
    source.parent.mkdir()
    source.write_text(
        "interface Renderable { render(): void }\n"
        "class BaseView { render() {} }\n"
        "export class CustomerView extends BaseView implements Renderable {\n"
        "  render() { return this.props.customer.id }\n"
        "}\n",
        encoding="utf-8",
    )

    symbols, _ = extract_symbols_with_status(source)
    customer_view = next(symbol for symbol in symbols if symbol.name == "CustomerView")

    assert customer_view.metadata.get("extends") == ["BaseView"]
    assert customer_view.metadata.get("implements") == ["Renderable"]


def test_typescript_parser_tracks_api_fetches_and_field_reads(tmp_path: Path) -> None:
    source = tmp_path / "ui" / "ProductTrendModal.tsx"
    source.parent.mkdir()
    source.write_text(
        "export const ProductTrendModal = async () => {\n"
        "  const response = await apiClient.get('/api/products/trends')\n"
        "  const data = response.data\n"
        "  const { metrics, chart_data: chartData } = data\n"
        "  chartData.map(point => point.qty_sold + point.intransit_stock)\n"
        "  return metrics.effective_stock\n"
        "}\n",
        encoding="utf-8",
    )

    symbols, _ = extract_symbols_with_status(source)
    component = next(symbol for symbol in symbols if symbol.name == "ProductTrendModal")

    assert component.metadata.get("fetches") == ["/products/trends"]
    assert "metrics.effective_stock" in component.metadata.get("field_reads", [])
    assert "chart_data[].qty_sold" in component.metadata.get("field_reads", [])
    assert "chart_data[].intransit_stock" in component.metadata.get("field_reads", [])


def test_typescript_parser_tracks_reexport_paths_and_barrel_metadata(tmp_path: Path) -> None:
    source = tmp_path / "ui" / "index.ts"
    source.parent.mkdir()
    source.write_text(
        "export { useCustomer as useCustomerHook } from '../hooks/useCustomer'\n"
        "export * from '../components/CustomerPanel'\n",
        encoding="utf-8",
    )

    symbols, status = extract_symbols_with_status(source)
    export_symbol = next(symbol for symbol in symbols if symbol.name == "exports")

    assert status["language"] == "typescript"
    assert export_symbol.kind == "module"
    assert "ui/index.ts" not in export_symbol.metadata.get("source_associations", [])
    assert any(path.endswith("hooks/useCustomer.ts") for path in export_symbol.metadata.get("source_associations", []))
    assert any(path.endswith("components/CustomerPanel.ts") for path in export_symbol.metadata.get("source_associations", []))
    re_exports = export_symbol.metadata.get("re_exports", [])
    assert len(re_exports) == 2
    assert re_exports[0]["aliases"]["useCustomerHook"] == "useCustomer"
    assert re_exports[1]["export_all"] is True


def test_typescript_parser_tracks_default_and_namespace_bindings(tmp_path: Path) -> None:
    source = tmp_path / "ui" / "CustomerView.tsx"
    source.parent.mkdir()
    source.write_text(
        "import CustomerPanel, * as CustomerHooks from '../hooks/useCustomer'\n"
        "export function CustomerView() {\n"
        "  return CustomerPanel() + CustomerHooks.useCustomer()\n"
        "}\n",
        encoding="utf-8",
    )

    symbols, _ = extract_symbols_with_status(source)
    customer_view = next(symbol for symbol in symbols if symbol.name == "CustomerView")

    assert customer_view.metadata.get("import_aliases", {}).get("CustomerPanel") == "default"
    assert customer_view.metadata.get("import_aliases", {}).get("CustomerHooks") == "__namespace__"
    assert "CustomerHooks.useCustomer" in customer_view.metadata.get("calls", [])
    assert "CustomerHooks.useCustomer" in customer_view.metadata.get("references", [])


def test_typescript_parser_tracks_namespace_reexport_alias(tmp_path: Path) -> None:
    source = tmp_path / "ui" / "index.ts"
    source.parent.mkdir()
    source.write_text(
        "export * as CustomerHooks from '../hooks/useCustomer'\n",
        encoding="utf-8",
    )

    symbols, _ = extract_symbols_with_status(source)
    export_symbol = next(symbol for symbol in symbols if symbol.name == "exports")
    re_exports = export_symbol.metadata.get("re_exports", [])

    assert re_exports[0]["namespace_export"] is True
    assert re_exports[0]["aliases"]["CustomerHooks"] == "__namespace__"
    assert "CustomerHooks" in export_symbol.metadata.get("export_names", [])


def test_csharp_parser_tracks_dependency_injection_registrations(tmp_path: Path) -> None:
    source = tmp_path / "Program.cs"
    source.write_text(
        "var builder = WebApplication.CreateBuilder(args);\n"
        "builder.Services.AddScoped<IProductService, ProductService>();\n"
        "builder.Services.AddSingleton<IClock, SystemClock>();\n",
        encoding="utf-8",
    )

    symbols, status = extract_symbols_with_status(source)
    di_symbol = next(symbol for symbol in symbols if symbol.name == "dependency_injection")

    assert status["language"] == "csharp"
    assert {
        (item["service"], item["implementation"], item["lifetime"])
        for item in di_symbol.metadata.get("di_registrations", [])
    } == {
        ("IProductService", "ProductService", "scoped"),
        ("IClock", "SystemClock", "singleton"),
    }
