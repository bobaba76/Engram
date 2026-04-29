from pathlib import Path

from services.app_context_service import app_context


class _Files:
    def fetch_all(self):
        return [{"path": "backend/routers/customers.py"}]


class _Processes:
    def fetch_clusters(self, limit=100, query=""):
        return [
            {
                "cluster_id": "p1",
                "name": "Customer assignment",
                "process_type": "business",
                "file_paths_json": '["backend/routers/customers.py", "backend/repositories/customers.py"]',
                "process_count": 2,
            }
        ]


class _Duck:
    files = _Files()
    processes = _Processes()

    def fetch_symbols_for_file(self, file_path):
        return [
            {
                "name": "get_customers",
                "qualified_name": "get_customers",
                "kind": "function",
                "start_line": 3,
                "end_line": 6,
            }
        ]

    def fetch_symbols_for_target(self, target, limit=50):
        return [
            {
                "file_path": "backend/routers/customers.py",
                "name": "get_customers",
                "qualified_name": "get_customers",
                "kind": "function",
            }
        ]


class _Kuzu:
    def edges_for_source(self, source, relation=None):
        return [{"source": source, "relation": "CALLS", "target": "load_customers"}]

    def edges_for_target(self, target, relation=None):
        return []


def test_app_context_links_routes_files_tables_and_processes(tmp_path: Path) -> None:
    router = tmp_path / "backend" / "routers"
    repo = tmp_path / "backend" / "repositories"
    router.mkdir(parents=True)
    repo.mkdir(parents=True)
    (router / "customers.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/customers')\n"
        "def get_customers():\n"
        "    return {'customers': []}\n",
        encoding="utf-8",
    )
    (repo / "customers.py").write_text("SELECT * FROM customers\n", encoding="utf-8")

    result = app_context(tmp_path, _Duck(), _Kuzu(), target="/customers")

    assert result["compact_summary"]["route_count"] == 1
    assert "backend/routers/customers.py" in result["compact_summary"]["top_files"]
    assert result["compact_summary"]["top_processes"] == ["Customer assignment"]


class _FrontendDuck(_Duck):
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
        return super().fetch_symbols_for_file(file_path)

    def fetch_symbols_for_target(self, target, limit=50):
        return [
            {
                "file_path": "frontend/components/CustomerView.tsx",
                "name": "CustomerView",
                "qualified_name": "frontend.components.CustomerView.CustomerView",
                "kind": "component",
            },
            {
                "file_path": "frontend/hooks/useCustomer.ts",
                "name": "useCustomer",
                "qualified_name": "frontend.hooks.useCustomer.useCustomer",
                "kind": "hook",
            },
        ]


class _FrontendKuzu:
    def edges_for_source(self, source, relation=None):
        if source == "frontend.components.CustomerView.CustomerView":
            return [{"source": source, "relation": "CALLS", "target": "frontend.hooks.useCustomer.useCustomer"}]
        return []

    def edges_for_target(self, target, relation=None):
        if target == "frontend.hooks.useCustomer.useCustomer":
            return [{"source": "frontend.components.CustomerView.CustomerView", "relation": "CALLS", "target": target}]
        return []


def test_app_context_summarizes_frontend_graph_paths(tmp_path: Path) -> None:
    frontend_components = tmp_path / "frontend" / "components"
    frontend_hooks = tmp_path / "frontend" / "hooks"
    frontend_components.mkdir(parents=True)
    frontend_hooks.mkdir(parents=True)
    (frontend_components / "CustomerView.tsx").write_text("export function CustomerView() { return null }\n", encoding="utf-8")
    (frontend_hooks / "useCustomer.ts").write_text("export function useCustomer() { return null }\n", encoding="utf-8")

    result = app_context(tmp_path, _FrontendDuck(), _FrontendKuzu(), target="CustomerView")

    assert result["frontend_graph"]["has_indirect_frontend_path"] is True
    assert result["frontend_graph"]["frontend_file_count"] == 2
    assert result["frontend_graph"]["frontend_graph_edge_count"] >= 1
    assert "frontend/components/CustomerView.tsx" in result["frontend_graph"]["top_frontend_files"]
    assert result["compact_summary"]["frontend_graph"]["has_indirect_frontend_path"] is True
    assert "graph-linked TS/TSX files" in result["compact_summary"]["frontend_graph"]["summary"]


def test_app_context_broad_target_skips_route_and_api_fanout(monkeypatch, tmp_path: Path) -> None:
    calls = {"route_map": 0, "api_impact": 0}

    monkeypatch.setattr(
        "services.app_context_service.route_map",
        lambda repo_root, duckdb_store, route="": calls.__setitem__("route_map", calls["route_map"] + 1) or {"routes": []},
    )
    monkeypatch.setattr(
        "services.app_context_service.api_impact",
        lambda repo_root, duckdb_store, route="": calls.__setitem__("api_impact", calls["api_impact"] + 1) or {"routes": []},
    )

    result = app_context(tmp_path, _Duck(), _Kuzu(), target="CustomerAnalysis")

    assert calls["route_map"] == 0
    assert calls["api_impact"] == 0
    assert result["guardrail"]["route_scan_skipped"] is True
    assert result["guardrail"]["api_impact_skipped"] is True
    assert any("broad" in warning for warning in result["warnings"])
