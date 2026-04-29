from pathlib import Path

from services.change_report_service import change_impact_report
from services.impact_service import analyze_impact


class _Duck:
    class _Files:
        def fetch_all(self):
            return []

    class _Processes:
        def fetch_clusters(self, limit=100):
            return []

    files = _Files()
    processes = _Processes()

    def fetch_symbols_for_target(self, target, limit=25):
        mapping = {
            "frontend.components.CustomerView.CustomerView": [
                {
                    "uid": "1",
                    "name": "CustomerView",
                    "qualified_name": "frontend.components.CustomerView.CustomerView",
                    "kind": "component",
                    "file_path": "frontend/components/CustomerView.tsx",
                }
            ],
            "frontend.hooks.useCustomer.useCustomer": [
                {
                    "uid": "2",
                    "name": "useCustomer",
                    "qualified_name": "frontend.hooks.useCustomer.useCustomer",
                    "kind": "hook",
                    "file_path": "frontend/hooks/useCustomer.ts",
                }
            ],
        }
        return mapping.get(target, [])

    def fetch_process_clusters_for_symbol(self, symbol_name, limit=8):
        return []

    def fetch_symbols_for_file(self, file_path):
        if file_path == "frontend/components/CustomerView.tsx":
            return [
                {
                    "name": "CustomerView",
                    "qualified_name": "frontend.components.CustomerView.CustomerView",
                    "kind": "component",
                    "start_line": 1,
                    "end_line": 20,
                }
            ]
        if file_path == "frontend/hooks/useCustomer.ts":
            return [
                {
                    "name": "useCustomer",
                    "qualified_name": "frontend.hooks.useCustomer.useCustomer",
                    "kind": "hook",
                    "start_line": 1,
                    "end_line": 12,
                }
            ]
        return []


class _Kuzu:
    def edges_for_target(self, node, relation=None):
        if node == "frontend.components.CustomerView.CustomerView" and relation == "CALLS":
            return [
                {
                    "source": "frontend.hooks.useCustomer.useCustomer",
                    "relation": "CALLS",
                    "target": "frontend.components.CustomerView.CustomerView",
                }
            ]
        return []

    def edges_for_source(self, node, relation=None):
        return []


class _ChangesDuck(_Duck):
    pass


def test_analyze_impact_summarizes_frontend_graph_paths(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.impact_service.resolve_candidates",
        lambda duckdb_store, target="", file_path=None, kind=None, symbol_uid_value=None, limit=25: [
            {
                "score": 1.0,
                "confidence": "high",
                "symbol": {
                    "uid": "1",
                    "name": "CustomerView",
                    "qualified_name": "frontend.components.CustomerView.CustomerView",
                    "kind": "component",
                    "file_path": "frontend/components/CustomerView.tsx",
                },
                "relevance": "direct symbol match",
            }
        ],
    )

    result = analyze_impact(_Duck(), _Kuzu(), target="CustomerView", direction="upstream", max_depth=2)

    assert result["frontend_graph"]["has_indirect_frontend_path"] is True
    assert "frontend/components/CustomerView.tsx" in result["frontend_graph"]["top_frontend_files"]
    assert result["compact_summary"]["frontend_graph"]["frontend_graph_edge_count"] >= 1
    assert "indirect rather than lexical" in result["frontend_graph"]["summary"]


def test_change_impact_report_propagates_frontend_graph_signal(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.change_report_service.detect_changes",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref=None: {
            "risk": "LOW",
            "changed_files": ["frontend/components/CustomerView.tsx"],
            "changed_symbols": [{"qualified_name": "frontend.components.CustomerView.CustomerView", "name": "CustomerView"}],
        },
    )
    monkeypatch.setattr(
        "services.change_report_service.analyze_impact",
        lambda duckdb_store, kuzu_store, target="", direction="upstream", max_depth=2: {
            "risk": "MEDIUM",
            "frontend_graph": {
                "frontend_file_count": 2,
                "top_frontend_files": ["frontend/components/CustomerView.tsx", "frontend/hooks/useCustomer.ts"],
                "frontend_graph_edge_count": 2,
                "top_relations": {"CALLS": 2},
                "has_indirect_frontend_path": True,
                "summary": "Impact includes graph-linked frontend TS/TSX paths, so implementation fallout may be indirect rather than lexical.",
            },
            "compact_summary": {"target": "frontend.components.CustomerView.CustomerView", "frontend_graph": {"has_indirect_frontend_path": True}},
        },
    )
    monkeypatch.setattr(
        "services.change_report_service.app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=5: {
            "frontend_graph": {
                "frontend_file_count": 1,
                "top_frontend_files": ["frontend/components/CustomerView.tsx"],
                "frontend_graph_edge_count": 1,
                "top_relations": {"IMPORTS": 1},
                "has_indirect_frontend_path": True,
                "summary": "Frontend implementation paths include graph-linked TS/TSX files, so behavior may be discovered indirectly.",
            },
            "compact_summary": {
                "frontend_graph": {
                    "frontend_file_count": 1,
                    "top_frontend_files": ["frontend/components/CustomerView.tsx"],
                    "frontend_graph_edge_count": 1,
                    "top_relations": {"IMPORTS": 1},
                    "has_indirect_frontend_path": True,
                    "summary": "Frontend implementation paths include graph-linked TS/TSX files, so behavior may be discovered indirectly.",
                }
            },
        },
    )
    monkeypatch.setattr(
        "services.change_report_service.suggest_tests_for_change",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref="": {"compact_summary": {"top_files": []}},
    )

    payload = change_impact_report(Path("C:/repo"), _ChangesDuck(), _Kuzu())

    assert payload["frontend_graph"]["has_indirect_frontend_path"] is True
    assert payload["frontend_graph"]["frontend_graph_edge_count"] == 3
    assert "frontend/hooks/useCustomer.ts" in payload["frontend_graph"]["top_frontend_files"]
    assert payload["compact_summary"]["frontend_graph"]["has_indirect_frontend_path"] is True


class _BroadImpactDuck(_Duck):
    def fetch_symbols_for_target(self, target, limit=25):
        if target == "popularHook":
            return [
                {
                    "uid": "root",
                    "name": "popularHook",
                    "qualified_name": "frontend.hooks.popularHook",
                    "kind": "hook",
                    "file_path": "frontend/hooks/popularHook.ts",
                }
            ]
        return super().fetch_symbols_for_target(target, limit=limit)


class _BroadImpactKuzu:
    def edges_for_target(self, node, relation=None):
        if node == "frontend.hooks.popularHook" and relation == "CALLS":
            return [
                {"source": f"frontend.components.Component{i}", "relation": "CALLS", "target": node}
                for i in range(120)
            ]
        if str(node).startswith("frontend.components.Component") and relation == "CALLS":
            suffix = str(node).rsplit("Component", 1)[-1]
            return [
                {"source": f"frontend.views.View{suffix}_{i}", "relation": "CALLS", "target": node}
                for i in range(120)
            ]
        return []

    def edges_for_source(self, node, relation=None):
        return []


def test_analyze_impact_caps_broad_queries_with_partial_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.impact_service.resolve_candidates",
        lambda duckdb_store, target="", file_path=None, kind=None, symbol_uid_value=None, limit=25: [
            {
                "score": 1.0,
                "confidence": "medium",
                "symbol": {
                    "uid": "root",
                    "name": "popularHook",
                    "qualified_name": "frontend.hooks.popularHook",
                    "kind": "hook",
                    "file_path": "frontend/hooks/popularHook.ts",
                },
                "relevance": "broad hook match",
            }
        ],
    )

    result = analyze_impact(_BroadImpactDuck(), _BroadImpactKuzu(), target="popularHook", direction="upstream", max_depth=3)

    assert result["status"] == "partial"
    assert result["guardrail"]["broad_query"] is True
    assert result["guardrail"]["traversal_truncated"] is True
    assert any("safety cap" in warning for warning in result["warnings"])
