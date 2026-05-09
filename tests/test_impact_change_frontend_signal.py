from pathlib import Path

from services.change_report_service import change_impact_report
from services.detect_changes_service import _focused_followups, detect_changes
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

    def get_impacted_files(self, changed_files):
        return ["backend/services/product_trends.py", "frontend/src/components/ProductTrendModal.tsx"]


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
        lambda duckdb_store, kuzu_store, target="", file_path=None, direction="upstream", max_depth=2: {
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


def test_detect_changes_includes_git_scope_and_file_risk(monkeypatch) -> None:
    diff_text = "\n".join(
        [
            "diff --git a/backend/services/product_trends.py b/backend/services/product_trends.py",
            "+++ b/backend/services/product_trends.py",
            "@@ -10 +10 @@",
            "+value = 1",
            "diff --git a/frontend/src/components/ProductTrendModal.tsx b/frontend/src/components/ProductTrendModal.tsx",
            "+++ b/frontend/src/components/ProductTrendModal.tsx",
            "@@ -2 +2 @@",
            "+value = 2",
        ]
    )
    monkeypatch.setattr("services.detect_changes_service._diff_output", lambda repo_root, scope="unstaged", base_ref=None: diff_text)
    monkeypatch.setattr("services.detect_changes_service._run_git", lambda repo_root, args: ".git")

    class _ChangesDuckWithSymbols(_ChangesDuck):
        def fetch_symbols_for_file(self, file_path):
            if file_path == "backend/services/product_trends.py":
                return [
                    {
                        "name": "get_product_trend_data",
                        "qualified_name": "backend.services.product_trends.get_product_trend_data",
                        "kind": "Function",
                        "start_line": 1,
                        "end_line": 20,
                    }
                ]
            if file_path == "frontend/src/components/ProductTrendModal.tsx":
                return [
                    {
                        "name": "ProductTrendModal",
                        "qualified_name": "frontend.src.components.ProductTrendModal",
                        "kind": "Component",
                        "start_line": 1,
                        "end_line": 20,
                    }
                ]
            return []

    payload = detect_changes(Path("C:/repo"), _ChangesDuckWithSymbols(), _Kuzu(), scope="unstaged")

    assert payload["risk_scope"] == "unstaged_working_tree"
    assert payload["risk_score"] > 0
    assert payload["risk_score_label"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert payload["weighted_risk_factors"]
    assert payload["risk_applies_to"] == ["all unstaged changes"]
    assert payload["not_limited_to_recent_edits"] is True
    assert payload["git"]["diff_command_equivalent"] == "git diff --"
    assert payload["risk_by_file"][0]["file"] == "backend/services/product_trends.py"
    assert any("shared service/core path" in row["risk_factors"] for row in payload["risk_by_file"])
    assert payload["compact_summary"]["risk_scope"] == "unstaged_working_tree"
    assert payload["compact_summary"]["risk_score"] == payload["risk_score"]
    assert payload["compact_summary"]["risk_explanation"]


def test_detect_changes_focused_followups_prioritize_capped_high_risk_area() -> None:
    followups = _focused_followups(
        [
            {"file": "services/process_service.py", "risk": "HIGH"},
            {"file": "services/change_report_service.py", "risk": "LOW"},
        ],
        [
            {
                "qualified_name": "trace_execution_flows",
                "name": "trace_execution_flows",
                "file_path": "services/process_service.py",
            }
        ],
        ["Graph blast-radius traversal skipped for 25 changed files."],
    )

    assert followups == [
        {
            "tool": "change_impact_report",
            "target": "services/process_service.py",
            "why": "Run a focused report because broad graph/process traversal was capped.",
        },
        {
            "tool": "trace_processes",
            "target": "trace_execution_flows",
            "why": "Trace execution flows for the highest-risk changed symbol.",
        },
        {
            "tool": "find_tests_for_target",
            "target": "services/process_service.py",
            "why": "Find focused tests for the highest-risk changed area.",
        },
    ]


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


def test_detect_changes_reports_changed_route_contract(monkeypatch, tmp_path: Path) -> None:
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
        "  const response = await apiClient.get('/api/products/trends')\n"
        "  const data = response.data\n"
        "  return data.metrics.intransit_stock\n"
        "}\n",
        encoding="utf-8",
    )
    diff_text = "\n".join(
        [
            "diff --git a/backend/routers/products.py b/backend/routers/products.py",
            "+++ b/backend/routers/products.py",
            "@@ -2 +2 @@",
            "+def get_product_trends():",
        ]
    )
    monkeypatch.setattr("services.detect_changes_service._diff_output", lambda repo_root, scope="unstaged", base_ref=None: diff_text)
    monkeypatch.setattr("services.detect_changes_service._run_git", lambda repo_root, args: ".git")

    class _RouteDuck(_ChangesDuck):
        class _Files:
            def fetch_all(self):
                return [{"path": "backend/routers/products.py"}, {"path": "frontend/src/ProductTrendModal.tsx"}]

        files = _Files()

        def fetch_symbols_for_file(self, file_path):
            if file_path == "backend/routers/products.py":
                return [
                    {
                        "name": "get_product_trends",
                        "qualified_name": "backend.routers.products.get_product_trends",
                        "kind": "Function",
                        "start_line": 1,
                        "end_line": 5,
                    }
                ]
            return super().fetch_symbols_for_file(file_path)

    payload = detect_changes(tmp_path, _RouteDuck(), _Kuzu(), scope="unstaged")

    assert payload["changed_routes"] == ["/products/trends"]
    assert payload["changed_response_shapes"][0]["route"] == "/products/trends"
    assert payload["affected_consumers"][0]["file"] == "frontend/src/ProductTrendModal.tsx"
    assert payload["shape_mismatches"][0]["nested_missing_fields"] == ["metrics.intransit_stock"]
    assert payload["compact_summary"]["changed_routes"] == ["/products/trends"]


def test_detect_changes_changed_routes_ignores_neighbor_decorators(monkeypatch, tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "routers" / "products.py"
    backend.parent.mkdir(parents=True)
    backend.write_text(
        "@limiter.limit('60/minute')\n"
        "@products_router.get(\n"
        "    '/products/trends',\n"
        "    response_model=None,\n"
        ")\n"
        "async def get_product_trends():\n"
        "    return {'metrics': {'avg_ros': 1}}\n"
        "\n"
        "@limiter.limit('60/minute')\n"
        "@products_router.post(\n"
        "    '/settings/channel-pricing',\n"
        ")\n"
        "async def get_channel_pricing_settings_endpoint():\n"
        "    return {'enabled': True}\n",
        encoding="utf-8",
    )
    diff_text = "\n".join(
        [
            "diff --git a/backend/routers/products.py b/backend/routers/products.py",
            "+++ b/backend/routers/products.py",
            "@@ -6 +6 @@",
            "+    return {'metrics': {'avg_ros': 1}}",
        ]
    )
    monkeypatch.setattr("services.detect_changes_service._diff_output", lambda repo_root, scope="unstaged", base_ref=None: diff_text)
    monkeypatch.setattr("services.detect_changes_service._run_git", lambda repo_root, args: ".git")

    class _RouteDuck(_ChangesDuck):
        class _Files:
            def fetch_all(self):
                return [{"path": "backend/routers/products.py"}]

        files = _Files()

        def fetch_symbols_for_file(self, file_path):
            return [
                {
                    "name": "get_product_trends",
                    "qualified_name": "backend.routers.products.get_product_trends",
                    "kind": "Function",
                    "start_line": 5,
                    "end_line": 7,
                }
            ]

    payload = detect_changes(tmp_path, _RouteDuck(), _Kuzu(), scope="unstaged")

    assert payload["changed_routes"] == ["/products/trends"]
    assert all("\n" not in route and "@" not in route for route in payload["changed_routes"])


def test_change_impact_report_uses_route_consumers_for_frontend_graph(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.change_report_service.detect_changes",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref=None: {
            "risk": "LOW",
            "changed_files": ["backend/routers/products.py"],
            "changed_symbols": [],
            "affected_consumers": [
                {
                    "file": "frontend/src/components/ProductTrendModal.tsx",
                    "route": "/products/trends",
                    "field_reads": ["metrics.intransit_stock", "chart_data[].qty_sold"],
                }
            ],
        },
    )
    monkeypatch.setattr("services.change_report_service.analyze_impact", lambda *args, **kwargs: {})
    monkeypatch.setattr("services.change_report_service.app_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        "services.change_report_service.suggest_tests_for_change",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref="": {"compact_summary": {"top_files": []}},
    )

    payload = change_impact_report(Path("C:/repo"), _ChangesDuck(), _Kuzu())

    assert payload["frontend_graph"]["frontend_file_count"] == 1
    assert payload["frontend_graph"]["frontend_graph_edge_count"] == 3
    assert payload["frontend_graph"]["top_relations"]["FETCHES"] == 1
    assert payload["frontend_graph"]["top_relations"]["READS_FIELD"] == 2
    assert payload["frontend_graph"]["top_frontend_files"] == ["frontend/src/components/ProductTrendModal.tsx"]


def test_change_impact_report_builds_pre_commit_workflow_slices(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.change_report_service.detect_changes",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref=None: {
            "risk": "HIGH",
            "confidence": "medium",
            "changed_files": [
                "backend/routers/products.py",
                "backend/services/product_trends.py",
                "frontend/src/components/ProductTrendModal.tsx",
            ],
            "changed_symbols": [],
            "risk_by_file": [
                {"file": "backend/routers/products.py", "risk": "HIGH", "risk_factors": ["API route handler"]},
                {"file": "backend/services/product_trends.py", "risk": "MEDIUM", "risk_factors": ["shared service/core path"]},
                {"file": "frontend/src/components/ProductTrendModal.tsx", "risk": "MEDIUM", "risk_factors": ["frontend UI"]},
            ],
            "changed_routes": ["/products/trends"],
            "risk_by_route": [{"route": "/products/trends", "risk": "HIGH"}],
            "affected_consumers": [
                {
                    "file": "frontend/src/components/ProductTrendModal.tsx",
                    "route": "/products/trends",
                    "function": "ProductTrendModal",
                    "field_reads": ["metrics.intransit_stock", "chart_data[].intransit_stock"],
                }
            ],
            "affected_processes": [
                {
                    "name": "backend: get_product_trends -> get_db_path",
                    "risk": "HIGH",
                    "changed_routes": ["/products/trends"],
                    "risk_reasons": ["1 changed step(s) in flow"],
                    "entry_symbol": "get_product_trends",
                    "changed_symbol": "get_product_trend_data",
                    "changed_symbols": ["get_product_trend_data"],
                    "steps": 3,
                    "step_details": [
                        {"symbol": "get_product_trends", "file": "backend/routers/products.py", "step": 1, "changed": False},
                        {"symbol": "get_product_trend_data", "file": "backend/services/product_trends.py", "step": 2, "changed": True},
                        {"symbol": "get_db_path", "file": "backend/db_utils.py", "step": 3, "changed": False},
                    ],
                }
            ],
            "shape_mismatches": [
                {"route": "/products/trends", "missing_fields": [], "nested_missing_fields": ["metrics.intransit_stock"]}
            ],
            "warnings": ["Process tracing skipped for broad diff"],
        },
    )
    monkeypatch.setattr("services.change_report_service.analyze_impact", lambda *args, **kwargs: {})
    monkeypatch.setattr("services.change_report_service.app_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        "services.change_report_service.suggest_tests_for_change",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref="": {
            "recommended_tests": [
                {"file": "backend/tests/test_product_trends.py"},
                {"file": "frontend/src/components/ProductTrendModal.test.tsx"},
            ],
            "compact_summary": {"top_files": ["backend/tests/test_product_trends.py"]},
        },
    )

    payload = change_impact_report(Path("C:/repo"), _ChangesDuck(), _Kuzu())
    workflow = payload["pre_commit_workflow"]
    first_slice = workflow["recommended_commit_slices"][0]

    assert workflow["summary"] == "3 changed files grouped into 2 recommended commit slice(s)."
    assert first_slice["id"] == "route:/products/trends"
    assert first_slice["risk"] == "HIGH"
    assert "/products/trends" in first_slice["routes"]
    assert "frontend/src/components/ProductTrendModal.tsx" in first_slice["consumers"]
    assert "metrics.intransit_stock" in first_slice["fields"]
    assert first_slice["processes"] == ["backend: get_product_trends -> get_db_path"]
    assert first_slice["process_blast_radius"][0]["changed_steps"][0]["symbol"] == "get_product_trend_data"
    assert "backend/services/product_trends.py" in first_slice["process_blast_radius"][0]["files"]
    assert any("Missing response fields" in item for item in first_slice["what_can_break"])
    assert first_slice["follow_up_tools"][0]["tool"] == "api_impact"
    assert any(item["tool"] == "field_impact" for item in first_slice["follow_up_tools"])
    assert first_slice["field_blast_radius"][0]["route"] == "/products/trends"
    assert first_slice["field_blast_radius"][0]["field"] == "metrics.intransit_stock"
    assert "Run field_impact for high-value or missing response fields." in first_slice["validation"]["validation_plan"]
    assert first_slice["validation"]["status"] == "blocked"
    assert first_slice["validation"]["ready_to_commit"] is False
    assert workflow["commit_plan"][0]["title"] == "Update API contract for /products/trends"
    assert workflow["commit_plan"][0]["slice_id"] == "route:/products/trends"
    assert workflow["validation_summary"]["blocked"] == 1
    assert workflow["readiness"]["status"] == "not_ready"
    assert workflow["readiness"]["ready_to_commit"] is False
    assert workflow["readiness"]["slice_validation"]["blocked"] == 1
    assert payload["pre_commit_readiness"]["blockers"]
    assert payload["what_can_break"]
    assert payload["what_to_test"]
    assert payload["pre_commit_workflow"]["follow_up_tools"]
    assert payload["pre_commit_workflow"]["field_blast_radius"]
    assert payload["pre_commit_workflow"]["process_blast_radius"]
    assert payload["compact_summary"]["pre_commit_slices"][0]["id"] == "route:/products/trends"
    assert payload["compact_summary"]["field_blast_radius"][0]["field"] == "metrics.intransit_stock"
    assert payload["compact_summary"]["process_blast_radius"][0]["changed_symbol"] == "get_product_trend_data"
    assert payload["compact_summary"]["pre_commit_slices"][0]["validation"]["status"] == "blocked"


def test_change_impact_report_groups_coder_infra_slices(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.change_report_service.detect_changes",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref=None: {
            "risk": "CRITICAL",
            "confidence": "medium",
            "changed_files": [
                "indexing/parsers/typescript.py",
                "indexing/graph_builder.py",
                "scripts/run_mcp.py",
                "services/test_intelligence_service.py",
                "services/change_report_service.py",
                "storage/kuzu_store.py",
                "tests/test_impact_change_frontend_signal.py",
            ],
            "changed_symbols": [],
            "risk_by_file": [
                {"file": "indexing/parsers/typescript.py", "risk": "HIGH", "risk_factors": []},
                {"file": "indexing/graph_builder.py", "risk": "MEDIUM", "risk_factors": []},
                {"file": "scripts/run_mcp.py", "risk": "HIGH", "risk_factors": []},
                {"file": "services/test_intelligence_service.py", "risk": "LOW", "risk_factors": []},
                {"file": "services/change_report_service.py", "risk": "MEDIUM", "risk_factors": []},
                {"file": "storage/kuzu_store.py", "risk": "HIGH", "risk_factors": []},
                {"file": "tests/test_impact_change_frontend_signal.py", "risk": "MEDIUM", "risk_factors": []},
            ],
        },
    )
    monkeypatch.setattr("services.change_report_service.analyze_impact", lambda *args, **kwargs: {})
    monkeypatch.setattr("services.change_report_service.app_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        "services.change_report_service.suggest_tests_for_change",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref="": {
            "recommended_tests": [{"file": "tests/test_impact_change_frontend_signal.py"}],
            "compact_summary": {"top_files": ["tests/test_impact_change_frontend_signal.py"]},
        },
    )

    payload = change_impact_report(Path("C:/repo"), _ChangesDuck(), _Kuzu())
    slices = {item["id"]: item for item in payload["pre_commit_workflow"]["recommended_commit_slices"]}

    assert "indexing-parsers" in slices
    assert "indexing-graph" in slices
    assert "mcp-runtime" in slices
    assert "code-intelligence-services" in slices
    assert "graph-storage" in slices
    assert "tests" in slices
    assert "services/test_intelligence_service.py" in slices["support-services"]["files"]
    assert "services/test_intelligence_service.py" not in slices["tests"]["files"]
    assert payload["pre_commit_workflow"]["recommended_order"][:3] == ["indexing-parsers", "indexing-graph", "graph-storage"]
    assert payload["pre_commit_workflow"]["recommended_order"][-1] == "tests"
    assert slices["indexing-parsers"]["what_can_break"]
    assert slices["indexing-parsers"]["validation"]["status"] == "ready"
    assert slices["code-intelligence-services"]["what_can_break"]
    assert slices["code-intelligence-services"]["follow_up_tools"]
    assert payload["pre_commit_workflow"]["commit_plan"][0]["title"] == "Improve parser extraction"
    assert payload["compact_summary"]["commit_plan"][0]["slice_id"] == "indexing-parsers"
    assert payload["compact_summary"]["pre_commit_readiness"]["status"] in {"needs_validation", "not_ready"}
    assert payload["compact_summary"]["validation_summary"]["ready"] >= 1
    assert payload["compact_summary"]["follow_up_tools"]


def test_change_impact_report_filters_to_focused_target(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.change_report_service.detect_changes",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref=None: {
            "risk": "CRITICAL",
            "confidence": "medium",
            "risk_scope": "unstaged_working_tree",
            "changed_files": [
                "indexing/parsers/python.py",
                "scripts/run_mcp.py",
            ],
            "changed_symbols": [
                {"qualified_name": "extract_symbols", "name": "extract_symbols", "file_path": "indexing/parsers/python.py"},
                {"qualified_name": "main", "name": "main", "file_path": "scripts/run_mcp.py"},
            ],
            "risk_by_file": [
                {"file": "indexing/parsers/python.py", "risk": "HIGH", "risk_factors": []},
                {"file": "scripts/run_mcp.py", "risk": "HIGH", "risk_factors": []},
            ],
            "impacted_files": [],
            "impacted_symbols": [],
            "warnings": [
                "Graph blast-radius traversal skipped for 25 changed files; narrow the scope or target a file/symbol for full graph impact.",
                "Process tracing skipped for broad diff (165 changed symbols); use trace_processes on a focused target for full flows.",
            ],
        },
    )
    monkeypatch.setattr("services.change_report_service.analyze_impact", lambda *args, **kwargs: {})
    monkeypatch.setattr("services.change_report_service.app_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        "services.change_report_service.suggest_tests_for_change",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref="", changes=None: {
            "recommended_tests": [],
            "compact_summary": {"top_files": []},
        },
    )

    payload = change_impact_report(
        Path("C:/repo"),
        _ChangesDuck(),
        _Kuzu(),
        target="indexing/parsers/python.py",
    )

    assert payload["risk_scope"] == "focused_change_target"
    assert payload["risk_score_label"] == "HIGH"
    assert "Focused report filtered" in payload["confidence_explanation"][0]
    assert payload["changes"]["changed_files"] == ["indexing/parsers/python.py"]
    assert payload["changes"]["changed_symbols"][0]["qualified_name"] == "extract_symbols"
    assert payload["compact_summary"]["changed_file_count"] == 1
    assert payload["compact_summary"]["target"] == "indexing/parsers/python.py"
    assert payload["changes"]["compact_summary"]["risk_score_label"] == "HIGH"
    assert payload["pre_commit_workflow"]["recommended_order"] == ["indexing-parsers"]
    assert payload["pre_commit_workflow"]["recommended_commit_slices"][0]["validation"]["status"] == "needs_validation"
    assert payload["pre_commit_workflow"]["readiness"]["status"] == "needs_validation"
    assert all("broad diff" not in warning for warning in payload["warnings"])


def test_change_impact_report_marks_validated_high_risk_slice_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.change_report_service.detect_changes",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref=None: {
            "risk": "HIGH",
            "confidence": "medium",
            "risk_scope": "unstaged_working_tree",
            "changed_files": ["services/process_service.py"],
            "changed_symbols": [
                {"qualified_name": "trace_execution_flows", "name": "trace_execution_flows", "file_path": "services/process_service.py"}
            ],
            "risk_by_file": [
                {"file": "services/process_service.py", "risk": "HIGH", "risk_factors": []},
            ],
            "impacted_files": [],
            "impacted_symbols": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr("services.change_report_service.analyze_impact", lambda *args, **kwargs: {})
    monkeypatch.setattr("services.change_report_service.app_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        "services.change_report_service.suggest_tests_for_change",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref="", changes=None: {
            "recommended_tests": [{"file": "tests/test_process_service.py"}],
            "compact_summary": {"top_files": ["tests/test_process_service.py"]},
        },
    )

    payload = change_impact_report(Path("C:/repo"), _ChangesDuck(), _Kuzu(), target="services/process_service.py")

    assert payload["pre_commit_workflow"]["recommended_commit_slices"][0]["validation"]["status"] == "ready"
    assert payload["pre_commit_workflow"]["readiness"]["status"] == "ready"
    assert payload["pre_commit_workflow"]["readiness"]["risk_after_validation"] == "MEDIUM"
    assert payload["risk_after_validation"] == "MEDIUM"
    assert payload["compact_summary"]["pre_commit_readiness"]["status"] == "ready"
    assert payload["compact_summary"]["risk_after_validation"] == "MEDIUM"


def test_change_impact_report_keeps_risk_label_consistent_when_graph_raises_risk(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.change_report_service.detect_changes",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref=None: {
            "risk": "LOW",
            "risk_score": 6,
            "risk_score_label": "LOW",
            "confidence": "medium",
            "risk_scope": "unstaged_working_tree",
            "changed_files": ["services/change_report_service.py"],
            "changed_symbols": [
                {"qualified_name": "change_impact_report", "name": "change_impact_report", "file_path": "services/change_report_service.py"}
            ],
            "risk_by_file": [
                {"file": "services/change_report_service.py", "risk": "LOW", "risk_factors": []},
            ],
            "impacted_files": [],
            "impacted_symbols": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr("services.change_report_service.analyze_impact", lambda *args, **kwargs: {"risk": "HIGH", "compact_summary": {"target": "change_impact_report"}})
    monkeypatch.setattr("services.change_report_service.app_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        "services.change_report_service.suggest_tests_for_change",
        lambda repo_root, duckdb_store, kuzu_store, scope="unstaged", base_ref="", changes=None: {
            "recommended_tests": [{"file": "tests/test_impact_change_frontend_signal.py"}],
            "compact_summary": {"top_files": ["tests/test_impact_change_frontend_signal.py"]},
        },
    )

    payload = change_impact_report(Path("C:/repo"), _ChangesDuck(), _Kuzu(), target="services/change_report_service.py")

    assert payload["base_change_risk"] == "LOW"
    assert payload["risk"] == "HIGH"
    assert payload["risk_score_label"] == "HIGH"
    assert payload["compact_summary"]["risk"] == "HIGH"
    assert payload["compact_summary"]["risk_adjustments"] == ["Focused graph impact raised report risk to HIGH."]


def test_detect_changes_marks_native_header_as_high_risk(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "include" / "engine.h"
    source.parent.mkdir()
    source.write_text("int run_engine(void);\n", encoding="utf-8")
    diff_text = "\n".join(
        [
            "diff --git a/include/engine.h b/include/engine.h",
            "+++ b/include/engine.h",
            "@@ -1 +1 @@",
            "+int run_engine(void);",
        ]
    )
    monkeypatch.setattr("services.detect_changes_service._diff_output", lambda repo_root, scope="unstaged", base_ref=None: diff_text)
    monkeypatch.setattr("services.detect_changes_service._run_git", lambda repo_root, args: ".git")
    monkeypatch.setattr("services.detect_changes_service._route_change_summary", lambda *args, **kwargs: {})
    monkeypatch.setattr("services.detect_changes_service._process_change_summary", lambda *args, **kwargs: {})

    class _Duck:
        def fetch_symbols_for_file(self, file_path):
            return [
                {
                    "name": "run_engine",
                    "qualified_name": "run_engine",
                    "kind": "function",
                    "file_path": file_path,
                    "start_line": 1,
                    "end_line": 1,
                }
            ]

    class _Kuzu:
        def get_impacted_files(self, touched_files):
            return set(touched_files)

        def get_impacted_file_details(self, touched_files):
            return {"impacted_files": touched_files, "relation_totals": {}, "by_touched_file": {}}

    payload = detect_changes(tmp_path, _Duck(), _Kuzu())
    row = payload["risk_by_file"][0]

    assert row["risk"] == "HIGH"
    assert "public/native header surface" in row["risk_factors"]


def test_detect_changes_marks_csharp_controller_as_high_risk(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "backend" / "Controllers" / "ProductsController.cs"
    source.parent.mkdir(parents=True)
    source.write_text("public class ProductsController { public IActionResult GetTrend() => Ok(); }\n", encoding="utf-8")
    diff_text = "\n".join(
        [
            "diff --git a/backend/Controllers/ProductsController.cs b/backend/Controllers/ProductsController.cs",
            "+++ b/backend/Controllers/ProductsController.cs",
            "@@ -1 +1 @@",
            "+public class ProductsController { public IActionResult GetTrend() => Ok(); }",
        ]
    )
    monkeypatch.setattr("services.detect_changes_service._diff_output", lambda repo_root, scope="unstaged", base_ref=None: diff_text)
    monkeypatch.setattr("services.detect_changes_service._run_git", lambda repo_root, args: ".git")
    monkeypatch.setattr("services.detect_changes_service._route_change_summary", lambda *args, **kwargs: {})
    monkeypatch.setattr("services.detect_changes_service._process_change_summary", lambda *args, **kwargs: {})

    class _Duck:
        def fetch_symbols_for_file(self, file_path):
            return [{"name": "ProductsController", "qualified_name": "ProductsController", "kind": "class", "file_path": file_path, "start_line": 1, "end_line": 1}]

    class _Kuzu:
        def get_impacted_files(self, touched_files):
            return set(touched_files)

        def get_impacted_file_details(self, touched_files):
            return {"impacted_files": touched_files, "relation_totals": {}, "by_touched_file": {}}

    payload = detect_changes(tmp_path, _Duck(), _Kuzu())
    row = payload["risk_by_file"][0]

    assert row["risk"] == "HIGH"
    assert "C# public route/API path" in row["risk_factors"]


def test_detect_changes_reports_affected_processes(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "backend" / "routers" / "products.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def get_product_trends():\n"
        "    return get_product_trend_data()\n",
        encoding="utf-8",
    )
    diff_text = "\n".join(
        [
            "diff --git a/backend/routers/products.py b/backend/routers/products.py",
            "+++ b/backend/routers/products.py",
            "@@ -1 +1 @@",
            "+def get_product_trends():",
        ]
    )
    monkeypatch.setattr("services.detect_changes_service._diff_output", lambda repo_root, scope="unstaged", base_ref=None: diff_text)
    monkeypatch.setattr("services.detect_changes_service._run_git", lambda repo_root, args: ".git")
    monkeypatch.setattr(
        "services.detect_changes_service.trace_execution_flows",
        lambda duckdb_store, kuzu_store, target, file_path=None, kind=None, symbol_uid=None, max_depth=4, max_flows=4, changed_symbols=None: {
            "flows": [
                {
                    "name": "products: get_product_trends ? get_product_trend_data",
                    "entry_symbol": "backend.routers.products.get_product_trends",
                    "module": "backend",
                    "steps": 3,
                    "step_details": [
                        {"symbol": "backend.routers.products.get_product_trends", "step": 1},
                        {"symbol": "backend.services.product_trends.get_product_trend_data", "step": 2},
                    ],
                }
            ]
        },
    )

    class _ProcessDuck(_ChangesDuck):
        class _Files:
            def fetch_all(self):
                return [{"path": "backend/routers/products.py"}]

        files = _Files()

        def fetch_symbols_for_file(self, file_path):
            return [
                {
                    "name": "get_product_trends",
                    "qualified_name": "backend.routers.products.get_product_trends",
                    "kind": "Function",
                    "start_line": 1,
                    "end_line": 3,
                }
            ]

    payload = detect_changes(tmp_path, _ProcessDuck(), _Kuzu(), scope="unstaged")

    assert payload["affected_processes"][0]["name"] == "products: get_product_trends ? get_product_trend_data"
    assert payload["risk_by_process"][0]["risk"] == "MEDIUM"
    assert payload["compact_summary"]["affected_processes"] == ["products: get_product_trends ? get_product_trend_data"]
