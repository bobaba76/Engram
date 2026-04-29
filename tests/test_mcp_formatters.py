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
