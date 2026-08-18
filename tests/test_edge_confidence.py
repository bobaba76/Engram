from indexing.graph_builder import build_graph
from models.entity_models import FileRecord, SymbolRecord
from storage.kuzu_store import KuzuStore


def _build_simple_graph(tmp_path):
    store = KuzuStore(tmp_path / "graph.kuzu")
    files = [
        FileRecord(path="src/a.py", language="python", size_bytes=1, sha256="a", modified_time=0.0),
        FileRecord(path="src/b.py", language="python", size_bytes=1, sha256="b", modified_time=0.0),
    ]
    symbols_by_file = {
        "src/a.py": [
            SymbolRecord(
                name="a",
                qualified_name="src.a.a",
                kind="function",
                start_line=1,
                end_line=1,
                metadata={"calls": ["b"], "imports": [], "references": []},
            )
        ],
        "src/b.py": [
            SymbolRecord(
                name="b",
                qualified_name="src.b.b",
                kind="function",
                start_line=1,
                end_line=1,
                metadata={"calls": [], "imports": [], "references": []},
            )
        ],
    }
    build_graph(store, files, symbols_by_file)
    return store


def test_extracted_edges_carry_confidence_tag(tmp_path) -> None:
    store = _build_simple_graph(tmp_path)
    try:
        calls = store.edges_for_source("src.a.a", relation="CALLS")
        assert calls, "expected at least one CALLS edge"
        assert all(edge.get("confidence") == "EXTRACTED" for edge in calls)
        defines = store.edges_for_target("src.a.a", relation="DEFINES")
        assert defines
        assert defines[0]["confidence"] == "EXTRACTED"
    finally:
        store.close()


def test_inferred_edges_carry_inferred_tag(tmp_path) -> None:
    store = KuzuStore(tmp_path / "graph.kuzu")
    try:
        store.ensure_file("src/a.py")
        store.ensure_symbol("src.a.svc", "src/a.py", "class", 1, 10)
        store.ensure_symbol("src.a.impl", "src/a.py", "class", 11, 20)
        store.add_edge("src.a.svc", "INJECTS", "src.a.impl", confidence="INFERRED")
        edges = store.edges_for_source("src.a.svc", relation="INJECTS")
        assert edges
        assert edges[0]["confidence"] == "INFERRED"
    finally:
        store.close()


def test_add_edge_rejects_unknown_confidence_value(tmp_path) -> None:
    store = KuzuStore(tmp_path / "graph.kuzu")
    try:
        store.ensure_file("src/a.py")
        store.ensure_symbol("src.a.x", "src/a.py", "function", 1, 2)
        store.ensure_symbol("src.a.y", "src/a.py", "function", 3, 4)
        store.add_edge("src.a.x", "CALLS", "src.a.y", confidence="GARBAGE")
        edges = store.edges_for_source("src.a.x", relation="CALLS")
        assert edges
        # Unknown confidence values are normalized to the default.
        assert edges[0]["confidence"] == "EXTRACTED"
    finally:
        store.close()


def test_build_graph_tags_inferred_relations(tmp_path) -> None:
    """USES_SERVICE edges produced by graph_builder should be INFERRED."""
    store = KuzuStore(tmp_path / "graph.kuzu")
    try:
        files = [
            FileRecord(path="src/svc.py", language="python", size_bytes=1, sha256="a", modified_time=0.0),
        ]
        symbols_by_file = {
            "src/svc.py": [
                SymbolRecord(
                    name="Handler",
                    qualified_name="src.svc.Handler",
                    kind="class",
                    start_line=1,
                    end_line=20,
                    metadata={
                        "calls": [],
                        "imports": [],
                        "references": [],
                        "constructor_dependencies": ["Logger"],
                    },
                ),
                SymbolRecord(
                    name="Logger",
                    qualified_name="src.svc.Logger",
                    kind="class",
                    start_line=21,
                    end_line=30,
                    metadata={"calls": [], "imports": [], "references": []},
                ),
            ],
        }
        build_graph(store, files, symbols_by_file)
        uses_service = store.edges_for_source("src.svc.Handler", relation="USES_SERVICE")
        assert uses_service, "expected USES_SERVICE edge from constructor dependency"
        assert uses_service[0]["confidence"] == "INFERRED"
    finally:
        store.close()
