from mcp_server.formatters import enrich_payload


def test_enrich_payload_renders_frontend_graph_summary_from_app_context() -> None:
    payload = {
        "target": "CustomerView",
        "compact_summary": {
            "route_count": 0,
            "file_count": 2,
            "graph_edge_count": 4,
            "frontend_graph": {
                "frontend_file_count": 2,
                "top_frontend_files": ["frontend/components/CustomerView.tsx", "frontend/hooks/useCustomer.ts"],
                "frontend_graph_edge_count": 3,
                "top_relations": {"CALLS": 2, "IMPORTS": 1},
                "has_indirect_frontend_path": True,
                "summary": "Frontend implementation paths include graph-linked TS/TSX files, so behavior may be discovered indirectly.",
            },
        },
    }

    enriched = enrich_payload(payload)

    assert "Frontend graph: frontend_files=2, frontend_graph=3, indirect_frontend_path=yes" in enriched["summary_text"]
    assert "Frontend files: frontend/components/CustomerView.tsx, frontend/hooks/useCustomer.ts" in enriched["summary_text"]
    assert "Frontend relations: CALLS=2, IMPORTS=1" in enriched["summary_text"]
    assert "Frontend summary: Frontend implementation paths include graph-linked TS/TSX files" in enriched["summary_text"]


def test_enrich_payload_renders_investigation_graph_signal() -> None:
    payload = {
        "target": "frontend.components.CustomerView",
        "answer": "Graph-backed investigation result.",
        "compact_summary": {
            "confidence": "medium",
            "graph_signal": {
                "frontend_graph_hit_count": 2,
                "frontend_graph_files": ["frontend/components/CustomerView.tsx"],
                "has_indirect_frontend_path": True,
            },
        },
    }

    enriched = enrich_payload(payload)

    assert "Frontend graph: frontend_graph=2, indirect_frontend_path=yes" in enriched["summary_text"]
    assert "Frontend files: frontend/components/CustomerView.tsx" in enriched["summary_text"]


def test_enrich_payload_adds_agent_reliability_contract_fields() -> None:
    payload = {
        "target": "pkg.service.do_work",
        "matches": [
            {
                "qualified_name": "pkg.service.do_work",
                "file_path": "pkg/service.py",
                "kind": "function",
            }
        ],
        "compact_summary": {},
    }

    enriched = enrich_payload(payload)

    assert enriched["status"] == "ok"
    assert enriched["confidence"] == "medium"
    assert enriched["partial"] is False
    assert enriched["warnings"] == []
    assert enriched["top_files"] == ["pkg/service.py"]
    assert enriched["top_symbols"] == ["pkg.service.do_work"]
    assert enriched["next_tools"][0]["tool"] == "get_source_context"
    assert enriched["compact_summary"]["status"] == "ok"
    assert enriched["compact_summary"]["next_tools"][0]["tool"] == "get_source_context"


def test_enrich_payload_promotes_pre_commit_follow_up_tools() -> None:
    payload = {
        "compact_summary": {
            "target": "unstaged changes",
            "changed_file_count": 12,
            "follow_up_tools": [
                {
                    "tool": "change_impact_report",
                    "target": "services/api_impact_service.py",
                    "why": "Run a narrower follow-up if whole-tree traversal was capped.",
                },
                {
                    "tool": "find_tests_for_target",
                    "target": "services/api_impact_service.py",
                    "why": "Find focused tests for this slice.",
                },
            ],
        },
        "pre_commit_workflow": {
            "readiness": {"status": "not_ready", "ready_to_commit": False},
            "follow_up_tools": [
                {
                    "tool": "get_source_context",
                    "target": "services/api_impact_service.py",
                    "why": "Inspect the highest-risk changed file in this slice.",
                },
                {
                    "tool": "change_impact_report",
                    "target": "services/api_impact_service.py",
                    "why": "Run a narrower follow-up if whole-tree traversal was capped.",
                },
            ],
        },
    }

    enriched = enrich_payload(payload)

    assert enriched["next_tools"] == [
        {
            "tool": "get_source_context",
            "target": "services/api_impact_service.py",
            "why": "Inspect the highest-risk changed file in this slice.",
        },
        {
            "tool": "change_impact_report",
            "target": "services/api_impact_service.py",
            "why": "Run a narrower follow-up if whole-tree traversal was capped.",
        },
        {
            "tool": "find_tests_for_target",
            "target": "services/api_impact_service.py",
            "why": "Find focused tests for this slice.",
        },
    ]
    assert enriched["compact_summary"]["next_tools"] == enriched["next_tools"]


def test_enrich_payload_prioritizes_field_and_process_blast_radius_tools() -> None:
    payload = {
        "compact_summary": {
            "target": "unstaged changes",
            "changed_file_count": 3,
            "field_blast_radius": [
                {
                    "route": "/products/trends",
                    "field": "metrics.intransit_stock",
                    "follow_up": {
                        "tool": "field_impact",
                        "target": "/products/trends metrics.intransit_stock",
                        "why": "Show exact field readers and missing-response risk for this route field.",
                    },
                }
            ],
            "process_blast_radius": [
                {
                    "name": "backend: get_product_trends -> get_db_path",
                    "changed_symbol": "get_product_trend_data",
                }
            ],
            "follow_up_tools": [
                {
                    "tool": "get_source_context",
                    "target": "backend/routers/products.py",
                    "why": "Inspect the highest-risk changed file in this slice.",
                }
            ],
        },
        "pre_commit_workflow": {
            "field_blast_radius": [
                {
                    "route": "/products/trends",
                    "field": "metrics.intransit_stock",
                }
            ],
            "process_blast_radius": [
                {
                    "changed_symbol": "get_product_trend_data",
                    "entry_symbol": "get_product_trends",
                }
            ],
        },
    }

    enriched = enrich_payload(payload)

    assert enriched["next_tools"][:3] == [
        {
            "tool": "field_impact",
            "target": "/products/trends metrics.intransit_stock",
            "why": "Show exact field readers and missing-response risk for this route field.",
        },
        {
            "tool": "trace_processes",
            "target": "get_product_trend_data",
            "why": "Trace the execution flow that includes the changed symbol.",
        },
        {
            "tool": "get_source_context",
            "target": "backend/routers/products.py",
            "why": "Inspect the highest-risk changed file in this slice.",
        },
    ]
    assert enriched["compact_summary"]["next_tools"] == enriched["next_tools"]


def test_enrich_payload_promotes_change_report_top_files_and_symbols() -> None:
    payload = {
        "compact_summary": {
            "target": "indexing/parsers/python.py",
            "top_changed_files": ["indexing/parsers/python.py"],
            "top_risk_files": ["scripts/run_mcp.py"],
            "top_changed_symbols": ["extract_symbols", "extract_symbols.visit"],
            "top_impacted": ["parse"],
        },
    }

    enriched = enrich_payload(payload)

    assert enriched["top_files"] == ["indexing/parsers/python.py", "scripts/run_mcp.py"]
    assert enriched["top_symbols"] == ["extract_symbols", "extract_symbols.visit", "parse"]
    assert enriched["compact_summary"]["top_files"] == enriched["top_files"]
    assert enriched["compact_summary"]["top_symbols"] == enriched["top_symbols"]


def test_enrich_payload_marks_capped_reports_partial_even_when_payload_says_false() -> None:
    payload = {
        "target": "unstaged changes",
        "partial": False,
        "warnings": [
            "Graph blast-radius traversal skipped for 25 changed files; narrow the scope or target a file/symbol for full graph impact.",
            "Process tracing skipped for broad diff; use trace_processes on a focused target for full flows.",
        ],
        "compact_summary": {
            "changed_file_count": 25,
            "changed_symbol_count": 164,
        },
    }

    enriched = enrich_payload(payload)

    assert enriched["partial"] is True
    assert enriched["compact_summary"]["partial"] is True


def test_enrich_payload_strips_large_embedding_vectors() -> None:
    payload = {
        "target": "app.main",
        "search": {
            "results": [
                {
                    "file_path": "app/main.py",
                    "vector": [0.1, 0.2],
                }
            ]
        },
    }

    enriched = enrich_payload(payload)

    assert "vector" not in enriched["search"]["results"][0]
