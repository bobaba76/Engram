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
