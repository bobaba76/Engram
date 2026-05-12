from models.entity_models import FileRecord, SymbolRecord
from indexing.graph_builder import build_graph


class _Kuzu:
    def __init__(self) -> None:
        self.files = []
        self.symbols = []
        self.edges = []

    def ensure_file(self, path: str) -> None:
        self.files.append(path)

    def ensure_symbol(self, qualified_name: str, file_path: str, kind: str, start_line: int, end_line: int) -> None:
        self.symbols.append((qualified_name, file_path, kind, start_line, end_line))

    def add_edge(self, source: str, relation: str, target: str) -> None:
        self.edges.append((source, relation, target))


def test_build_graph_resolves_typescript_import_and_call_edges() -> None:
    files = [
        FileRecord(path="src/hooks/useCustomer.ts", language="typescript", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="src/ui/CustomerView.tsx", language="typescript", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/hooks/useCustomer.ts": [
            SymbolRecord(
                name="useCustomer",
                qualified_name="src.hooks.useCustomer.useCustomer",
                kind="hook",
                start_line=1,
                end_line=3,
                signature="useCustomer",
                metadata={"imports": [], "calls": [], "references": []},
            )
        ],
        "src/ui/CustomerView.tsx": [
            SymbolRecord(
                name="CustomerView",
                qualified_name="src.ui.CustomerView.CustomerView",
                kind="component",
                start_line=1,
                end_line=6,
                signature="CustomerView",
                metadata={
                    "imports": ["../hooks/useCustomer", "useCustomer", "useBoundCustomer"],
                    "calls": ["useBoundCustomer"],
                    "references": ["useCustomer"],
                    "import_aliases": {"useBoundCustomer": "useCustomer"},
                },
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("src/ui/CustomerView.tsx", "DEFINES", "src.ui.CustomerView.CustomerView") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "IMPORTS", "src.hooks.useCustomer.useCustomer") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "CALLS", "src.hooks.useCustomer.useCustomer") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "REFERENCES", "src.hooks.useCustomer.useCustomer") in kuzu.edges


def test_build_graph_resolves_python_import_alias_call_edges() -> None:
    files = [
        FileRecord(path="backend/services/product_trends.py", language="python", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="backend/routers/products.py", language="python", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "backend/services/product_trends.py": [
            SymbolRecord(
                name="get_product_trend_data",
                qualified_name="backend.services.product_trends.get_product_trend_data",
                kind="function",
                start_line=1,
                end_line=3,
                signature="get_product_trend_data",
                metadata={"imports": [], "calls": [], "references": []},
            )
        ],
        "backend/routers/products.py": [
            SymbolRecord(
                name="get_product_trends",
                qualified_name="backend.routers.products.get_product_trends",
                kind="function",
                start_line=1,
                end_line=6,
                signature="get_product_trends",
                metadata={
                    "imports": ["backend.services.product_trends.get_product_trend_data"],
                    "calls": ["svc_get_product_trend_data"],
                    "references": ["svc_get_product_trend_data"],
                    "import_aliases": {"svc_get_product_trend_data": "get_product_trend_data"},
                },
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert (
        "backend.routers.products.get_product_trends",
        "CALLS",
        "backend.services.product_trends.get_product_trend_data",
    ) in kuzu.edges


def test_build_graph_adds_access_edges_for_property_reads() -> None:
    files = [
        FileRecord(path="src/ui/CustomerView.tsx", language="typescript", size_bytes=1, sha256="a", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/ui/CustomerView.tsx": [
            SymbolRecord(
                name="CustomerView",
                qualified_name="src.ui.CustomerView.CustomerView",
                kind="component",
                start_line=1,
                end_line=4,
                signature="CustomerView",
                metadata={"imports": [], "calls": [], "references": [], "accesses": ["data.metrics.intransit_stock"]},
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("property:data.metrics.intransit_stock", "src/ui/CustomerView.tsx", "property", 1, 4) in kuzu.symbols
    assert ("src.ui.CustomerView.CustomerView", "ACCESSES", "property:data.metrics.intransit_stock") in kuzu.edges


def test_build_graph_adds_frontend_api_contract_edges() -> None:
    files = [
        FileRecord(path="src/ui/ProductTrendModal.tsx", language="typescript", size_bytes=1, sha256="a", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/ui/ProductTrendModal.tsx": [
            SymbolRecord(
                name="ProductTrendModal",
                qualified_name="src.ui.ProductTrendModal.ProductTrendModal",
                kind="component",
                start_line=1,
                end_line=8,
                signature="ProductTrendModal",
                metadata={
                    "imports": [],
                    "calls": [],
                    "references": [],
                    "fetches": ["/products/trends"],
                    "field_reads": ["metrics.effective_stock", "chart_data[].qty_sold"],
                },
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("route:/products/trends", "src/ui/ProductTrendModal.tsx", "api_route", 1, 8) in kuzu.symbols
    assert ("field:metrics.effective_stock", "src/ui/ProductTrendModal.tsx", "field", 1, 8) in kuzu.symbols
    assert ("src.ui.ProductTrendModal.ProductTrendModal", "FETCHES", "route:/products/trends") in kuzu.edges
    assert ("src.ui.ProductTrendModal.ProductTrendModal", "READS_FIELD", "field:chart_data[].qty_sold") in kuzu.edges


def test_build_graph_adds_inheritance_and_method_override_edges() -> None:
    files = [
        FileRecord(path="src/services.py", language="python", size_bytes=1, sha256="a", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/services.py": [
            SymbolRecord(name="BaseService", qualified_name="BaseService", kind="class", start_line=1, end_line=3, signature="BaseService", metadata={"imports": [], "calls": [], "references": []}),
            SymbolRecord(name="run", qualified_name="BaseService.run", kind="method", start_line=2, end_line=3, signature="BaseService.run", metadata={"imports": [], "calls": [], "references": [], "parent_chain": ["BaseService"]}),
            SymbolRecord(name="CustomerService", qualified_name="CustomerService", kind="class", start_line=5, end_line=7, signature="CustomerService", metadata={"imports": [], "calls": [], "references": [], "extends": ["BaseService"]}),
            SymbolRecord(name="run", qualified_name="CustomerService.run", kind="method", start_line=6, end_line=7, signature="CustomerService.run", metadata={"imports": [], "calls": [], "references": [], "parent_chain": ["CustomerService"]}),
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("CustomerService", "EXTENDS", "BaseService") in kuzu.edges
    assert ("BaseService", "HAS_METHOD", "BaseService.run") in kuzu.edges
    assert ("CustomerService", "HAS_METHOD", "CustomerService.run") in kuzu.edges
    assert ("CustomerService.run", "METHOD_OVERRIDES", "BaseService.run") in kuzu.edges


def test_build_graph_adds_member_property_ownership_edges() -> None:
    files = [
        FileRecord(path="src/ProductDto.cs", language="csharp", size_bytes=1, sha256="a", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/ProductDto.cs": [
            SymbolRecord(name="ProductDto", qualified_name="MyApp.ProductDto", kind="class", start_line=1, end_line=4, signature="MyApp.ProductDto", metadata={"imports": [], "calls": [], "references": []}),
            SymbolRecord(name="InTransitStock", qualified_name="MyApp.ProductDto.InTransitStock", kind="property", start_line=2, end_line=2, signature="int InTransitStock", metadata={"imports": [], "calls": [], "references": [], "parent_chain": ["MyApp.ProductDto"]}),
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("MyApp.ProductDto", "HAS_PROPERTY", "MyApp.ProductDto.InTransitStock") in kuzu.edges


def test_build_graph_adds_explicit_native_header_implementation_edges() -> None:
    files = [
        FileRecord(path="src/engine.h", language="c", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="src/engine.c", language="c", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/engine.h": [
            SymbolRecord(
                name="run_engine",
                qualified_name="engine.header.run_engine",
                kind="function",
                start_line=1,
                end_line=1,
                signature="engine::run_engine(void)",
                metadata={
                    "imports": [],
                    "calls": [],
                    "references": [],
                    "translation_unit": "engine",
                    "file_role": "header",
                    "is_declaration": True,
                    "source_associations": ["src/engine.c"],
                },
            )
        ],
        "src/engine.c": [
            SymbolRecord(
                name="run_engine",
                qualified_name="engine.source.run_engine",
                kind="function",
                start_line=3,
                end_line=5,
                signature="engine::run_engine(void)",
                metadata={
                    "imports": [],
                    "calls": [],
                    "references": [],
                    "translation_unit": "engine",
                    "file_role": "source",
                    "is_definition": True,
                    "source_associations": ["src/engine.h"],
                },
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("engine.header.run_engine", "DECLARES_IN_HEADER", "engine.source.run_engine") in kuzu.edges
    assert ("engine.source.run_engine", "DEFINES_IMPLEMENTATION", "engine.header.run_engine") in kuzu.edges


def test_build_graph_adds_native_include_edges() -> None:
    files = [
        FileRecord(path="include/engine.h", language="c", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="src/app.c", language="c", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "include/engine.h": [
            SymbolRecord(
                name="run_engine",
                qualified_name="run_engine",
                kind="function",
                start_line=1,
                end_line=1,
                signature="run_engine(void)",
                metadata={"imports": [], "calls": [], "references": [], "language": "c"},
            )
        ],
        "src/app.c": [
            SymbolRecord(
                name="main",
                qualified_name="main",
                kind="function",
                start_line=3,
                end_line=5,
                signature="main(void)",
                metadata={"imports": ["engine.h", "run_engine"], "calls": ["run_engine"], "references": [], "language": "c"},
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("main", "INCLUDES", "run_engine") in kuzu.edges


def test_build_graph_adds_csharp_dependency_injection_edges() -> None:
    files = [
        FileRecord(path="Program.cs", language="csharp", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="Services.cs", language="csharp", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "Program.cs": [
            SymbolRecord(
                name="dependency_injection",
                qualified_name="dependency_injection",
                kind="module",
                start_line=1,
                end_line=3,
                signature="dependency_injection",
                metadata={
                    "imports": [],
                    "calls": [],
                    "references": [],
                    "di_registrations": [
                        {"service": "IProductService", "implementation": "ProductService", "lifetime": "scoped"}
                    ],
                },
            )
        ],
        "Services.cs": [
            SymbolRecord(name="IProductService", qualified_name="MyApp.IProductService", kind="interface", start_line=1, end_line=2, signature="MyApp.IProductService", metadata={"imports": [], "calls": [], "references": []}),
            SymbolRecord(name="ProductService", qualified_name="MyApp.ProductService", kind="class", start_line=4, end_line=8, signature="MyApp.ProductService", metadata={"imports": [], "calls": [], "references": []}),
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("MyApp.IProductService", "INJECTS", "MyApp.ProductService") in kuzu.edges


def test_build_graph_adds_csharp_constructor_service_edges_for_class_and_methods() -> None:
    files = [
        FileRecord(path="Controllers/ProductsController.cs", language="csharp", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="Services.cs", language="csharp", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "Controllers/ProductsController.cs": [
            SymbolRecord(
                name="ProductsController",
                qualified_name="MyApp.ProductsController",
                kind="class",
                start_line=1,
                end_line=8,
                signature="MyApp.ProductsController",
                metadata={"imports": [], "calls": [], "references": [], "constructor_dependencies": ["IProductService"]},
            ),
            SymbolRecord(
                name="GetTrend",
                qualified_name="MyApp.ProductsController.GetTrend",
                kind="method",
                start_line=5,
                end_line=6,
                signature="MyApp.ProductsController.GetTrend",
                metadata={"imports": [], "calls": [], "references": [], "parent_chain": ["MyApp.ProductsController"]},
            ),
        ],
        "Services.cs": [
            SymbolRecord(name="IProductService", qualified_name="MyApp.IProductService", kind="interface", start_line=1, end_line=2, signature="MyApp.IProductService", metadata={"imports": [], "calls": [], "references": []}),
            SymbolRecord(name="ProductService", qualified_name="MyApp.ProductService", kind="class", start_line=4, end_line=8, signature="MyApp.ProductService", metadata={"imports": [], "calls": [], "references": []}),
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("MyApp.ProductsController", "USES_SERVICE", "MyApp.IProductService") in kuzu.edges
    assert ("MyApp.ProductsController.GetTrend", "USES_SERVICE", "MyApp.IProductService") in kuzu.edges


def test_build_graph_prefers_associated_file_for_duplicate_import_names() -> None:
    files = [
        FileRecord(path="src/hooks/useCustomer.ts", language="typescript", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="src/legacy/useCustomer.ts", language="typescript", size_bytes=1, sha256="b", modified_time=0.0),
        FileRecord(path="src/ui/CustomerView.tsx", language="typescript", size_bytes=1, sha256="c", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/hooks/useCustomer.ts": [SymbolRecord(name="useCustomer", qualified_name="src.hooks.useCustomer.useCustomer", kind="hook", start_line=1, end_line=2, signature="useCustomer", metadata={"imports": [], "calls": [], "references": []})],
        "src/legacy/useCustomer.ts": [SymbolRecord(name="useCustomer", qualified_name="src.legacy.useCustomer.useCustomer", kind="hook", start_line=1, end_line=2, signature="useCustomer", metadata={"imports": [], "calls": [], "references": []})],
        "src/ui/CustomerView.tsx": [
            SymbolRecord(
                name="CustomerView",
                qualified_name="src.ui.CustomerView.CustomerView",
                kind="component",
                start_line=1,
                end_line=4,
                signature="CustomerView",
                metadata={
                    "imports": ["useCustomer"],
                    "calls": ["useCustomer"],
                    "references": ["useCustomer"],
                    "source_associations": ["src/hooks/useCustomer.ts"],
                },
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("src.ui.CustomerView.CustomerView", "IMPORTS", "src.hooks.useCustomer.useCustomer") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "CALLS", "src.hooks.useCustomer.useCustomer") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "REFERENCES", "src.hooks.useCustomer.useCustomer") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "IMPORTS", "src.legacy.useCustomer.useCustomer") not in kuzu.edges


def test_build_graph_uses_transitive_barrel_source_associations() -> None:
    files = [
        FileRecord(path="src/components/CustomerPanel.ts", language="typescript", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="src/components/index.ts", language="typescript", size_bytes=1, sha256="b", modified_time=0.0),
        FileRecord(path="src/ui/CustomerView.tsx", language="typescript", size_bytes=1, sha256="c", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/components/CustomerPanel.ts": [SymbolRecord(name="CustomerPanel", qualified_name="src.components.CustomerPanel.CustomerPanel", kind="component", start_line=1, end_line=2, signature="CustomerPanel", metadata={"imports": [], "calls": [], "references": []})],
        "src/components/index.ts": [
            SymbolRecord(
                name="exports",
                qualified_name="src.components.index.exports",
                kind="module",
                start_line=1,
                end_line=1,
                signature="exports",
                metadata={
                    "imports": ["../components/CustomerPanel", "CustomerPanel"],
                    "calls": [],
                    "references": [],
                    "source_associations": ["src/components/CustomerPanel.ts"],
                    "re_exports": [{"module": "../components/CustomerPanel", "exported_names": [], "aliases": {}, "export_all": True}],
                },
            )
        ],
        "src/ui/CustomerView.tsx": [
            SymbolRecord(
                name="CustomerView",
                qualified_name="src.ui.CustomerView.CustomerView",
                kind="component",
                start_line=1,
                end_line=4,
                signature="CustomerView",
                metadata={
                    "imports": ["CustomerPanel"],
                    "calls": ["CustomerPanel"],
                    "references": ["CustomerPanel"],
                    "source_associations": ["src/components/index.ts"],
                },
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("src.ui.CustomerView.CustomerView", "IMPORTS", "src.components.CustomerPanel.CustomerPanel") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "CALLS", "src.components.CustomerPanel.CustomerPanel") in kuzu.edges


def test_build_graph_resolves_default_import_to_default_export_symbol() -> None:
    files = [
        FileRecord(path="src/components/CustomerPanel.ts", language="typescript", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="src/ui/CustomerView.tsx", language="typescript", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/components/CustomerPanel.ts": [
            SymbolRecord(
                name="CustomerPanel",
                qualified_name="src.components.CustomerPanel.CustomerPanel",
                kind="component",
                start_line=1,
                end_line=2,
                signature="CustomerPanel",
                metadata={"imports": [], "calls": [], "references": [], "default_export": True, "exported": True},
            ),
            SymbolRecord(
                name="exports",
                qualified_name="src.components.CustomerPanel.exports",
                kind="module",
                start_line=1,
                end_line=2,
                signature="exports",
                metadata={"imports": [], "calls": [], "references": [], "export_names": ["CustomerPanel"], "exported": True},
            ),
        ],
        "src/ui/CustomerView.tsx": [
            SymbolRecord(
                name="CustomerView",
                qualified_name="src.ui.CustomerView.CustomerView",
                kind="component",
                start_line=1,
                end_line=4,
                signature="CustomerView",
                metadata={
                    "imports": ["CustomerPanel"],
                    "calls": ["CustomerPanel"],
                    "references": ["CustomerPanel"],
                    "import_aliases": {"CustomerPanel": "default"},
                    "source_associations": ["src/components/CustomerPanel.ts"],
                },
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("src.ui.CustomerView.CustomerView", "IMPORTS", "src.components.CustomerPanel.CustomerPanel") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "CALLS", "src.components.CustomerPanel.CustomerPanel") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "REFERENCES", "src.components.CustomerPanel.CustomerPanel") in kuzu.edges


def test_build_graph_resolves_namespace_import_to_module_symbol() -> None:
    files = [
        FileRecord(path="src/hooks/useCustomer.ts", language="typescript", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="src/ui/CustomerView.tsx", language="typescript", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/hooks/useCustomer.ts": [
            SymbolRecord(
                name="useCustomer",
                qualified_name="src.hooks.useCustomer.useCustomer",
                kind="hook",
                start_line=1,
                end_line=2,
                signature="useCustomer",
                metadata={"imports": [], "calls": [], "references": [], "default_export": False, "exported": True},
            ),
            SymbolRecord(
                name="exports",
                qualified_name="src.hooks.useCustomer.exports",
                kind="module",
                start_line=1,
                end_line=2,
                signature="exports",
                metadata={"imports": [], "calls": [], "references": [], "export_names": ["useCustomer"], "exported": True},
            ),
        ],
        "src/ui/CustomerView.tsx": [
            SymbolRecord(
                name="CustomerView",
                qualified_name="src.ui.CustomerView.CustomerView",
                kind="component",
                start_line=1,
                end_line=4,
                signature="CustomerView",
                metadata={
                    "imports": ["CustomerHooks"],
                    "calls": ["CustomerHooks"],
                    "references": ["CustomerHooks"],
                    "import_aliases": {"CustomerHooks": "__namespace__"},
                    "source_associations": ["src/hooks/useCustomer.ts"],
                },
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("src.ui.CustomerView.CustomerView", "IMPORTS", "src.hooks.useCustomer.exports") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "CALLS", "src.hooks.useCustomer.exports") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "REFERENCES", "src.hooks.useCustomer.exports") in kuzu.edges


def test_build_graph_resolves_namespace_member_to_exported_symbol() -> None:
    files = [
        FileRecord(path="src/hooks/useCustomer.ts", language="typescript", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="src/ui/CustomerView.tsx", language="typescript", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/hooks/useCustomer.ts": [
            SymbolRecord(
                name="useCustomer",
                qualified_name="src.hooks.useCustomer.useCustomer",
                kind="hook",
                start_line=1,
                end_line=2,
                signature="useCustomer",
                metadata={"imports": [], "calls": [], "references": [], "exported": True},
            ),
            SymbolRecord(
                name="exports",
                qualified_name="src.hooks.useCustomer.exports",
                kind="module",
                start_line=1,
                end_line=2,
                signature="exports",
                metadata={"imports": [], "calls": [], "references": [], "export_names": ["useCustomer"], "exported": True},
            ),
        ],
        "src/ui/CustomerView.tsx": [
            SymbolRecord(
                name="CustomerView",
                qualified_name="src.ui.CustomerView.CustomerView",
                kind="component",
                start_line=1,
                end_line=4,
                signature="CustomerView",
                metadata={
                    "imports": ["CustomerHooks"],
                    "calls": ["CustomerHooks.useCustomer"],
                    "references": ["CustomerHooks.useCustomer"],
                    "import_aliases": {"CustomerHooks": "__namespace__"},
                    "source_associations": ["src/hooks/useCustomer.ts"],
                },
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("src.ui.CustomerView.CustomerView", "CALLS", "src.hooks.useCustomer.useCustomer") in kuzu.edges
    assert ("src.ui.CustomerView.CustomerView", "REFERENCES", "src.hooks.useCustomer.useCustomer") in kuzu.edges


def test_build_graph_links_object_pascal_uses_methods_and_properties() -> None:
    files = [
        FileRecord(path="SysUtils.pas", language="object_pascal", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="CustomerService.pas", language="object_pascal", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "SysUtils.pas": [
            SymbolRecord(
                name="SysUtils",
                qualified_name="SysUtils",
                kind="unit",
                start_line=1,
                end_line=1,
                signature="unit SysUtils",
                metadata={"imports": [], "calls": [], "references": [], "language": "object_pascal"},
            )
        ],
        "CustomerService.pas": [
            SymbolRecord(
                name="TCustomerService",
                qualified_name="CustomerService.TCustomerService",
                kind="class",
                start_line=5,
                end_line=7,
                signature="TCustomerService = class",
                metadata={"imports": ["SysUtils"], "calls": [], "references": [], "language": "object_pascal"},
            ),
            SymbolRecord(
                name="Load",
                qualified_name="CustomerService.TCustomerService.Load",
                kind="procedure",
                start_line=10,
                end_line=12,
                signature="procedure TCustomerService.Load;",
                metadata={"imports": ["SysUtils"], "calls": [], "references": [], "language": "object_pascal", "parent": "CustomerService.TCustomerService"},
            ),
            SymbolRecord(
                name="Name",
                qualified_name="CustomerService.Name",
                kind="property",
                start_line=8,
                end_line=8,
                signature="property Name",
                metadata={"imports": ["SysUtils"], "calls": [], "references": [], "language": "object_pascal", "parent": "CustomerService.TCustomerService"},
            ),
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("CustomerService.TCustomerService", "IMPORTS", "SysUtils") in kuzu.edges
    assert ("CustomerService.TCustomerService", "HAS_METHOD", "CustomerService.TCustomerService.Load") in kuzu.edges
    assert ("CustomerService.TCustomerService", "HAS_PROPERTY", "CustomerService.Name") in kuzu.edges


def test_build_graph_links_object_pascal_form_event_to_method() -> None:
    files = [
        FileRecord(path="MainForm.pas", language="object_pascal", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="MainForm.dfm", language="object_pascal_form", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "MainForm.pas": [
            SymbolRecord(
                name="TMainForm",
                qualified_name="MainForm.TMainForm",
                kind="class",
                start_line=1,
                end_line=3,
                signature="TMainForm = class",
                metadata={"imports": [], "calls": [], "references": [], "language": "object_pascal", "source_associations": ["MainForm.dfm"]},
            ),
            SymbolRecord(
                name="SaveButtonClick",
                qualified_name="MainForm.TMainForm.SaveButtonClick",
                kind="procedure",
                start_line=10,
                end_line=12,
                signature="procedure TMainForm.SaveButtonClick;",
                metadata={"imports": [], "calls": [], "references": [], "language": "object_pascal", "parent": "MainForm.TMainForm", "source_associations": ["MainForm.dfm"]},
            ),
        ],
        "MainForm.dfm": [
            SymbolRecord(
                name="SaveButtonClick",
                qualified_name="MainForm.OnClick.SaveButtonClick",
                kind="event_handler_binding",
                start_line=4,
                end_line=4,
                signature="OnClick = SaveButtonClick",
                metadata={"imports": [], "calls": ["SaveButtonClick"], "references": ["SaveButtonClick"], "language": "object_pascal_form", "source_associations": ["MainForm.pas"]},
            ),
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("MainForm.OnClick.SaveButtonClick", "CALLS", "MainForm.TMainForm.SaveButtonClick") in kuzu.edges
    assert ("MainForm.TMainForm", "HAS_METHOD", "MainForm.TMainForm.SaveButtonClick") in kuzu.edges
    assert ("MainForm.OnClick.SaveButtonClick", "REFERENCES", "MainForm.TMainForm.SaveButtonClick") in kuzu.edges


def test_build_graph_links_object_pascal_project_to_owned_units_and_forms() -> None:
    files = [
        FileRecord(path="CustomerApp.dproj", language="object_pascal_project", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="src/CustomerService.pas", language="object_pascal", size_bytes=1, sha256="b", modified_time=0.0),
        FileRecord(path="forms/MainForm.dfm", language="object_pascal_form", size_bytes=1, sha256="c", modified_time=0.0),
    ]
    symbols_by_file = {
        "CustomerApp.dproj": [
            SymbolRecord(
                name="CustomerApp",
                qualified_name="CustomerApp",
                kind="project",
                start_line=1,
                end_line=1,
                signature="CustomerApp",
                metadata={
                    "language": "object_pascal_project",
                    "imports": [],
                    "calls": [],
                    "references": [],
                    "project_references": ["CustomerService.pas", "MainForm.dfm"],
                    "project_ownership_surface": True,
                },
            )
        ],
        "src/CustomerService.pas": [
            SymbolRecord(
                name="CustomerService",
                qualified_name="CustomerService",
                kind="unit",
                start_line=1,
                end_line=1,
                signature="unit CustomerService;",
                metadata={"language": "object_pascal", "imports": [], "calls": [], "references": []},
            )
        ],
        "forms/MainForm.dfm": [
            SymbolRecord(
                name="MainForm",
                qualified_name="MainForm.MainForm",
                kind="component",
                start_line=1,
                end_line=1,
                signature="object MainForm: TMainForm",
                metadata={"language": "object_pascal_form", "imports": [], "calls": [], "references": []},
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("CustomerApp", "REFERENCES", "CustomerService") in kuzu.edges
    assert ("CustomerApp", "OWNS", "CustomerService") in kuzu.edges
    assert ("CustomerApp", "REFERENCES", "MainForm.MainForm") in kuzu.edges
    assert ("CustomerApp", "OWNS", "MainForm.MainForm") in kuzu.edges


def test_build_graph_links_object_pascal_inheritance_and_overrides() -> None:
    files = [FileRecord(path="Forms.pas", language="object_pascal", size_bytes=1, sha256="a", modified_time=0.0)]
    symbols_by_file = {
        "Forms.pas": [
            SymbolRecord(
                name="TBaseForm",
                qualified_name="Forms.TBaseForm",
                kind="class",
                start_line=1,
                end_line=3,
                signature="TBaseForm = class(TForm)",
                metadata={"language": "object_pascal", "imports": [], "calls": [], "references": [], "extends": ["TForm"]},
            ),
            SymbolRecord(
                name="Render",
                qualified_name="Forms.TBaseForm.Render",
                kind="procedure",
                start_line=4,
                end_line=4,
                signature="procedure Render;",
                metadata={"language": "object_pascal", "imports": [], "calls": [], "references": [], "parent": "Forms.TBaseForm"},
            ),
            SymbolRecord(
                name="TCustomerForm",
                qualified_name="Forms.TCustomerForm",
                kind="class",
                start_line=6,
                end_line=8,
                signature="TCustomerForm = class(TBaseForm, IPrintable)",
                metadata={"language": "object_pascal", "imports": [], "calls": [], "references": [], "extends": ["TBaseForm"], "implements": ["IPrintable"]},
            ),
            SymbolRecord(
                name="Render",
                qualified_name="Forms.TCustomerForm.Render",
                kind="procedure",
                start_line=9,
                end_line=9,
                signature="procedure Render;",
                metadata={"language": "object_pascal", "imports": [], "calls": [], "references": [], "parent": "Forms.TCustomerForm"},
            ),
            SymbolRecord(
                name="IPrintable",
                qualified_name="Forms.IPrintable",
                kind="type",
                start_line=11,
                end_line=12,
                signature="IPrintable = interface",
                metadata={"language": "object_pascal", "imports": [], "calls": [], "references": []},
            ),
        ]
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("Forms.TCustomerForm", "EXTENDS", "Forms.TBaseForm") in kuzu.edges
    assert ("Forms.TCustomerForm", "IMPLEMENTS", "Forms.IPrintable") in kuzu.edges
    assert ("Forms.TCustomerForm.Render", "METHOD_OVERRIDES", "Forms.TBaseForm.Render") in kuzu.edges


def test_build_graph_pairs_object_pascal_class_method_declaration_and_definition() -> None:
    files = [FileRecord(path="CustomerService.pas", language="object_pascal", size_bytes=1, sha256="a", modified_time=0.0)]
    symbols_by_file = {
        "CustomerService.pas": [
            SymbolRecord(
                name="TCustomerService",
                qualified_name="CustomerService.TCustomerService",
                kind="class",
                start_line=1,
                end_line=5,
                signature="TCustomerService = class",
                metadata={"language": "object_pascal", "imports": [], "calls": [], "references": []},
            ),
            SymbolRecord(
                name="LoadCustomer",
                qualified_name="CustomerService.LoadCustomer",
                kind="procedure",
                start_line=3,
                end_line=3,
                signature="procedure LoadCustomer;",
                metadata={
                    "language": "object_pascal",
                    "imports": [],
                    "calls": [],
                    "references": [],
                    "parent": "CustomerService.TCustomerService",
                    "is_declaration": True,
                    "declaration_key": "CustomerService.TCustomerService.LoadCustomer",
                },
            ),
            SymbolRecord(
                name="LoadCustomer",
                qualified_name="CustomerService.TCustomerService.LoadCustomer",
                kind="procedure",
                start_line=8,
                end_line=10,
                signature="procedure TCustomerService.LoadCustomer;",
                metadata={
                    "language": "object_pascal",
                    "imports": [],
                    "calls": [],
                    "references": [],
                    "parent": "CustomerService.TCustomerService",
                    "is_definition": True,
                    "declaration_key": "CustomerService.TCustomerService.LoadCustomer",
                },
            ),
        ]
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("CustomerService.LoadCustomer", "DECLARES", "CustomerService.TCustomerService.LoadCustomer") in kuzu.edges
    assert ("CustomerService.TCustomerService", "HAS_METHOD", "CustomerService.LoadCustomer") in kuzu.edges
    assert ("CustomerService.TCustomerService", "HAS_METHOD", "CustomerService.TCustomerService.LoadCustomer") in kuzu.edges


def test_build_graph_links_object_pascal_form_component_hierarchy_and_property_refs() -> None:
    files = [FileRecord(path="MainForm.lfm", language="object_pascal_form", size_bytes=1, sha256="a", modified_time=0.0)]
    symbols_by_file = {
        "MainForm.lfm": [
            SymbolRecord(
                name="MainForm",
                qualified_name="MainForm.MainForm",
                kind="component",
                start_line=1,
                end_line=1,
                signature="inherited MainForm: TMainForm",
                metadata={"language": "object_pascal_form", "imports": [], "calls": [], "references": ["TMainForm"], "inherited_component": True},
            ),
            SymbolRecord(
                name="Panel1",
                qualified_name="MainForm.Panel1",
                kind="component",
                start_line=2,
                end_line=2,
                signature="object Panel1: TPanel",
                metadata={"language": "object_pascal_form", "imports": [], "calls": [], "references": ["TPanel"], "component_parent": "MainForm.MainForm"},
            ),
            SymbolRecord(
                name="DataSource1",
                qualified_name="MainForm.DataSource1",
                kind="component",
                start_line=3,
                end_line=3,
                signature="object DataSource1: TDataSource",
                metadata={"language": "object_pascal_form", "imports": [], "calls": [], "references": ["TDataSource"], "component_parent": "MainForm.MainForm"},
            ),
            SymbolRecord(
                name="CustomerName",
                qualified_name="MainForm.CustomerName",
                kind="component",
                start_line=4,
                end_line=4,
                signature="object CustomerName: TDBEdit",
                metadata={
                    "language": "object_pascal_form",
                    "imports": [],
                    "calls": [],
                    "references": ["TDBEdit", "DataSource1"],
                    "component_parent": "MainForm.Panel1",
                    "component_properties": [{"property": "DataSource", "value": "DataSource1"}],
                },
            ),
        ]
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("MainForm.MainForm", "HAS_COMPONENT", "MainForm.Panel1") in kuzu.edges
    assert ("MainForm.MainForm", "HAS_COMPONENT", "MainForm.DataSource1") in kuzu.edges
    assert ("MainForm.Panel1", "HAS_COMPONENT", "MainForm.CustomerName") in kuzu.edges
    assert ("MainForm.CustomerName", "REFERENCES", "MainForm.DataSource1") in kuzu.edges


def test_build_graph_links_object_pascal_includes() -> None:
    files = [
        FileRecord(path="CustomerService.pas", language="object_pascal", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="Shared.inc", language="assembly_include", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "CustomerService.pas": [
            SymbolRecord(
                name="CustomerService",
                qualified_name="CustomerService",
                kind="unit",
                start_line=1,
                end_line=10,
                signature="unit CustomerService;",
                metadata={"language": "object_pascal", "imports": [], "calls": [], "references": [], "include_files": ["Shared.inc"]},
            )
        ],
        "Shared.inc": [
            SymbolRecord(
                name="Shared",
                qualified_name="Shared",
                kind="include",
                start_line=1,
                end_line=5,
                signature="Shared.inc",
                metadata={"language": "assembly_include", "imports": [], "calls": [], "references": []},
            )
        ],
    }
    kuzu = _Kuzu()

    build_graph(kuzu, files, symbols_by_file)

    assert ("CustomerService", "INCLUDES", "Shared") in kuzu.edges
    assert ("CustomerService", "REFERENCES", "Shared") in kuzu.edges
