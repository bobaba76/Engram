from pathlib import Path

from services.feature_context_service import _chunk_feature_files, _feature_file_roles, _feature_query_terms, _process_feature_files, feature_context


class _Chunks:
    def fetch_for_target(self, target, limit=24):
        rows = {
            "indexing progress": [{"file_path": "app/coordinator.py"}],
            "progress reporting": [{"file_path": "services/run_summary_service.py"}],
        }
        return rows.get(target, [])


class _Processes:
    def fetch_clusters(self, limit=12, query=""):
        rows = {
            "indexing progress": [
                {
                    "cluster_id": "p1",
                    "name": "Index Progress Reporting",
                    "process_type": "pipeline",
                    "file_paths_json": '["app/coordinator.py"]',
                    "process_count": 2,
                }
            ],
            "progress reporting": [
                {
                    "cluster_id": "p2",
                    "name": "Run Summary Reporting",
                    "process_type": "reporting",
                    "file_paths_json": '["services/run_summary_service.py"]',
                    "process_count": 1,
                }
            ],
        }
        return rows.get(query, [])


class _Duck:
    chunks = _Chunks()
    processes = _Processes()

    def search_chunks_content(self, term, limit=24):
        rows = {
            "indexing progress": [{"file_path": "app/coordinator.py"}],
            "progress reporting": [{"file_path": "services/run_summary_service.py"}],
            "progress": [{"file_path": "services/realtime_index_service.py"}],
        }
        return rows.get(term, [])

    def fetch_symbols_for_file(self, file_path):
        return []

    def fetch_symbols_for_target(self, target, limit=24):
        return []


def test_feature_query_terms_builds_phrase_first_terms() -> None:
    terms = _feature_query_terms("trace the indexing progress reporting flow", limit=5)

    assert terms[0] == "trace the indexing progress reporting flow"
    assert "indexing progress" in terms
    assert "progress reporting" in terms


def test_chunk_feature_files_aggregates_phrase_and_token_matches() -> None:
    files = _chunk_feature_files(_Duck(), "trace the indexing progress reporting flow", limit=3)

    assert files[0] == "app/coordinator.py"
    assert "services/run_summary_service.py" in files


def test_process_feature_files_aggregates_multi_term_process_matches() -> None:
    files, processes = _process_feature_files(_Duck(), "trace the indexing progress reporting flow", limit=3)

    assert files[0] == "app/coordinator.py"
    assert any(process.get("name") == "Index Progress Reporting" for process in processes)


def test_feature_file_roles_detect_page_shared_ui_and_backend() -> None:
    assert "page" in _feature_file_roles("frontend/pages/RegionalOverviewLandingPage.js")
    assert "shared_ui" in _feature_file_roles("frontend/components/PeriodSelector.js")
    assert "backend" in _feature_file_roles("backend/services/period_service.py")


def test_feature_context_exposes_role_groups(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "services.feature_context_service.app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=12: {
            "files": [
                {"file_path": "frontend/pages/RegionalOverviewLandingPage.js"},
                {"file_path": "frontend/components/PeriodSelector.js"},
                {"file_path": "backend/services/period_service.py"},
            ],
            "routes": ["/api/regional-overview"],
            "processes": [],
            "graph_edges": [],
            "compact_summary": {"top_routes": ["/api/regional-overview"]},
        },
    )

    result = feature_context(tmp_path, _Duck(), object(), feature="regional overview period selector", limit=6)

    assert "frontend/pages/RegionalOverviewLandingPage.js" in result["role_groups"]["page_files"]
    assert "frontend/components/PeriodSelector.js" in result["role_groups"]["shared_ui_files"]
    assert "backend/services/period_service.py" in result["role_groups"]["backend_files"]
    assert "frontend/pages/RegionalOverviewLandingPage.js" in result["compact_summary"]["role_groups"]["page_files"]


def test_feature_context_lightweight_skips_app_context(monkeypatch, tmp_path: Path) -> None:
    calls = {"app": 0}

    monkeypatch.setattr(
        "services.feature_context_service.app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=12: calls.__setitem__("app", calls["app"] + 1) or {},
    )

    result = feature_context(tmp_path, _Duck(), object(), feature="regional overview period selector", limit=6, lightweight=True)

    assert calls["app"] == 0
    assert result["partial"] is True
    assert result["guardrail"]["app_context_skipped"] is True
