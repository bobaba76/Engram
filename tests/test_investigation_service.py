from pathlib import Path

from services import investigation_service


class _Store:
    pass


class _Kuzu:
    pass


def test_investigate_codebase_distinguishes_seed_and_expanded_evidence(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "resolved_target": "backend.services.customer_service.resolveCustomer",
            "matches": [
                {
                    "qualified_name": "backend.services.customer_service.resolveCustomer",
                    "file_path": "backend/services/customer_service.py",
                }
            ],
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {
            "compact_results": [
                {
                    "file": "backend/services/customer_service.py",
                    "target": target,
                    "lines": [20, 40],
                    "chunk_kind": "function",
                    "retrieval_source": "chunk_index",
                }
            ]
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {
            "compact_summary": {
                "caller_count": 3,
                "callee_count": 5,
                "dependency_counts": {"imports": 2, "calls": 4},
                "top_neighbors": [{"node": "fetch_customer", "edge_count": 2}],
            }
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {
            "compact_summary": {
                "top_routes": ["/api/customers"],
                "top_files": [
                    "backend/services/customer_service.py",
                    "frontend/components/CustomerView.tsx",
                ],
                "top_processes": ["Customer Lookup"],
                "file_kinds": {"backend": 1, "frontend_component": 1},
                "graph_edge_count": 7,
            }
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="where is customer lookup handled",
        search_payload={
            "compact_results": [
                {
                    "target": "backend.services.customer_service.resolveCustomer",
                    "file": "backend/services/customer_service.py",
                    "lines": [22, 35],
                    "why_relevant": "direct symbol match",
                    "sources": ["symbol", "vector"],
                },
                {
                    "target": "backend.services.customer_service.customerTotals",
                    "file": "backend/services/customer_service.py",
                    "lines": [40, 60],
                    "why_relevant": "expanded search context",
                    "sources": ["window"],
                },
                {
                    "target": "frontend.components.CustomerView",
                    "file": "frontend/components/CustomerView.tsx",
                    "lines": [10, 40],
                    "why_relevant": "route consumer",
                    "sources": ["graph"],
                },
            ],
            "retrieval_diagnostics": {
                "vector_candidates": 8,
                "regex_candidates": 4,
                "expanded_regex_candidates": 3,
                "window_candidates": 2,
            },
        },
        limit=5,
    )

    assert payload["target"] == "backend.services.customer_service.resolveCustomer"
    assert payload["retrieval_diagnostics"]["expanded_regex_candidates"] == 3
    assert len(payload["evidence_breakdown"]["seed_hits"]) == 1
    assert len(payload["evidence_breakdown"]["expanded_hits"]) == 2
    assert payload["ranked_files"][0]["file"] == "backend/services/customer_service.py"
    assert payload["ranked_files"][0]["seed_hits"] == 1
    assert payload["ranked_files"][0]["expanded_hits"] == 1
    assert payload["ranked_files"][0]["snippet_hits"] == 1
    assert any("direct search:" in reason for reason in payload["ranked_files"][0]["reasons"])
    assert any("expanded search:" in reason for reason in payload["ranked_files"][0]["reasons"])
    assert "Primary evidence came from 1 seed hits and 2 expanded hits." in payload["answer"]
    assert "Retrieval diagnostics:" in payload["answer"]
    assert payload["architecture_summary"]["caller_count"] == 3
    assert "Related routes: /api/customers." in payload["data_flow_summary"]
    assert payload["compact_summary"]["seed_hit_count"] == 1
    assert payload["compact_summary"]["expanded_hit_count"] == 2
    assert payload["guidance_summary"]["weak_primary"] is False
    assert any(step.startswith("Open the top source snippets first") for step in payload["next_steps"])
    assert any(tool["tool"] == "impact_analysis" for tool in payload["next_tools"])
    assert any(tool["tool"] == "app_context" for tool in payload["next_tools"])


def test_investigate_codebase_guidance_reacts_to_expanded_only_results(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "found",
            "resolved_target": "frontend.components.CustomerView",
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {
            "compact_summary": {
                "caller_count": 0,
                "callee_count": 0,
                "dependency_counts": {},
                "top_neighbors": [],
            }
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {
            "compact_summary": {
                "top_routes": [],
                "top_files": ["frontend/components/CustomerView.tsx"],
                "top_processes": [],
                "file_kinds": {"frontend_component": 1},
                "graph_edge_count": 0,
            }
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="customer view behavior",
        search_payload={
            "compact_results": [
                {
                    "target": "frontend.components.CustomerView",
                    "file": "frontend/components/CustomerView.tsx",
                    "lines": [5, 30],
                    "why_relevant": "expanded context only",
                    "sources": ["window"],
                }
            ],
            "retrieval_diagnostics": {
                "vector_candidates": 2,
                "regex_candidates": 0,
                "expanded_regex_candidates": 1,
                "window_candidates": 1,
            },
        },
        limit=5,
    )

    assert payload["guidance_summary"]["weak_primary"] is True
    assert any("mostly by expanded context" in step for step in payload["next_steps"])
    assert any(tool["tool"] == "semantic_code_search" for tool in payload["next_tools"])
    assert "Results are mostly expanded context" in payload["open_questions"][0]


def test_investigate_codebase_location_intent_steers_summary(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "found",
            "resolved_target": "backend.services.customer_service.resolveCustomer",
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {
            "compact_results": [
                {
                    "file": "backend/services/customer_service.py",
                    "target": target,
                    "lines": [20, 40],
                    "chunk_kind": "function",
                    "retrieval_source": "chunk_index",
                }
            ]
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 1, "callee_count": 1, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": ["backend/services/customer_service.py"], "top_processes": [], "file_kinds": {"backend": 1}, "graph_edge_count": 0}},
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="where is customer lookup handled",
        search_payload={
            "compact_results": [
                {
                    "target": "backend.services.customer_service.resolveCustomer",
                    "file": "backend/services/customer_service.py",
                    "lines": [22, 35],
                    "why_relevant": "direct symbol match",
                    "sources": ["symbol"],
                }
            ]
        },
        limit=5,
    )

    assert payload["intent"]["primary"] == "location"
    assert "locating the owning implementation" in payload["answer"]
    assert any("Confirm the owning file and symbol" in step for step in payload["next_steps"])


def test_investigate_codebase_flow_intent_prefers_graph_guidance(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "found",
            "resolved_target": "backend.jobs.sync.runSync",
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 4, "callee_count": 6, "dependency_counts": {"calls": 6}, "top_neighbors": [{"node": "loadData", "edge_count": 3}]}} ,
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": ["backend/jobs/sync.py"], "top_processes": ["Sync Pipeline"], "file_kinds": {"backend": 1}, "graph_edge_count": 6}},
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="why does sync happen after upload",
        search_payload={
            "compact_results": [
                {
                    "target": "backend.jobs.sync.runSync",
                    "file": "backend/jobs/sync.py",
                    "lines": [10, 50],
                    "why_relevant": "direct symbol match",
                    "sources": ["symbol", "vector"],
                }
            ]
        },
        limit=5,
    )

    assert payload["intent"]["primary"] == "flow"
    assert "execution flow and why the behavior happens" in payload["answer"]
    assert any("Trace callers, callees, or processes" in step for step in payload["next_steps"])
    assert any(tool["tool"] == "unified_context" for tool in payload["next_tools"])


def test_investigate_codebase_impact_intent_prefers_impact_guidance(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "found",
            "resolved_target": "backend.services.billing.computeInvoice",
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 5, "callee_count": 2, "dependency_counts": {"imports": 2}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": ["/api/invoices"], "top_files": ["backend/services/billing.py"], "top_processes": [], "file_kinds": {"backend": 1}, "graph_edge_count": 4}},
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="what breaks if I change invoice calculation",
        search_payload={
            "compact_results": [
                {
                    "target": "backend.services.billing.computeInvoice",
                    "file": "backend/services/billing.py",
                    "lines": [12, 60],
                    "why_relevant": "direct symbol match",
                    "sources": ["symbol"],
                }
            ]
        },
        limit=5,
    )

    assert payload["intent"]["primary"] == "impact"
    assert any("change-oriented" in step for step in payload["next_steps"])
    assert any(tool["tool"] == "impact_analysis" for tool in payload["next_tools"])


def test_investigation_search_task_recognizes_affect_as_impact_intent() -> None:
    task, plan = investigation_service.investigation_search_task(
        "what will Coordinator.run affect",
        limit=5,
    )

    assert task == "Coordinator.run"
    assert plan["intent"]["primary"] == "impact"


def test_investigate_codebase_exposes_query_rewrite_metadata(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "found",
            "resolved_target": target,
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": ["/api/customers"], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}},
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="please show me where /api/customers is handled in backend/services/customer_service.py",
        search_payload={"compact_results": []},
        limit=5,
    )

    rewrite = payload["query_rewrite"]
    assert "/api/customers" in rewrite["route_terms"]
    assert "backend/services/customer_service.py" in rewrite["file_terms"]
    assert rewrite["search_seeds"]
    assert payload["compact_summary"]["query_rewrite"]["search_seeds"]


def test_investigate_codebase_uses_rewritten_seed_when_search_hits_missing(monkeypatch) -> None:
    repo_root = Path("C:/repo")
    attempts = []

    def _resolve(duckdb_store, repo_root, target="", limit=5):
        attempts.append(target)
        return {
            "status": "found",
            "resolved_target": target,
            "compact_summary": {"warnings": []},
        }

    monkeypatch.setattr(investigation_service, "resolve_tool_target", _resolve)
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}},
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="where is resolveCustomer implemented",
        search_payload={"compact_results": []},
        limit=5,
    )

    assert payload["seed_target"] == "resolveCustomer"
    assert attempts[0] == "resolveCustomer"
    assert "resolveCustomer" in payload["query_rewrite"]["symbol_terms"]


def test_investigate_codebase_retries_with_alternate_seed_when_first_pass_is_weak(monkeypatch) -> None:
    repo_root = Path("C:/repo")
    attempts = []

    def _resolve(duckdb_store, repo_root, target="", limit=5):
        attempts.append(target)
        return {
            "status": "found",
            "resolved_target": target,
            "compact_summary": {"warnings": []},
        }

    def _source_context(duckdb_store, target, limit=3, repo_root=None):
        if target == "resolveCustomer":
            return {"compact_results": []}
        if target == "implementation location resolveCustomer implemented":
            return {
                "compact_results": [
                    {
                        "file": "backend/services/customer_service.py",
                        "target": target,
                        "lines": [10, 30],
                        "chunk_kind": "function",
                        "retrieval_source": "chunk_index",
                    }
                ]
            }
        return {"compact_results": []}

    monkeypatch.setattr(investigation_service, "resolve_tool_target", _resolve)
    monkeypatch.setattr(investigation_service, "get_source_context", _source_context)
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": ["backend/services/customer_service.py"], "top_processes": [], "file_kinds": {"backend": 1}, "graph_edge_count": 0}},
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="where is resolveCustomer implemented",
        search_payload={
            "compact_results": [
                {
                    "target": "resolveCustomer",
                    "file": "backend/services/customer_service.py",
                    "lines": [1, 2],
                    "why_relevant": "expanded only",
                    "sources": ["window"],
                }
            ]
        },
        limit=5,
    )

    assert payload["investigation_passes"]["retry_used"] is True
    assert payload["investigation_passes"]["retry_reason"] == "weak_primary"
    assert len(payload["investigation_passes"]["attempted_seeds"]) >= 2
    assert attempts[0] == "resolveCustomer"
    assert payload["ranked_files"][0]["file"] == "backend/services/customer_service.py"


def test_investigate_codebase_surfaces_graph_backed_frontend_evidence(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "found",
            "resolved_target": "frontend.components.CustomerView",
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {
            "compact_summary": {
                "caller_count": 2,
                "callee_count": 3,
                "dependency_counts": {"calls": 2},
                "top_neighbors": [{"node": "frontend.hooks.useCustomer.useCustomer", "edge_count": 2}],
            }
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {
            "compact_summary": {
                "top_routes": [],
                "top_files": ["frontend/components/CustomerView.tsx", "frontend/hooks/useCustomer.ts"],
                "top_processes": ["Customer Screen"],
                "file_kinds": {"frontend_component": 1, "frontend": 1},
                "graph_edge_count": 5,
            }
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="where is customer view behavior handled",
        search_payload={
            "compact_results": [
                {
                    "target": "frontend.components.CustomerView",
                    "file": "frontend/components/CustomerView.tsx",
                    "lines": [10, 40],
                    "why_relevant": "namespace import consumer",
                    "sources": ["graph"],
                }
            ],
            "retrieval_diagnostics": {
                "vector_candidates": 1,
                "regex_candidates": 0,
                "expanded_regex_candidates": 1,
                "window_candidates": 0,
            },
        },
        limit=5,
    )

    assert payload["graph_signal"]["has_indirect_frontend_path"] is True
    assert payload["graph_signal"]["frontend_graph_hit_count"] == 1
    assert any("graph-backed frontend path" in reason for reason in payload["ranked_files"][0]["reasons"])
    assert payload["evidence"][0]["source"] == "graph_frontend_expanded"
    assert "Frontend implementation evidence is partly graph-backed" in payload["answer"]
    assert payload["compact_summary"]["graph_signal"]["has_indirect_frontend_path"] is True


def test_investigate_codebase_guidance_calls_out_indirect_frontend_path(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "found",
            "resolved_target": "frontend.components.CustomerView",
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {
            "compact_summary": {
                "caller_count": 0,
                "callee_count": 1,
                "dependency_counts": {},
                "top_neighbors": [{"node": "frontend.hooks.useCustomer.useCustomer", "edge_count": 1}],
            }
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {
            "compact_summary": {
                "top_routes": [],
                "top_files": ["frontend/components/CustomerView.tsx"],
                "top_processes": [],
                "file_kinds": {"frontend_component": 1},
                "graph_edge_count": 3,
            }
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="customer view behavior",
        search_payload={
            "compact_results": [
                {
                    "target": "frontend.components.CustomerView",
                    "file": "frontend/components/CustomerView.tsx",
                    "lines": [5, 30],
                    "why_relevant": "graph-only frontend path",
                    "sources": ["graph"],
                }
            ]
        },
        limit=5,
    )

    assert any("graph-backed frontend evidence" in step for step in payload["next_steps"])
    assert any("frontend graph hits as implementation clues" in step for step in payload["next_steps"])
    assert any("graph-backed rather than lexical" in question for question in payload["open_questions"])


def test_behavior_trace_features_extracts_exploratory_anchors() -> None:
    features = investigation_service._behavior_trace_features(
        "find the frontend national overview page and code path for its period selector",
        {
            "symbol_terms": [],
            "route_terms": [],
            "file_terms": [],
            "search_seeds": [],
            "core_terms": ["find", "frontend", "national", "overview", "page", "code", "path", "period", "selector"],
        },
        limit=3,
    )

    assert "period selector" in features
    assert any("national overview" in feature for feature in features)


def test_behavior_trace_features_adds_code_shaped_aliases_for_behavior_terms() -> None:
    features = investigation_service._behavior_trace_features(
        "find the MCP repo selection flow across the app",
        {
            "symbol_terms": ["MCP", "selection"],
            "route_terms": [],
            "file_terms": [],
            "search_seeds": [],
            "core_terms": ["find", "mcp", "repo", "selection", "flow", "across", "app"],
        },
        limit=5,
    )

    assert "select_repo" in features or "select_repo_tool" in features


def test_investigate_codebase_enriches_behavior_trace_from_multiple_feature_anchors(monkeypatch) -> None:
    repo_root = Path("C:/repo")
    feature_calls = []

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {"status": "missing", "resolved_target": target, "compact_summary": {"warnings": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}},
    )

    def _feature_context(repo_root, duckdb_store, kuzu_store, feature, limit=6, lightweight=False):
        feature_calls.append(feature)
        if feature == "national overview":
            return {
                "feature": feature,
                "compact_summary": {
                    "top_files": ["frontend/pages/NationalOverview.tsx"],
                    "top_routes": ["/overview/national"],
                    "top_processes": ["National Overview"],
                    "file_kinds": {"frontend": 1},
                    "file_count": 1,
                },
            }
        if feature == "period selector":
            return {
                "feature": feature,
                "compact_summary": {
                    "top_files": ["frontend/components/PeriodSelector.tsx", "backend/services/period_service.py"],
                    "top_routes": [],
                    "top_processes": ["Period Selection"],
                    "file_kinds": {"frontend": 1, "backend": 1},
                    "file_count": 2,
                },
            }
        return {"feature": feature, "compact_summary": {"top_files": [], "top_routes": [], "top_processes": [], "file_kinds": {}, "file_count": 0}}

    monkeypatch.setattr(investigation_service, "feature_context", _feature_context)

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="find the frontend national overview page and code path for its period selector",
        search_payload={"compact_results": []},
        limit=5,
    )

    assert "national overview" in feature_calls
    assert "period selector" in feature_calls
    assert "frontend/pages/NationalOverview.tsx" in payload["behavior_trace"]["top_files"]
    assert "frontend/components/PeriodSelector.tsx" in payload["behavior_trace"]["top_files"]
    assert set(payload["behavior_trace"]["attempted_features"][:2]) == {"national overview", "period selector"}
    assert any(tool["tool"] == "feature_context" for tool in payload["next_tools"])
    assert any("Behavior trace surfaced exploratory candidate files" in warning for warning in payload["warnings"])


def test_investigate_codebase_behavior_trace_helps_when_direct_evidence_is_sparse(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {"status": "missing", "resolved_target": target, "compact_summary": {"warnings": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}},
    )
    monkeypatch.setattr(
        investigation_service,
        "feature_context",
        lambda repo_root, duckdb_store, kuzu_store, feature, limit=6, lightweight=False: {
            "feature": feature,
            "compact_summary": {
                "top_files": ["frontend/components/FinancialYearToggle.tsx"] if feature == "financial year" else [],
                "top_routes": [],
                "top_processes": ["Year Selection"] if feature == "financial year" else [],
                "file_kinds": {"frontend": 1} if feature == "financial year" else {},
                "file_count": 1 if feature == "financial year" else 0,
            },
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="trace financial year versus calendar year behavior across the app",
        search_payload={"compact_results": []},
        limit=5,
    )

    assert "frontend/components/FinancialYearToggle.tsx" in payload["behavior_trace"]["top_files"]
    assert "Feature trace candidates include frontend/components/FinancialYearToggle.tsx." in payload["answer"]
    assert "Behavior anchors tried:" in " ".join(payload["answer_outline"])


def test_investigate_codebase_promotes_behavior_trace_files_into_ranked_results(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {"status": "missing", "resolved_target": target, "compact_summary": {"warnings": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}},
    )
    monkeypatch.setattr(
        investigation_service,
        "feature_context",
        lambda repo_root, duckdb_store, kuzu_store, feature, limit=6, lightweight=False: {
            "feature": feature,
            "compact_summary": {
                "top_files": ["scripts/run_mcp.py"] if feature in {"mcp repo", "repo selection"} else [],
                "top_routes": [],
                "top_processes": ["Repo Selection"] if feature in {"mcp repo", "repo selection"} else [],
                "file_kinds": {"supporting_code": 1} if feature in {"mcp repo", "repo selection"} else {},
                "file_count": 1 if feature in {"mcp repo", "repo selection"} else 0,
            },
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="find the MCP repo selection flow across the app",
        search_payload={"compact_results": []},
        limit=5,
    )

    assert payload["ranked_files"][0]["file"] == "scripts/run_mcp.py"
    assert any("behavior trace candidate" in reason or "owner hint:" in reason for reason in payload["ranked_files"][0]["reasons"])


def test_investigate_codebase_adds_owner_hints_for_workflow_questions(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {"status": "missing", "resolved_target": target, "compact_summary": {"warnings": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}},
    )
    monkeypatch.setattr(
        investigation_service,
        "feature_context",
        lambda repo_root, duckdb_store, kuzu_store, feature, limit=6, lightweight=False: {"feature": feature, "compact_summary": {"top_files": [], "top_routes": [], "top_processes": [], "file_kinds": {}, "file_count": 0}},
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="trace the indexing progress reporting flow",
        search_payload={"compact_results": []},
        limit=5,
    )

    top_files = [item["file"] for item in payload["ranked_files"]]
    assert "app/coordinator.py" in top_files[:2]
    coordinator = next(item for item in payload["ranked_files"] if item["file"] == "app/coordinator.py")
    assert any("owner hint: indexing progress coordinator" in reason for reason in coordinator["reasons"])


def test_investigate_codebase_returns_grouped_exploratory_roles_for_ui_trace(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {"status": "missing", "resolved_target": target, "compact_summary": {"warnings": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {
            "compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {
            "compact_summary": {
                "top_routes": ["/api/regional-overview"],
                "top_files": [],
                "top_processes": [],
                "file_kinds": {"frontend_component": 1, "backend": 1},
                "graph_edge_count": 0,
            }
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "feature_context",
        lambda repo_root, duckdb_store, kuzu_store, feature, limit=6, lightweight=False: {
            "feature": feature,
            "compact_summary": {
                "top_files": (
                    ["frontend/pages/RegionalOverviewLandingPage.js"]
                    if "overview" in feature.lower()
                    else ["frontend/components/PeriodSelector.js", "backend/services/period_service.py"]
                    if "period" in feature.lower() or "selector" in feature.lower()
                    else []
                ),
                "top_routes": ["/api/regional-overview"] if "overview" in feature.lower() else [],
                "top_processes": [],
                "file_kinds": {"frontend_component": 1, "backend": 1},
                "file_count": 2,
            },
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="Find the frontend national overview page and the code path for its period selector, including shared date period utilities and the backend endpoints it calls.",
        search_payload={"compact_results": [], "retrieval_diagnostics": {"exploratory_lightweight_path": True}},
        limit=5,
    )

    assert payload["intent"]["primary"] == "ui_ownership"
    assert "frontend/pages/RegionalOverviewLandingPage.js" in payload["exploratory_groups"]["page_files"]
    assert "frontend/components/PeriodSelector.js" in payload["exploratory_groups"]["shared_ui_files"]
    assert "backend/services/period_service.py" in payload["exploratory_groups"]["backend_files"]
    assert "/api/regional-overview" in payload["exploratory_groups"]["endpoint_routes"]
    assert "exploratory feature trace" in payload["answer"]


def test_investigate_codebase_uses_lightweight_behavior_trace_for_broad_exploration(monkeypatch) -> None:
    repo_root = Path("C:/repo")
    feature_calls = []

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {"status": "missing", "resolved_target": target, "compact_summary": {"warnings": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {
            "compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {
            "compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}
        },
    )

    def _feature_context(repo_root, duckdb_store, kuzu_store, feature, limit=6, lightweight=False):
        feature_calls.append((feature, limit, lightweight))
        return {
            "feature": feature,
            "partial": lightweight,
            "compact_summary": {
                "partial": lightweight,
                "top_files": ["frontend/pages/RegionalOverviewLandingPage.js"] if "overview" in feature.lower() else [],
                "top_routes": [],
                "top_processes": [],
                "file_kinds": {"frontend_component": 1},
                "role_groups": {"page_files": ["frontend/pages/RegionalOverviewLandingPage.js"], "shared_ui_files": [], "backend_files": []},
                "file_count": 1,
            },
        }

    monkeypatch.setattr(investigation_service, "feature_context", _feature_context)

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="Find the frontend national overview page and the code path for its period selector, including shared date period utilities and the backend endpoints it calls.",
        search_payload={"compact_results": [], "retrieval_diagnostics": {"exploratory_lightweight_path": True}},
        limit=5,
    )

    assert feature_calls
    assert all(call[2] is True for call in feature_calls)
    assert payload["behavior_trace"]["partial"] is True
    assert any("lightweight budget" in warning for warning in payload["warnings"])
    assert payload["target"] == "frontend/pages/RegionalOverviewLandingPage.js"
    assert payload["ranked_files"][0]["file"] == "frontend/pages/RegionalOverviewLandingPage.js"
    assert any("page owner" in reason for reason in payload["ranked_files"][0]["reasons"])


def test_lightweight_exploratory_path_orders_page_shared_ui_then_backend(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {"status": "missing", "resolved_target": target, "compact_summary": {"warnings": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {
            "compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {
            "compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "feature_context",
        lambda repo_root, duckdb_store, kuzu_store, feature, limit=6, lightweight=False: {
            "feature": feature,
            "partial": lightweight,
            "compact_summary": {
                "partial": lightweight,
                "top_files": [
                    "frontend/components/HikvisionReportExport.js",
                    "frontend/components/ReportExport.js",
                    "frontend/contexts/PeriodContext.js",
                    "frontend/components/GlobalPeriodSelector.js",
                ],
                "top_routes": [],
                "top_processes": [],
                "file_kinds": {"frontend_component": 1, "backend": 1},
                "role_groups": {
                    "page_files": ["frontend/pages/RegionalOverviewLandingPage.js"],
                    "shared_ui_files": ["frontend/contexts/PeriodContext.js", "frontend/components/GlobalPeriodSelector.js"],
                    "backend_files": ["backend/api/endpoints/regional.py"],
                },
                "file_count": 4,
            },
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="Find the frontend national overview page and the code path for its period selector, including shared date period utilities and the backend endpoints it calls.",
        search_payload={"compact_results": [], "retrieval_diagnostics": {"exploratory_lightweight_path": True}},
        limit=5,
    )

    ranked_paths = [item["file"] for item in payload["ranked_files"][:4]]
    assert ranked_paths[0] == "frontend/pages/RegionalOverviewLandingPage.js"
    assert "frontend/contexts/PeriodContext.js" in ranked_paths[:3]
    assert "frontend/components/GlobalPeriodSelector.js" in ranked_paths[:3]
    assert "backend/api/endpoints/regional.py" in ranked_paths[:4]
    assert "frontend/components/HikvisionReportExport.js" not in ranked_paths[:4]


def test_investigation_search_task_narrows_broad_question() -> None:
    task, plan = investigation_service.investigation_search_task(
        "where is defaultView behavior handled",
        limit=5,
    )

    assert task == "defaultView"
    assert plan["task_source"] == "symbol_term"
    assert plan["guardrails"]["broad_question"] is True
    assert plan["guardrails"]["allow_retry"] is False
    assert plan["guardrails"]["search_limit"] == 4


def test_investigation_search_task_prefers_feature_phrase_over_weak_broad_seed() -> None:
    task, plan = investigation_service.investigation_search_task(
        "trace the indexing progress reporting flow",
        limit=5,
    )

    assert task == "indexing progress"
    assert plan["task_source"] == "behavior_trace_seed"


def test_investigation_search_task_prefers_feature_phrase_over_endpoint_seed_for_ui_prompt() -> None:
    task, plan = investigation_service.investigation_search_task(
        "Find the frontend national overview page and the code path for its period selector, including shared date period utilities and the backend endpoints it calls.",
        limit=5,
    )

    assert task in {"national overview", "period selector"}
    assert plan["task_source"] == "behavior_trace_seed"


def test_symbolish_terms_rejects_imperative_seed_tokens() -> None:
    terms = investigation_service._symbolish_terms(
        "Find the frontend national overview page and code path for its period selector",
        limit=8,
    )

    assert "Find" not in terms
    assert "including" not in [term.lower() for term in terms]


def test_symbolish_terms_rejects_generic_exploratory_nouns() -> None:
    terms = investigation_service._symbolish_terms(
        "Find the frontend national overview page and the code path for its period selector, including shared date period utilities",
        limit=10,
    )

    lowered = [term.lower() for term in terms]
    assert "utilities" not in lowered
    assert "shared" not in lowered


def test_question_intent_classifies_broad_ui_feature_trace() -> None:
    intent = investigation_service._question_intent(
        "Find the frontend national overview page and the code path for its period selector, including shared date period utilities",
    )

    assert intent["primary"] == "ui_ownership"


def test_app_context_target_prefers_behavior_feature_for_ui_prompt() -> None:
    query_rewrite = investigation_service._query_rewrite(
        "Find the frontend national overview page and the code path for its period selector, including shared date period utilities and the backend endpoints it calls.",
        {"primary": "ui_ownership"},
    )

    target, source = investigation_service._app_context_target(
        "Find the frontend national overview page and the code path for its period selector, including shared date period utilities and the backend endpoints it calls.",
        "SendReportRequest",
        query_rewrite,
    )

    assert target in {"national overview", "period selector"}
    assert source == "behavior_trace_feature"


def test_file_relevance_downranks_export_noise_for_period_state_prompt() -> None:
    ranked = investigation_service._file_relevance(
        search_hits=[
            {"file": "frontend/components/GlobalPeriodSelector.js", "target": "GlobalPeriodSelector", "why_relevant": "selector match", "sources": ["symbol"]},
            {"file": "frontend/components/ReportExport.js", "target": "ReportExport", "why_relevant": "generic text overlap", "sources": ["symbol"]},
        ],
        snippets=[],
        app={"compact_summary": {}},
        behavior_trace={},
        question="Find the frontend national overview page and the code path for its period selector, including shared date period utilities and the backend endpoints it calls.",
        intent={"primary": "ui_ownership"},
        limit=5,
    )

    assert ranked[0]["file"] == "frontend/components/GlobalPeriodSelector.js"
    export_item = next(item for item in ranked if item["file"] == "frontend/components/ReportExport.js")
    assert any("export/report file" in reason for reason in export_item["reasons"])


def test_file_relevance_prefers_page_owner_over_shared_hook_for_page_prompt() -> None:
    ranked = investigation_service._file_relevance(
        search_hits=[
            {"file": "frontend/hooks/useApiQuery.js", "target": "useApiQuery", "why_relevant": "shared query helper", "sources": ["symbol"]},
            {"file": "frontend/pages/RegionalOverviewLandingPage.js", "target": "RegionalOverviewLandingPage", "why_relevant": "overview page owner", "sources": ["symbol"]},
        ],
        snippets=[],
        app={"compact_summary": {}},
        behavior_trace={},
        question="Find the frontend national overview page and the code path for its period selector.",
        intent={"primary": "ui_ownership"},
        limit=5,
    )

    assert ranked[0]["file"] == "frontend/pages/RegionalOverviewLandingPage.js"
    hook_item = next(item for item in ranked if item["file"] == "frontend/hooks/useApiQuery.js")
    assert any("secondary-role penalty" in reason for reason in hook_item["reasons"])


def test_file_relevance_penalizes_unrelated_backend_endpoint_for_ui_trace() -> None:
    ranked = investigation_service._file_relevance(
        search_hits=[
            {"file": "backend/api/endpoints/email.py", "target": "SendReportRequest", "why_relevant": "endpoint mention", "sources": ["symbol"]},
            {"file": "frontend/pages/RegionalOverviewLandingPage.js", "target": "RegionalOverviewLandingPage", "why_relevant": "overview page owner", "sources": ["symbol"]},
            {"file": "backend/api/endpoints/regional.py", "target": "RegionalOverviewEndpoint", "why_relevant": "regional endpoint", "sources": ["symbol"]},
        ],
        snippets=[],
        app={"compact_summary": {}},
        behavior_trace={},
        question="Find the frontend national overview page and the code path for its period selector, including shared date period utilities and the backend endpoints it calls.",
        intent={"primary": "ui_ownership"},
        limit=5,
    )

    assert ranked[0]["file"] == "frontend/pages/RegionalOverviewLandingPage.js"
    regional_item = next(item for item in ranked if item["file"] == "backend/api/endpoints/regional.py")
    email_item = next(item for item in ranked if item["file"] == "backend/api/endpoints/email.py")
    assert regional_item["score"] > email_item["score"]
    assert any("endpoint mismatch penalty" in reason for reason in email_item["reasons"])


def test_evidence_items_filters_noisy_exploratory_files_and_reasons() -> None:
    evidence = investigation_service._evidence_items(
        seed_hits=[
            {"file": "frontend/pages/RegionalOverviewLandingPage.js", "target": "RegionalOverviewLandingPage", "lines": [10, 40], "why_relevant": "page owner", "sources": ["symbol"]},
            {"file": "frontend/test-utils.js", "target": "findByText", "lines": [1, 10], "why_relevant": "test-utils helper", "sources": ["symbol"]},
        ],
        expanded_hits=[
            {"file": "frontend/components/GlobalPeriodSelector.js", "target": "GlobalPeriodSelector", "lines": [5, 30], "why_relevant": "selector state", "sources": ["window"]},
            {"file": "frontend/utils/xssProtection.js", "target": "xssProtection", "lines": [1, 8], "why_relevant": "xssProtection overlap", "sources": ["window"]},
        ],
        snippets=[
            {"file": "frontend/hooks/useApiQuery.js", "target": "useApiQuery", "lines": [1, 20], "retrieval_source": "chunk_index"},
            {"file": "frontend/utils/memoryMonitor.js", "target": "memoryMonitor", "lines": [1, 20], "retrieval_source": "memoryMonitor"},
        ],
        unified={"compact_summary": {"top_neighbors": []}},
        app={"compact_summary": {"top_files": ["frontend/pages/RegionalOverviewLandingPage.js", "frontend/test-utils.js"]}},
        ranked_files=[
            {"file": "frontend/pages/RegionalOverviewLandingPage.js"},
            {"file": "frontend/components/GlobalPeriodSelector.js"},
            {"file": "frontend/hooks/useApiQuery.js"},
        ],
        intent={"primary": "ui_ownership"},
    )

    evidence_files = [item.get("file") for item in evidence if item.get("file")]
    assert "frontend/pages/RegionalOverviewLandingPage.js" in evidence_files
    assert "frontend/components/GlobalPeriodSelector.js" in evidence_files
    assert "frontend/hooks/useApiQuery.js" in evidence_files
    assert "frontend/test-utils.js" not in evidence_files
    assert "frontend/utils/memoryMonitor.js" not in evidence_files
    assert "frontend/utils/xssProtection.js" not in evidence_files


def test_should_allow_broad_vector_fallback_rejects_vague_camel_case_term() -> None:
    task, plan = investigation_service.investigation_search_task(
        "where is defaultView behavior handled",
        limit=5,
    )

    assert task == "defaultView"
    assert investigation_service.should_allow_broad_vector_fallback(task, plan["query_rewrite"]) is False


def test_should_allow_broad_vector_fallback_allows_specific_symbol_like_target() -> None:
    task, plan = investigation_service.investigation_search_task(
        "where is resolveCustomer implemented",
        limit=5,
    )

    assert task == "resolveCustomer"
    assert investigation_service.should_allow_broad_vector_fallback(task, plan["query_rewrite"]) is True


def test_should_allow_broad_vector_fallback_allows_route_like_target() -> None:
    task, plan = investigation_service.investigation_search_task(
        "where is /api/customers handled",
        limit=5,
    )

    assert task == "/api/customers"
    assert investigation_service.should_allow_broad_vector_fallback(task, plan["query_rewrite"]) is True


def test_broad_lexical_search_terms_keeps_safe_specific_terms_only() -> None:
    task, plan = investigation_service.investigation_search_task(
        "where is defaultView behavior handled in /api/customers",
        limit=5,
    )

    terms = investigation_service.broad_lexical_search_terms(task, plan["query_rewrite"], limit=4)

    assert "api/customers" in terms or "/api/customers" in terms
    assert "behavior" not in terms
    assert "handled" not in terms


def test_broad_lexical_search_terms_adds_split_camel_case_variant() -> None:
    task, plan = investigation_service.investigation_search_task(
        "where is resolveCustomer implemented",
        limit=5,
    )

    terms = investigation_service.broad_lexical_search_terms(task, plan["query_rewrite"], limit=4)

    assert "resolveCustomer" in terms
    assert "resolve Customer" in terms


def test_prioritize_search_hits_prefers_exact_target_over_generic_neighbor() -> None:
    prioritized = investigation_service._prioritize_search_hits(
        [
            {
                "target": "main",
                "file": "app/main.py",
                "score": 1.3,
                "sources": ["chunk", "regex"],
            },
            {
                "target": "Coordinator.run",
                "file": "app/coordinator.py",
                "score": 1.2,
                "sources": ["chunk", "regex"],
            },
        ],
        seed_target="Coordinator.run",
        resolved_target="Coordinator.run",
    )

    assert prioritized[0]["target"] == "Coordinator.run"


def test_guidance_next_tools_dedupes_same_tool_and_target() -> None:
    tools = investigation_service._guidance_next_tools(
        {
            "ambiguous": False,
            "has_graph_context": False,
            "has_routes": False,
            "has_processes": False,
            "weak_primary": False,
            "intent": {"primary": "location"},
        },
        resolved_target="Coordinator.run",
        question="where is Coordinator.run handled",
    )

    source_tools = [item for item in tools if item["tool"] == "get_source_context" and item["target"] == "Coordinator.run"]
    assert len(source_tools) == 1


def test_alternate_discovery_anchors_prefers_specific_safe_candidates() -> None:
    anchors = investigation_service.alternate_discovery_anchors(
        "defaultView",
        {
            "symbol_terms": ["defaultView", "useSavedViews", "behavior"],
            "route_terms": [],
            "file_terms": ["frontend/src/hooks/useSavedViews.ts"],
            "search_seeds": ["defaultView", "useSavedViews"],
            "core_terms": ["defaultview", "savedviews", "behavior"],
        },
        limit=2,
    )

    assert anchors == ["frontend/src/hooks/useSavedViews.ts", "useSavedViews"]


def test_investigate_codebase_skips_retry_for_broad_questions(monkeypatch) -> None:
    repo_root = Path("C:/repo")
    attempts = []

    def _resolve(duckdb_store, repo_root, target="", limit=5):
        attempts.append(target)
        return {
            "status": "found",
            "resolved_target": target,
            "compact_summary": {"warnings": []},
        }

    monkeypatch.setattr(investigation_service, "resolve_tool_target", _resolve)
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {
            "compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {
            "compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="where is defaultView behavior handled",
        search_payload={
            "compact_results": [
                {
                    "target": "defaultView",
                    "file": "frontend/src/hooks/useSavedViews.ts",
                    "lines": [10, 20],
                    "why_relevant": "expanded only",
                    "sources": ["window"],
                },
                {
                    "target": "SavedViewsToolbar",
                    "file": "frontend/src/components/SavedViewsToolbar.tsx",
                    "lines": [1, 5],
                    "why_relevant": "extra graph context",
                    "sources": ["graph"],
                },
            ]
        },
        limit=5,
    )

    assert attempts == ["defaultView"]
    assert payload["investigation_passes"]["retry_used"] is False
    assert payload["investigation_passes"]["retry_reason"] == "guardrail_skipped"
    assert payload["guardrails"]["broad_question"] is True
    assert payload["seed_target"] == "defaultView"
    assert payload["search_task"]["task"] == "defaultView"
    assert any("Alternate-seed retries were skipped" in warning for warning in payload["warnings"])
    assert any("anchored to narrowed search term 'defaultView'" in warning for warning in payload["warnings"])


def test_investigate_codebase_replaces_generic_target_with_narrowed_term(monkeypatch) -> None:
    repo_root = Path("C:/repo")
    attempts = []

    def _resolve(duckdb_store, repo_root, target="", limit=5):
        attempts.append(target)
        if target == "defaultView":
            return {"status": "found", "resolved_target": "main", "compact_summary": {"warnings": []}}
        return {"status": "found", "resolved_target": target, "compact_summary": {"warnings": []}}

    monkeypatch.setattr(investigation_service, "resolve_tool_target", _resolve)
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {
            "compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {
            "compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="where is defaultView behavior handled",
        search_payload={"compact_results": []},
        limit=5,
    )

    assert attempts == ["defaultView"]
    assert payload["target"] == "main"
    assert not any("Generic target resolution was replaced" in warning for warning in payload["warnings"])


def test_investigate_codebase_uses_cheap_symbol_discovery_when_search_is_empty(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    class _DiscoveryStore(_Store):
        def fetch_symbols_for_target(self, target, limit=50):
            if str(target) == "defaultView":
                return [
                    {
                        "qualified_name": "frontend.saved_views.defaultViewState",
                        "name": "defaultViewState",
                        "file_path": "frontend/src/hooks/useSavedViews.ts",
                        "kind": "function",
                        "start_line": 10,
                        "end_line": 30,
                    }
                ]
            if str(target) == "defaultview":
                return [
                    {
                        "qualified_name": "frontend.saved_views.defaultViewLabel",
                        "name": "defaultViewLabel",
                        "file_path": "frontend/src/components/SavedViewsToolbar.tsx",
                        "kind": "const",
                        "start_line": 3,
                        "end_line": 8,
                    }
                ]
            return []

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "not_found",
            "resolved_target": target,
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}},
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_DiscoveryStore(),
        kuzu_store=_Kuzu(),
        question="where is defaultView behavior handled",
        search_payload={"compact_results": []},
        limit=5,
    )

    assert len(payload["discovered_symbols"]) == 2
    assert "cheap lexical discovery" in " ".join(payload["warnings"]).lower()
    assert "nearby candidates" in payload["answer"]
    assert payload["compact_summary"]["discovered_symbols"]


def test_investigate_codebase_tries_alternate_discovery_anchors_when_primary_is_empty(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    class _DiscoveryStore(_Store):
        def fetch_symbols_for_target(self, target, limit=50):
            if str(target) == "useSavedViews":
                return [
                    {
                        "qualified_name": "frontend.saved_views.useSavedViews",
                        "name": "useSavedViews",
                        "file_path": "frontend/src/hooks/useSavedViews.ts",
                        "kind": "function",
                        "start_line": 5,
                        "end_line": 35,
                    }
                ]
            return []

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "not_found",
            "resolved_target": target,
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}},
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_DiscoveryStore(),
        kuzu_store=_Kuzu(),
        question="where is defaultView behavior handled",
        search_payload={
            "compact_results": [],
            "investigation_search_plan": {
                "query_rewrite": {
                    "core_terms": ["defaultview", "savedviews", "behavior"],
                    "symbol_terms": ["defaultView", "useSavedViews", "behavior"],
                    "route_terms": [],
                    "file_terms": [],
                    "search_seeds": ["defaultView", "useSavedViews"],
                    "rewritten_queries": ["where is defaultView behavior handled"],
                }
            },
        },
        limit=5,
    )

    assert payload["discovered_symbols"]
    assert payload["discovered_symbols"][0]["qualified_name"] == "frontend.saved_views.useSavedViews"
    assert payload["investigation_passes"]["alternate_discovery_anchors"] == ["useSavedViews", "savedviews"]
    assert "alternate anchors" in " ".join(payload["warnings"]).lower()


def test_investigate_codebase_uses_chunk_text_for_weak_ui_target(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    class _UiStore(_Store):
        def fetch_symbols_for_target(self, target, limit=50):
            return []

        def search_chunks_content(self, query, limit=20):
            if str(query).strip().lower() in {"default view", "defaultview"}:
                return [{"file_path": "frontend/src/hooks/useSavedViews.ts"}]
            return []

        def fetch_symbols_for_file(self, file_path):
            if file_path == "frontend/src/hooks/useSavedViews.ts":
                return [
                    {
                        "qualified_name": "frontend.saved_views.useSavedViews",
                        "name": "useSavedViews",
                        "file_path": file_path,
                        "kind": "function",
                        "start_line": 5,
                        "end_line": 35,
                    }
                ]
            return []

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "not_found",
            "resolved_target": target,
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": []},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 0, "callee_count": 0, "dependency_counts": {}, "top_neighbors": []}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": [], "top_processes": [], "file_kinds": {}, "graph_edge_count": 0}},
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_UiStore(),
        kuzu_store=_Kuzu(),
        question="where is defaultView behavior handled",
        search_payload={"compact_results": []},
        limit=5,
    )

    assert payload["discovered_symbols"]
    assert payload["discovered_symbols"][0]["qualified_name"] == "frontend.saved_views.useSavedViews"
    assert any("weak ui-like target" in warning.lower() for warning in payload["warnings"])


def test_investigate_codebase_includes_change_guidance(monkeypatch) -> None:
    repo_root = Path("C:/repo")

    monkeypatch.setattr(
        investigation_service,
        "resolve_tool_target",
        lambda duckdb_store, repo_root, target="", limit=5: {
            "status": "found",
            "resolved_target": "Coordinator.run",
            "compact_summary": {"warnings": []},
        },
    )
    monkeypatch.setattr(
        investigation_service,
        "get_source_context",
        lambda duckdb_store, target, limit=3, repo_root=None: {"compact_results": [{"file": "app/coordinator.py", "target": target, "lines": [167, 277], "retrieval_source": "chunk_index"}]},
    )
    monkeypatch.setattr(
        investigation_service,
        "get_unified_context",
        lambda duckdb_store, kuzu_store, target, max_matches=3, neighborhood_depth=1: {"compact_summary": {"caller_count": 1, "callee_count": 1, "dependency_counts": {}, "top_neighbors": [{"node": "Coordinator._run_agent_analyses", "edge_count": 1}]}},
    )
    monkeypatch.setattr(
        investigation_service,
        "app_context",
        lambda repo_root, duckdb_store, kuzu_store, target="", limit=6: {"compact_summary": {"top_routes": [], "top_files": ["app/coordinator.py", "app/main.py"], "top_processes": [], "file_kinds": {"backend": 1}, "graph_edge_count": 0}},
    )
    monkeypatch.setattr(
        investigation_service,
        "find_tests_for_target",
        lambda duckdb_store, target, limit=4: {
            "compact_results": [
                {"file": "tests/test_coordinator.py", "target": "test_run", "kind": "test", "score": 5},
            ],
            "compact_summary": {"top_files": ["tests/test_coordinator.py"]},
        },
    )

    payload = investigation_service.investigate_codebase(
        repo_root=repo_root,
        duckdb_store=_Store(),
        kuzu_store=_Kuzu(),
        question="what will Coordinator.run affect",
        search_payload={
            "compact_results": [
                {"target": "Coordinator.run", "file": "app/coordinator.py", "lines": [167, 277], "why_relevant": "direct symbol match", "sources": ["symbol", "chunk"]},
            ]
        },
        limit=5,
    )

    assert payload["change_guidance"]["related_files"][:2] == ["app/coordinator.py", "app/main.py"]
    assert payload["change_guidance"]["recommended_tests"][0]["file"] == "tests/test_coordinator.py"
    assert payload["change_guidance"]["likely_impact_targets"] == ["Coordinator._run_agent_analyses"]
    assert "Suggested tests: 1" in payload["answer_outline"]
