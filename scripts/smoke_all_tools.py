"""Smoke test: call every MCP tool against the real indexed repo."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from config.settings import load_settings
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from storage.manifest_store import ManifestStore

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_session():
    from unittest.mock import MagicMock
    settings = load_settings(REPO_ROOT)
    manifest = ManifestStore(settings.manifest_path).read_current()
    session = MagicMock()
    session.default_repo_root = settings.repo_root
    session.settings = settings
    session.manifest = manifest

    duckdb = DuckDBStore(settings.duckdb_path, read_only=False)
    kuzu = KuzuStore(settings.kuzu_path, read_only=True)

    repo_context = {
        "duckdb_store": duckdb,
        "kuzu_store": kuzu,
        "repo_root": settings.repo_root,
        "manifest": manifest,
        "settings": settings,
    }
    session.get_repo_context = lambda repo="": repo_context
    session.get_kuzu_store = lambda repo="": kuzu
    session.lazy_kuzu = lambda repo="": kuzu
    session.detect_changes_from_cache = lambda scope, base_ref, repo: None
    return session, duckdb, kuzu


def run_tool(name, func, session, **kwargs):
    print(f"\n{'='*60}")
    print(f"TOOL: {name}")
    print(f"ARGS: {kwargs}")
    start = time.time()
    try:
        result = func(session, **kwargs)
        elapsed = round(time.time() - start, 3)
        status = result.get("status", "?") if isinstance(result, dict) else "?"
        compact = result.get("compact_summary", {}) if isinstance(result, dict) else {}
        print(f"STATUS: {status}  ELAPSED: {elapsed}s")
        if compact:
            print(f"SUMMARY: {json.dumps(compact, indent=2, default=str)[:500]}")
        if isinstance(result, dict):
            for key in ("warnings", "error"):
                val = result.get(key)
                if val:
                    print(f"{key.upper()}: {val}")
        return result
    except Exception as exc:
        elapsed = round(time.time() - start, 3)
        print(f"ERROR after {elapsed}s: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return None


def main():
    from mcp_server import tool_handlers as th

    session, duckdb, kuzu = make_session()

    # Find a real symbol to use for symbol-based tools
    rows = duckdb.execute(
        "SELECT qualified_name FROM symbols WHERE kind = 'function' LIMIT 1"
    ).fetchall()
    sample_symbol = str(rows[0][0]) if rows else "detect_changes"
    print(f"Using sample symbol: {sample_symbol}")

    rows = duckdb.execute(
        "SELECT path FROM files WHERE language = 'python' LIMIT 1"
    ).fetchall()
    sample_file = str(rows[0][0]) if rows else "services/detect_changes_service.py"
    print(f"Using sample file: {sample_file}")

    # Find a route if any
    rows = duckdb.execute(
        "SELECT qualified_name FROM symbols WHERE qualified_name LIKE '%route%' OR qualified_name LIKE '%api%' LIMIT 1"
    ).fetchall()
    sample_route = str(rows[0][0]) if rows else ""

    tools = [
        # Index management
        ("index_status", th.index_status, {}),
        ("list_repos", th.list_repos_tool, {}),
        ("get_recent_runs", th.get_recent_runs_tool, {}),
        # Discovery
        ("find_symbols", th.find_symbols_tool, {"query": "detect", "limit": 5}),
        ("get_file_summary", th.get_file_summary_tool, {"target": sample_file}),
        ("get_source_context", th.get_source_context_tool, {"target": sample_file, "limit": 3}),
        # Graph
        ("resolve_target", th.resolve_target_tool, {"target": sample_symbol}),
        ("get_symbol_context", th.get_symbol_context_tool, {"target": sample_symbol}),
        ("get_callers_and_callees", th.get_callers_and_callees_tool, {"target": sample_symbol}),
        ("get_dependencies", th.get_dependencies_tool, {"target": sample_symbol}),
        ("get_graph_neighborhood", th.get_graph_neighborhood_tool, {"target": sample_symbol, "depth": 1}),
        ("impact_analysis", th.impact_analysis_tool, {"target": sample_symbol, "direction": "upstream", "max_depth": 2}),
        ("unified_context", th.unified_context_tool, {"target": sample_symbol}),
        ("graph_query", th.graph_query_tool, {"query": "MATCH (s:Symbol) RETURN s.qualified_name, s.kind LIMIT 5"}),
        # Process
        ("list_processes", th.list_processes_tool, {"limit": 5}),
        ("trace_processes", th.trace_processes_tool, {"target": sample_symbol}),
        ("symbol_process_participation", th.symbol_process_participation_tool, {"target": sample_symbol}),
        # Code quality
        ("detect_circular_dependencies", th.detect_circular_dependencies_tool, {}),
        ("detect_dead_code", th.detect_dead_code_tool, {"limit": 5}),
        # ("detect_duplicate_code", th.detect_duplicate_code_tool, {"limit": 5}),  # needs vector_store
        ("test_coverage_gaps", th.test_coverage_gaps_tool, {"limit": 5}),
        # Rename
        ("preview_rename", th.preview_rename_tool, {"symbol_name": sample_symbol.split(".")[-1], "new_name": "renamed_test", "file_path": sample_file}),
        # Data flow
        ("trace_data_flow", th.trace_data_flow_tool, {"field": "status"}),
        # Route/API (if routes exist)
    ]

    if sample_route:
        tools.append(("route_map", th.route_map_tool, {"route": sample_route}))
        tools.append(("api_impact", th.api_impact_tool, {"route": sample_route}))
        tools.append(("shape_check", th.shape_check_tool, {"route": sample_route}))

    # Feature context
    tools.append(("feature_context", th.feature_context_tool, {"feature": "detect changes", "limit": 5}))

    # Index health
    tools.append(("index_health", th.index_health_tool, {}))

    # Review history
    tools.append(("get_review_history", th.get_review_history_tool, {"target": sample_file}))

    # File dependencies
    tools.append(("get_file_dependencies", th.get_file_dependencies_tool, {"file_path": sample_file}))

    # Stale index
    tools.append(("check_stale_index", th.check_stale_index_tool, {}))

    # --- NEW: Community detection ---
    tools.append(("detect_communities", th.detect_communities_tool, {"min_size": 2, "max_size": 200}))
    tools.append(("list_communities", th.list_communities_tool, {"limit": 10}))

    # After detect_communities, try get_community_detail and get_symbol_community
    # We'll call them after detect_communities returns

    # --- NEW: Repo groups ---
    tools.append(("group_list", th.group_list_tool, {}))

    # Run all tools
    results = {}
    for name, func, kwargs in tools:
        result = run_tool(name, func, session, **kwargs)
        results[name] = result

    # Now try community detail if detect_communities found communities
    if results.get("detect_communities") and isinstance(results["detect_communities"], dict):
        communities = results["detect_communities"].get("communities", [])
        if communities:
            cid = communities[0].get("community_id", "")
            if cid:
                run_tool("get_community_detail", th.get_community_detail_tool, session, community_id=cid)

            # Try get_symbol_community with a member
            members = communities[0].get("members", [])
            if members:
                run_tool("get_symbol_community", th.get_symbol_community_tool, session, target=members[0])

    # Test repo group lifecycle: create -> add -> detail -> sync -> query -> status -> remove -> list
    print(f"\n{'='*60}")
    print("REPO GROUP LIFECYCLE TEST")
    run_tool("group_create", th.group_create_tool, session, group_name="_smoke_test_group", group_path="test")
    run_tool("group_add_repo", th.group_add_repo_tool, session, group_name="_smoke_test_group", repo_name="Coder", hierarchy_path="svc/coder")
    run_tool("group_detail", th.group_detail_tool, session, group_name="_smoke_test_group")
    run_tool("group_query", th.group_query_tool, session, group_name="_smoke_test_group", query="detect", limit=5)
    run_tool("group_status", th.group_status_tool, session, group_name="_smoke_test_group")
    run_tool("group_sync", th.group_sync_tool, session, group_name="_smoke_test_group")
    run_tool("group_remove_repo", th.group_remove_repo_tool, session, group_name="_smoke_test_group", hierarchy_path="svc/coder")
    run_tool("group_list", th.group_list_tool, session)

    # Cleanup: delete the test group
    try:
        duckdb.connection.execute("DELETE FROM repo_group_members WHERE group_name = '_smoke_test_group'")
        duckdb.connection.execute("DELETE FROM repo_groups WHERE group_name = '_smoke_test_group'")
        print("\nCleaned up _smoke_test_group")
    except Exception:
        pass

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    passed = sum(1 for r in results.values() if r is not None and (not isinstance(r, dict) or r.get("status") != "error"))
    failed = sum(1 for r in results.values() if r is None or (isinstance(r, dict) and r.get("status") == "error"))
    print(f"Tools tested: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    duckdb.close()
    kuzu.close()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
