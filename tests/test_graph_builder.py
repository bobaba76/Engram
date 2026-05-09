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
    assert ("CustomerService.run", "METHOD_OVERRIDES", "BaseService.run") in kuzu.edges


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
