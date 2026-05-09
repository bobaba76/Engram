from pathlib import Path

from services.test_intelligence_service import find_tests_for_target, suggest_tests_for_change


class _Symbols:
    def fetch_for_target(self, target, limit=60):
        return [
            {
                "file_path": "tests/test_graph_builder.py",
                "name": "test_graph_builder",
                "qualified_name": "test_build_graph_adds_frontend_api_contract_edges",
                "kind": "function",
            },
            {
                "file_path": "tests/test_unrelated.py",
                "name": "test_unrelated",
                "qualified_name": "test_unrelated",
                "kind": "function",
            },
        ]


class _Files:
    def fetch_all(self):
        return [
            {"path": "tests/test_graph_builder.py"},
            {"path": "tests/test_unrelated.py"},
            {"path": "tests/test_symbol_context_service.py"},
        ]


class _Duck:
    symbols = _Symbols()
    files = _Files()


class _Kuzu:
    pass


def test_find_tests_for_target_uses_csharp_test_naming_conventions(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.test_intelligence_service.resolve_candidates",
        lambda duckdb_store, target="", limit=5: [
            {
                "symbol": {
                    "qualified_name": "MyApp.Controllers.ProductsController",
                    "name": "ProductsController",
                    "file_path": "backend/Controllers/ProductsController.cs",
                }
            }
        ],
    )

    class _FilesWithCSharpTests(_Files):
        def fetch_all(self):
            return [
                {"path": "backend.Tests/ProductsControllerTests.cs"},
                {"path": "backend.Tests/UnrelatedTests.cs"},
            ]

    class _DuckWithCSharpTests(_Duck):
        files = _FilesWithCSharpTests()

    payload = find_tests_for_target(_DuckWithCSharpTests(), "ProductsController", limit=8)

    assert payload["compact_summary"]["top_files"] == ["backend.Tests/ProductsControllerTests.cs"]
    assert payload["compact_results"][0]["why_relevant"] == "C# test naming convention match"


def test_find_tests_for_target_uses_native_test_naming_conventions(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.test_intelligence_service.resolve_candidates",
        lambda duckdb_store, target="", limit=5: [
            {
                "symbol": {
                    "qualified_name": "run_engine",
                    "name": "run_engine",
                    "file_path": "src/engine.c",
                }
            }
        ],
    )

    class _FilesWithNativeTests(_Files):
        def fetch_all(self):
            return [
                {"path": "tests/test_engine.cpp"},
                {"path": "tests/test_unrelated.cpp"},
            ]

    class _DuckWithNativeTests(_Duck):
        files = _FilesWithNativeTests()

    payload = find_tests_for_target(_DuckWithNativeTests(), "run_engine", limit=8)

    assert payload["compact_summary"]["top_files"] == ["tests/test_engine.cpp"]
    assert payload["compact_results"][0]["why_relevant"] == "C/C++ test naming convention match"


def test_suggest_tests_filters_zero_overlap_fallback_noise(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.test_intelligence_service.resolve_candidates",
        lambda duckdb_store, target="", limit=5: [
            {
                "symbol": {
                    "qualified_name": "build_graph",
                    "name": "build_graph",
                    "file_path": "indexing/graph_builder.py",
                }
            }
        ],
    )
    changes = {
        "changed_files": ["indexing/graph_builder.py"],
        "changed_symbols": [
            {
                "qualified_name": "build_graph",
                "name": "build_graph",
                "file_path": "indexing/graph_builder.py",
            }
        ],
        "compact_summary": {"changed_file_count": 1},
    }

    payload = suggest_tests_for_change(Path("C:/repo"), _Duck(), _Kuzu(), changes=changes)
    files = [item["file"] for item in payload["recommended_tests"]]

    assert "tests/test_graph_builder.py" in files
    assert "tests/test_symbol_context_service.py" not in files


def test_suggest_tests_uses_subsystem_map_without_weak_noise(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.test_intelligence_service.resolve_candidates",
        lambda duckdb_store, target="", limit=5: [
            {
                "symbol": {
                    "qualified_name": "extract_symbols",
                    "name": "extract_symbols",
                    "file_path": "indexing/parsers/python.py",
                }
            }
        ],
    )
    changes = {
        "focused_target": "indexing/parsers/python.py",
        "changed_files": ["indexing/parsers/python.py"],
        "changed_symbols": [
            {
                "qualified_name": "extract_symbols",
                "name": "extract_symbols",
                "file_path": "indexing/parsers/python.py",
            }
        ],
        "compact_summary": {"changed_file_count": 1},
    }

    payload = suggest_tests_for_change(Path("C:/repo"), _Duck(), _Kuzu(), changes=changes)
    files = [item["file"] for item in payload["recommended_tests"]]

    assert "tests/test_graph_builder.py" in files
    assert "tests/test_unrelated.py" not in files
    assert payload["compact_summary"]["target"] == "indexing/parsers/python.py"


def test_suggest_tests_prefers_subsystem_map_over_tangential_token_matches(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.test_intelligence_service.resolve_candidates",
        lambda duckdb_store, target="", limit=5: [
            {
                "symbol": {
                    "qualified_name": "change_impact_report",
                    "name": "change_impact_report",
                    "file_path": "services/change_report_service.py",
                }
            }
        ],
    )

    class _SymbolsWithTangential(_Symbols):
        def fetch_for_target(self, target, limit=60):
            return [
                {
                    "file_path": "tests/test_impact_change_frontend_signal.py",
                    "name": "test_change_impact_report",
                    "qualified_name": "test_change_impact_report",
                    "kind": "function",
                },
                {
                    "file_path": "tests/test_route_map_service.py",
                    "name": "test_route_map_mentions_change_report_service",
                    "qualified_name": "test_route_map_mentions_change_report_service",
                    "kind": "function",
                },
            ]

    class _FilesWithMapped(_Files):
        def fetch_all(self):
            return [
                {"path": "tests/test_impact_change_frontend_signal.py"},
                {"path": "tests/test_route_map_service.py"},
            ]

    class _DuckWithTangential(_Duck):
        symbols = _SymbolsWithTangential()
        files = _FilesWithMapped()

    changes = {
        "focused_target": "services/change_report_service.py",
        "changed_files": ["services/change_report_service.py"],
        "changed_symbols": [
            {
                "qualified_name": "change_impact_report",
                "name": "change_impact_report",
                "file_path": "services/change_report_service.py",
            }
        ],
        "compact_summary": {"changed_file_count": 1},
    }

    payload = suggest_tests_for_change(Path("C:/repo"), _DuckWithTangential(), _Kuzu(), changes=changes)

    assert [item["file"] for item in payload["recommended_tests"]] == ["tests/test_impact_change_frontend_signal.py"]


def test_find_tests_for_target_uses_subsystem_map_without_weak_noise(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.test_intelligence_service.resolve_candidates",
        lambda duckdb_store, target="", limit=5: [
            {
                "symbol": {
                    "qualified_name": "extract_symbols",
                    "name": "extract_symbols",
                    "file_path": "indexing/parsers/python.py",
                }
            }
        ],
    )

    payload = find_tests_for_target(_Duck(), "indexing/parsers/python.py", limit=8)

    assert payload["compact_summary"]["top_files"] == ["tests/test_graph_builder.py"]
    assert payload["compact_results"][0]["why_relevant"] == "mapped Coder subsystem coverage"
    assert payload["warnings"] == []
    assert payload["next_tools"] == []
