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

    assert attempts == ["defaultView", "defaultView"]
    assert payload["target"] == "defaultView"
    assert any("Generic target resolution was replaced" in warning for warning in payload["warnings"])
