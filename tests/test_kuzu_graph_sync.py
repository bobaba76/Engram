from models.entity_models import FileRecord, SymbolRecord
from indexing.graph_builder import build_graph
from storage.kuzu_store import KuzuStore


def test_kuzu_delete_index_data_for_files_removes_owned_symbols_and_edges(tmp_path) -> None:
    store = KuzuStore(tmp_path / "graph.kuzu")
    try:
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
        assert store.edges_for_source("src.a.a", relation="CALLS")

        store.delete_index_data_for_files(["src/a.py"])

        assert store.edges_for_source("src.a.a") == []
        assert store.edges_for_target("src.a.a") == []
        assert store.edges_for_target("src.b.b", relation="CALLS") == []
        report = store.graph_integrity_report()
        assert report["ok"] is True
        assert report["symbols_missing_file_node"] == []
        assert report["symbols_missing_defines_edge"] == []
    finally:
        store.close()


def test_graph_integrity_ignores_synthetic_property_nodes_without_defines_edges(tmp_path) -> None:
    store = KuzuStore(tmp_path / "graph.kuzu")
    try:
        files = [
            FileRecord(path="src/a.py", language="python", size_bytes=1, sha256="a", modified_time=0.0),
        ]
        symbols_by_file = {
            "src/a.py": [
                SymbolRecord(
                    name="a",
                    qualified_name="src.a.a",
                    kind="function",
                    start_line=1,
                    end_line=1,
                    metadata={"calls": [], "imports": [], "references": [], "accesses": ["self.value"]},
                )
            ],
        }

        build_graph(store, files, symbols_by_file)
        report = store.graph_integrity_report()

        assert report["ok"] is True
        assert report["symbols_missing_defines_edge"] == []
    finally:
        store.close()
