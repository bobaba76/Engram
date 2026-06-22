"""MCP tool handler functions.

Each handler takes an ``MCPSession`` as the first argument and delegates to
the appropriate service.  These were previously closures inside ``run_mcp.main()``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.run_modes import INCREMENTAL
from indexing.embeddings import get_model_load_error, is_model_ready, prewarm_jina_model
from mcp_server.git_change_cache import fast_repo_root_for_tool, mcp_change_preflight_payload
from mcp_server.mcp_session import MCPSession
from mcp_server.resolvers import resolve_tool_target
from services.api_impact_service import api_impact
from services.app_context_service import app_context
from services.change_report_service import change_impact_report
from services.detect_changes_service import detect_changes
from services.dependency_service import get_dependencies
from services.feature_context_service import feature_context
from services.field_impact_service import field_impact
from services.file_summary_service import get_file_summary
from services.graph_query_service import execute_graph_query
from services.graph_service import get_callers_and_callees, get_graph_neighborhood_with_options
from services.impact_service import analyze_impact
from services.index_health_service import index_health
from services.index_status_service import get_index_status, get_recent_runs, get_run_metrics
from services.investigation_service import (
    broad_lexical_search_terms,
    investigate_codebase,
    investigation_search_task,
)
from services.process_catalog_service import get_symbol_process_participation, list_processes
from services.process_service import trace_execution_flows
from services.rename_service import preview_rename
from services.repo_registry_service import list_indexed_repos, resolve_indexed_repo
from services.review_history_service import get_review_history
from services.route_map_service import route_map
from services.semantic_search import semantic_code_search
from services.shape_check_service import shape_check
from services.source_retrieval_service import get_source_context
from services.symbol_context_service import get_symbol_context
from services.symbol_lookup_service import find_symbols
from services.test_intelligence_service import find_tests_for_target, suggest_tests_for_change, test_impact
from services.unified_context_service import get_unified_context


def _resolve_graph_target(session: MCPSession, target: str, repo: str = "") -> str:
    """Resolve a short target name to a qualified_name for graph queries.

    Graph nodes are stored by qualified_name (e.g. "products.ProductsTableShell.ProductsTableShell"),
    but users often pass a short name (e.g. "ProductsTableShell").  This helper uses DuckDB symbol
    resolution to find the qualified_name.  If the target is already a UID or cannot be resolved,
    it is returned unchanged so existing behaviour is preserved.
    """
    from services.symbol_resolution_service import resolve_candidates, symbol_uid_from_target

    resolved_uid = symbol_uid_from_target(target)
    lookup = str(target or "").strip()
    if resolved_uid and resolved_uid == lookup:
        lookup = ""
    if not lookup and not resolved_uid:
        return str(target or "").strip()
    context = session.get_repo_context(repo)
    candidates = resolve_candidates(context["duckdb_store"], target=lookup, symbol_uid_value=resolved_uid, limit=1)
    if candidates:
        symbol = candidates[0].get("symbol", {}) if isinstance(candidates[0], dict) else {}
        qn = str(symbol.get("qualified_name", "") or "").strip()
        if qn:
            return qn
    return str(target or "").strip()


def index_status(session: MCPSession, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return get_index_status(context["manifest"])


def list_repos_tool(session: MCPSession) -> dict[str, object]:
    payload = list_indexed_repos(session.selected_repo_root)
    payload["selected_repo"] = str(session.selected_repo_root)
    payload["compact_summary"]["selected_repo"] = session.selected_repo_root.name
    return payload


def select_repo_tool(session: MCPSession, repo: str) -> dict[str, object]:
    resolved_repo_root = resolve_indexed_repo(session.selected_repo_root, repo)
    session.selected_repo_root = resolved_repo_root
    context = session.get_repo_context()
    return {
        "selected_repo": str(session.selected_repo_root),
        "repo_root": str(session.selected_repo_root),
        "repo_name": session.selected_repo_root.name,
        "repo_selection": {
            "mode": "selected_repo_updated",
            "requested_repo": repo,
            "resolved_repo_root": str(session.selected_repo_root),
            "resolved_repo_name": session.selected_repo_root.name,
        },
        "manifest": context["manifest"],
        "summary_text": f"Selected repo: {session.selected_repo_root}",
        "highlights": [f"Selected repo: {session.selected_repo_root.name}", f"Repo root: {session.selected_repo_root}"],
        "compact_summary": {
            "selected_repo": session.selected_repo_root.name,
            "repo_root": str(session.selected_repo_root),
            "repo_selection_mode": "selected_repo_updated",
        },
    }


def get_recent_runs_tool(session: MCPSession, limit: int = 10, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return get_recent_runs(context["duckdb_store"], limit=limit)


def get_run_metrics_tool(session: MCPSession, run_id: str, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return get_run_metrics(context["duckdb_store"], run_id=run_id)


def reindex_project_tool(session: MCPSession, project_root: str = "", run_mode: str = INCREMENTAL, background: bool = True) -> dict[str, object]:
    from mcp_server.project_resolution import index_project

    target_root = Path(project_root).resolve() if str(project_root or '').strip() else session.settings.repo_root
    if background:
        return session.start_background_reindex(target_root, run_mode)
    session.close_all_repo_contexts()
    result = index_project(target_root, run_mode=run_mode)
    session.refresh_selected_manifest(target_root, result["manifest"] if isinstance(result["manifest"], dict) else {})
    return result


def reindex_status_tool(session: MCPSession, job_id: str) -> dict[str, object]:
    return session.reindex_status_payload(job_id)


def unified_context_tool(
    session: MCPSession,
    target: str,
    max_matches: int = 5,
    neighborhood_depth: int = 1,
    file_path: str = "",
    kind: str = "",
    symbol_uid: str = "",
    repo: str = "",
) -> dict[str, object]:
    context = session.get_repo_context(repo)
    return get_unified_context(
        context["duckdb_store"],
        session.get_kuzu_store(repo),
        target=target,
        max_matches=max_matches,
        neighborhood_depth=neighborhood_depth,
        file_path=file_path or None,
        kind=kind or None,
        symbol_uid=symbol_uid or None,
    )


def impact_analysis_tool(
    session: MCPSession,
    target: str,
    direction: str = "upstream",
    max_depth: int = 3,
    file_path: str = "",
    kind: str = "",
    symbol_uid: str = "",
    repo: str = "",
) -> dict[str, object]:
    context = session.get_repo_context(repo)
    return analyze_impact(
        context["duckdb_store"],
        session.get_kuzu_store(repo),
        target=target,
        direction=direction,
        max_depth=max_depth,
        file_path=file_path or None,
        kind=kind or None,
        symbol_uid=symbol_uid or None,
    )


def graph_query_tool(session: MCPSession, query: str, limit: int = 100, repo: str = "") -> dict[str, object]:
    return execute_graph_query(session.get_kuzu_store(repo), query=query, limit=limit)


def detect_changes_tool(session: MCPSession, scope: str = "unstaged", base_ref: str = "", repo: str = "") -> dict[str, object]:
    cached_changes = session.detect_changes_from_cache(scope, base_ref, repo)
    if cached_changes is not None:
        return cached_changes
    repo_root = fast_repo_root_for_tool(session.selected_repo_root, repo)
    from mcp_server.git_change_cache import mcp_git_changed_files

    changed_files, normalized_scope = mcp_git_changed_files(repo_root, scope, base_ref)
    preflight = mcp_change_preflight_payload(repo_root, scope, base_ref, changed_files, normalized_scope, force=True)
    if preflight is not None or normalized_scope == "staged":
        return preflight
    context = session.get_repo_context(repo)
    return detect_changes(
        context["repo_root"],
        context["duckdb_store"],
        session.lazy_kuzu(repo),
        scope=scope,
        base_ref=base_ref or None,
    )


def route_map_tool(session: MCPSession, route: str = "", repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return route_map(context["repo_root"], context["duckdb_store"], route=route)


def api_impact_tool(session: MCPSession, route: str = "", repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return api_impact(context["repo_root"], context["duckdb_store"], route=route, kuzu_store=session.lazy_kuzu(repo))


def shape_check_tool(session: MCPSession, route: str = "", repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return shape_check(context["repo_root"], context["duckdb_store"], route=route, kuzu_store=session.lazy_kuzu(repo))


def field_impact_tool(session: MCPSession, field: str, route: str = "", repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return field_impact(
        context["repo_root"],
        context["duckdb_store"],
        field=field,
        route=route,
        kuzu_store=session.lazy_kuzu(repo),
    )


def app_context_tool(session: MCPSession, target: str = "", limit: int = 12, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return app_context(
        context["repo_root"],
        context["duckdb_store"],
        session.get_kuzu_store(repo),
        target=target,
        limit=limit,
    )


def resolve_target_tool(
    session: MCPSession,
    target: str = "",
    file_path: str = "",
    kind: str = "",
    symbol_uid: str = "",
    limit: int = 5,
    repo: str = "",
) -> dict[str, object]:
    context = session.get_repo_context(repo)
    return resolve_tool_target(
        context["duckdb_store"],
        context["repo_root"],
        target=target,
        file_path=file_path or None,
        kind=kind or None,
        symbol_uid=symbol_uid or None,
        limit=limit,
    )


def trace_processes_tool(
    session: MCPSession,
    target: str,
    file_path: str = "",
    kind: str = "",
    symbol_uid: str = "",
    max_depth: int = 4,
    max_flows: int = 8,
    changed_symbols: str = "",
    repo: str = "",
) -> dict[str, object]:
    context = session.get_repo_context(repo)
    changed_symbol_list = [item.strip() for item in changed_symbols.split(",") if item.strip()]
    return trace_execution_flows(
        context["duckdb_store"],
        session.get_kuzu_store(repo),
        target=target,
        file_path=file_path or None,
        kind=kind or None,
        symbol_uid=symbol_uid or None,
        max_depth=max_depth,
        max_flows=max_flows,
        changed_symbols=changed_symbol_list or None,
    )


def list_processes_tool(session: MCPSession, query: str = "", limit: int = 25, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return list_processes(context["duckdb_store"], query=query, limit=limit)


def symbol_process_participation_tool(
    session: MCPSession,
    target: str,
    file_path: str = "",
    kind: str = "",
    symbol_uid: str = "",
    limit: int = 25,
    repo: str = "",
) -> dict[str, object]:
    context = session.get_repo_context(repo)
    return get_symbol_process_participation(
        context["duckdb_store"],
        target=target,
        file_path=file_path or None,
        kind=kind or None,
        symbol_uid=symbol_uid or None,
        limit=limit,
    )


def preview_rename_tool(session: MCPSession, symbol_name: str, new_name: str, file_path: str = "", symbol_uid: str = "", repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return preview_rename(
        context["repo_root"],
        context["duckdb_store"],
        session.get_kuzu_store(repo),
        symbol_name=symbol_name,
        new_name=new_name,
        file_path=file_path or None,
        symbol_uid=symbol_uid or None,
    )


def semantic_code_search_tool(session: MCPSession, task: str, limit: int = 5, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    model_name = context["settings"].embedding_model
    prewarm_jina_model(model_name, device=context["settings"].embedding_device)
    model_ready = is_model_ready(model_name)
    load_error = get_model_load_error(model_name) if not model_ready else ""
    result = semantic_code_search(
        context["vector_store"],
        task=task,
        model_name=model_name,
        duckdb_store=context["duckdb_store"],
        kuzu_store=session.get_kuzu_store(repo),
        limit=limit,
        max_length=context["settings"].embedding_max_length,
        device=context["settings"].embedding_device,
        provider_name=context["settings"].embedding_provider,
        api_key=context["settings"].embedding_api_key,
        base_url=context["settings"].embedding_base_url,
        include_vector=model_ready,
    )
    if not model_ready:
        warnings = result.setdefault("warnings", [])
        if load_error:
            warnings.append(f"Vector search unavailable: embedding model failed to load ({load_error}). Results are lexical-only.")
        else:
            warnings.append(
                "Vector search unavailable: embedding model not yet loaded. Results are lexical-only. Try again in a few seconds."
            )
        result["degraded"] = True
        result["missing_capabilities"] = ["vector_search"]
    return result


def investigate_codebase_tool(session: MCPSession, question: str, limit: int = 5, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    prewarm_jina_model(context["settings"].embedding_model, device=context["settings"].embedding_device)
    search_task, search_plan = investigation_search_task(question, limit=limit)
    intent = search_plan.get("intent", {}) if isinstance(search_plan.get("intent", {}), dict) else {}
    guardrails = search_plan.get("guardrails", {}) if isinstance(search_plan.get("guardrails", {}), dict) else {}
    intent_primary = str(intent.get("primary", "general") or "general")
    broad_question = bool(guardrails.get("broad_question"))
    impact_question = intent_primary == "impact"
    exploratory_question = intent_primary in {"ui_ownership", "feature_exploration"}
    lightweight_exploratory = bool(exploratory_question and (broad_question or len(intent.get("tokens", [])) >= 8))
    safe_first_pass = broad_question or impact_question
    if lightweight_exploratory:
        return investigate_codebase(
            context["repo_root"],
            context["duckdb_store"],
            session.get_kuzu_store(repo),
            question=question,
            search_payload={
                "compact_results": [],
                "retrieval_diagnostics": {
                    "exploratory_budget_short_circuit": True,
                    "investigation_safe_first_pass": True,
                    "exploratory_lightweight_path": True,
                },
                "investigation_search_plan": search_plan,
            },
            limit=limit,
        )
    search_limit = int(guardrails.get("search_limit", limit) or limit)
    lexical_terms = broad_lexical_search_terms(search_task, search_plan.get("query_rewrite", {}), limit=4) if safe_first_pass else [search_task]
    model_ready = is_model_ready(context["settings"].embedding_model)
    search_payload = semantic_code_search(
        context["vector_store"],
        task=search_task,
        model_name=context["settings"].embedding_model,
        duckdb_store=context["duckdb_store"],
        kuzu_store=session.get_kuzu_store(repo),
        limit=search_limit,
        max_length=context["settings"].embedding_max_length,
        device=context["settings"].embedding_device,
        provider_name=context["settings"].embedding_provider,
        api_key=context["settings"].embedding_api_key,
        base_url=context["settings"].embedding_base_url,
        max_variants=1 if safe_first_pass else 3,
        include_vector=(not safe_first_pass) and model_ready,
        include_graph=not safe_first_pass,
        include_expansion=not safe_first_pass,
        extra_query_terms=lexical_terms,
    )
    if safe_first_pass and isinstance(search_payload, dict):
        retrieval_diag = search_payload.get("retrieval_diagnostics", {})
        if isinstance(retrieval_diag, dict):
            retrieval_diag["investigation_safe_first_pass"] = True
            retrieval_diag["impact_safe_path"] = impact_question
            retrieval_diag["broad_safe_path"] = broad_question
    if safe_first_pass and isinstance(search_payload, dict) and not search_payload.get("compact_results") and model_ready:
        fallback_payload = semantic_code_search(
            context["vector_store"],
            task=search_task,
            model_name=context["settings"].embedding_model,
            duckdb_store=context["duckdb_store"],
            kuzu_store=session.get_kuzu_store(repo),
            limit=min(search_limit, 3),
            max_length=context["settings"].embedding_max_length,
            device=context["settings"].embedding_device,
            provider_name=context["settings"].embedding_provider,
            api_key=context["settings"].embedding_api_key,
            base_url=context["settings"].embedding_base_url,
            max_variants=1,
            include_vector=True,
            include_graph=False,
            include_expansion=False,
            extra_query_terms=lexical_terms,
        )
        if isinstance(fallback_payload, dict):
            fallback_payload["investigation_search_plan"] = search_plan
            fallback_diag = fallback_payload.get("retrieval_diagnostics", {})
            if isinstance(fallback_diag, dict):
                fallback_diag["fallback_from_lexical_only"] = True
                fallback_diag["impact_safe_path"] = impact_question
                fallback_diag["broad_safe_path"] = broad_question
            search_payload = fallback_payload
    elif safe_first_pass and isinstance(search_payload, dict) and not search_payload.get("compact_results"):
        fallback_diag = search_payload.get("retrieval_diagnostics", {})
        if isinstance(fallback_diag, dict):
            fallback_diag["fallback_from_lexical_only"] = False
            fallback_diag["fallback_skipped_broad_target"] = True
            fallback_diag["impact_safe_path"] = impact_question
            fallback_diag["broad_safe_path"] = broad_question
    if isinstance(search_payload, dict):
        search_payload.setdefault("investigation_search_plan", search_plan)
    return investigate_codebase(
        context["repo_root"],
        context["duckdb_store"],
        session.get_kuzu_store(repo),
        question=question,
        search_payload=search_payload,
        limit=limit,
    )


def change_impact_report_tool(session: MCPSession, scope: str = "unstaged", base_ref: str = "", max_symbols: int = 5, repo: str = "", target: str = "") -> dict[str, object]:
    cached_changes = session.detect_changes_from_cache(scope, base_ref, repo)
    if cached_changes is not None:
        context = session.get_repo_context(repo)
        return change_impact_report(
            context["repo_root"],
            context["duckdb_store"],
            session.lazy_kuzu(repo),
            scope=scope,
            base_ref=base_ref,
            max_symbols=max_symbols,
            changes=cached_changes,
            target=target,
        )
    repo_root = fast_repo_root_for_tool(session.selected_repo_root, repo)
    from mcp_server.git_change_cache import mcp_git_changed_files

    changed_files, normalized_scope = mcp_git_changed_files(repo_root, scope, base_ref)
    preflight = mcp_change_preflight_payload(repo_root, scope, base_ref, changed_files, normalized_scope, force=True)
    if preflight is not None and not target:
        return {
            "scope": normalized_scope,
            "base_ref": base_ref,
            "risk": preflight.get("risk", "LOW"),
            "confidence": preflight.get("confidence", "low"),
            "risk_scope": preflight.get("risk_scope", normalized_scope),
            "risk_explanation": preflight.get("risk_explanation", []),
            "risk_by_file": preflight.get("risk_by_file", []),
            "git": preflight.get("git", {}),
            "changed_routes": [],
            "affected_consumers": [],
            "changed_response_shapes": [],
            "risk_by_route": [],
            "shape_mismatches": [],
            "affected_processes": [],
            "risk_by_process": [],
            "changes": preflight,
            "symbol_impacts": [],
            "app_contexts": [],
            "frontend_graph": {
                "frontend_file_count": len([path for path in changed_files if path.lower().endswith((".ts", ".tsx", ".js", ".jsx"))]),
                "top_frontend_files": [path for path in changed_files if path.lower().endswith((".ts", ".tsx", ".js", ".jsx"))][:6],
                "frontend_graph_edge_count": 0,
                "top_relations": {},
                "has_indirect_frontend_path": False,
                "summary": "Preflight response only; route consumer graph not traversed.",
            },
            "test_recommendations": {"compact_summary": {"top_files": []}, "recommended_tests": []},
            "what_changed": [f"{len(changed_files)} files changed.", "Symbol analysis skipped by MCP preflight."],
            "what_to_test": [],
            "warnings": preflight.get("warnings", []),
            "partial": preflight.get("partial", False),
            "compact_summary": {
                **dict(preflight.get("compact_summary", {}) if isinstance(preflight.get("compact_summary", {}), dict) else {}),
                "frontend_graph": {
                    "frontend_file_count": len([path for path in changed_files if path.lower().endswith((".ts", ".tsx", ".js", ".jsx"))]),
                    "top_frontend_files": [path for path in changed_files if path.lower().endswith((".ts", ".tsx", ".js", ".jsx"))][:6],
                    "frontend_graph_edge_count": 0,
                    "has_indirect_frontend_path": False,
                },
            },
        }
    context = session.get_repo_context(repo)
    return change_impact_report(
        context["repo_root"],
        context["duckdb_store"],
        session.lazy_kuzu(repo),
        scope=scope,
        base_ref=base_ref,
        max_symbols=max_symbols,
        target=target,
    )


def find_tests_for_target_tool(session: MCPSession, target: str, limit: int = 10, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return find_tests_for_target(context["duckdb_store"], target=target, limit=limit, kuzu_store=session.lazy_kuzu(repo))


def suggest_tests_for_change_tool(session: MCPSession, scope: str = "unstaged", base_ref: str = "", repo: str = "") -> dict[str, object]:
    cached_changes = session.detect_changes_from_cache(scope, base_ref, repo)
    if cached_changes is not None:
        context = session.get_repo_context(repo)
        return suggest_tests_for_change(
            context["repo_root"],
            context["duckdb_store"],
            session.lazy_kuzu(repo),
            scope=scope,
            base_ref=base_ref,
            changes=cached_changes,
        )
    repo_root = fast_repo_root_for_tool(session.selected_repo_root, repo)
    from mcp_server.git_change_cache import mcp_git_changed_files

    changed_files, normalized_scope = mcp_git_changed_files(repo_root, scope, base_ref)
    preflight = mcp_change_preflight_payload(repo_root, scope, base_ref, changed_files, normalized_scope, force=True)
    if preflight is not None:
        return {
            "scope": normalized_scope,
            "base_ref": base_ref,
            "changes": preflight,
            "recommended_tests": [],
            "compact_results": [],
            "warnings": preflight.get("warnings", []),
            "partial": True,
            "compact_summary": {
                "target": f"{normalized_scope} changes",
                "changed_file_count": len(changed_files),
                "test_count": 0,
                "top_files": [],
                "status": "partial",
                "partial": True,
            },
            "status": "partial",
        }
    context = session.get_repo_context(repo)
    return suggest_tests_for_change(context["repo_root"], context["duckdb_store"], session.lazy_kuzu(repo), scope=scope, base_ref=base_ref)


def test_impact_tool(session: MCPSession, scope: str = "unstaged", base_ref: str = "", repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return test_impact(context["repo_root"], context["duckdb_store"], session.lazy_kuzu(repo), scope=scope, base_ref=base_ref)


def feature_context_tool(session: MCPSession, feature: str, limit: int = 12, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return feature_context(context["repo_root"], context["duckdb_store"], session.get_kuzu_store(repo), feature=feature, limit=limit)


def index_health_tool(session: MCPSession, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return index_health(context["repo_root"], context["duckdb_store"], session.get_kuzu_store(repo))


def get_dependencies_tool(session: MCPSession, target: str, repo: str = "") -> dict[str, object]:
    resolved = _resolve_graph_target(session, target, repo)
    return get_dependencies(session.get_kuzu_store(repo), target=resolved)


def get_review_history_tool(session: MCPSession, target: str, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return get_review_history(context["duckdb_store"], target=target)


def get_symbol_context_tool(session: MCPSession, target: str, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return get_symbol_context(duckdb_store=context["duckdb_store"], kuzu_store=session.get_kuzu_store(repo), target=target)


def find_symbols_tool(session: MCPSession, query: str, limit: int = 10, file_path: str = "", kind: str = "", symbol_uid: str = "", repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return find_symbols(context["duckdb_store"], query=query, limit=limit, file_path=file_path or None, kind=kind or None, symbol_uid=symbol_uid or None)


def get_callers_and_callees_tool(session: MCPSession, target: str, repo: str = "") -> dict[str, object]:
    resolved = _resolve_graph_target(session, target, repo)
    return get_callers_and_callees(session.get_kuzu_store(repo), target=resolved)


def get_graph_neighborhood_tool(
    session: MCPSession,
    target: str,
    depth: int = 1,
    relation: str = "",
    max_edges: int = 0,
    mode: str = "full",
    suppress_common_hubs: bool = False,
    repo: str = "",
) -> dict[str, object]:
    resolved = _resolve_graph_target(session, target, repo)
    return get_graph_neighborhood_with_options(
        session.get_kuzu_store(repo),
        target=resolved,
        depth=depth,
        relation=relation or None,
        max_edges=max_edges or None,
        mode=mode,
        suppress_common_hubs=suppress_common_hubs,
    )


def get_file_summary_tool(session: MCPSession, target: str, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return get_file_summary(context["duckdb_store"], target=target)


def get_source_context_tool(session: MCPSession, target: str, limit: int = 5, repo: str = "") -> dict[str, object]:
    context = session.get_repo_context(repo)
    return get_source_context(context["duckdb_store"], target=target, limit=limit, repo_root=context["repo_root"])


# --- Tool registration table -----------------------------------------------

TOOL_DEFINITIONS: list[tuple[str, Any, str]] = [
    ("index_status", index_status, "Show index readiness, counts, versions, and resolved repository metadata."),
    ("list_repos", list_repos_tool, "List indexed sibling repositories Coder can serve."),
    ("select_repo", select_repo_tool, "Select the default repo target for this MCP session."),
    ("get_recent_runs", get_recent_runs_tool, "List recent persisted index runs including parsed stage summaries."),
    ("get_run_metrics", get_run_metrics_tool, "Show parsed persisted stage metrics for a specific run ID."),
    ("reindex_project", reindex_project_tool, "Start an incremental or full index refresh for a repository. Defaults to background mode to avoid MCP client timeouts."),
    ("reindex_status", reindex_status_tool, "Poll a background reindex job started by reindex_project."),
    ("unified_context", unified_context_tool, "Resolve an exact or near-exact target and return matches, callers/callees, dependencies, and graph neighborhood. Prefer after resolve_target for broad names."),
    ("impact_analysis", impact_analysis_tool, "Estimate upstream or downstream impact for a symbol target. Prefer exact symbols or resolved targets; broad inputs may return partial results with warnings."),
    ("graph_query", graph_query_tool, "Execute a read-only graph query against the indexed Kuzu graph."),
    ("detect_changes", detect_changes_tool, "Analyze changed files and related graph impact for the working tree or git ref."),
    ("route_map", route_map_tool, "Map API/frontend route strings to likely files and symbols."),
    ("api_impact", api_impact_tool, "Estimate code impact for an API route."),
    ("shape_check", shape_check_tool, "Check API route response shapes against frontend consumer field reads."),
    ("field_impact", field_impact_tool, "Show which consumers read a specific API response field, optionally within one route."),
    ("app_context", app_context_tool, "Map app-level context across routes, files, tables, graph edges, and processes. Broad natural-language targets are capped for safety and may return partial context."),
    ("resolve_target", resolve_target_tool, "Resolve a file, symbol name, or symbol UID to the indexed target Coder will use. Best first step before graph-heavy symbol tools."),
    ("trace_processes", trace_processes_tool, "Trace execution/process flows around a target symbol."),
    ("list_processes", list_processes_tool, "List inferred process clusters from the indexed codebase."),
    ("symbol_process_participation", symbol_process_participation_tool, "Show process clusters involving a target symbol."),
    ("preview_rename", preview_rename_tool, "Preview references that may need edits for a symbol rename."),
    ("semantic_code_search", semantic_code_search_tool, "Search indexed chunks semantically for a natural language task. Use when you do not yet have an exact symbol or file target."),
    ("investigate_codebase", investigate_codebase_tool, "Safely investigate a natural-language codebase question using search, symbol resolution, snippets, graph, and app context. Broad questions may be narrowed automatically."),
    ("change_impact_report", change_impact_report_tool, "Safely summarize git changes, likely impact, app context, and recommended tests for the current worktree or a base ref."),
    ("find_tests_for_target", find_tests_for_target_tool, "Find likely tests for a symbol, file, or feature target."),
    ("suggest_tests_for_change", suggest_tests_for_change_tool, "Suggest tests for current git changes."),
    ("test_impact", test_impact_tool, "Estimate testing impact and risk for current git changes."),
    ("feature_context", feature_context_tool, "Map a feature to related files, routes, tables, processes, and graph context."),
    ("index_health", index_health_tool, "Report index health, counts, parser/chunk distribution, recent runs, and warnings."),
    ("get_dependencies", get_dependencies_tool, "Show dependency graph context for a target."),
    ("get_review_history", get_review_history_tool, "Show persisted review findings and analyses for a target file."),
    ("get_symbol_context", get_symbol_context_tool, "Show direct symbol metadata and related source context."),
    ("find_symbols", find_symbols_tool, "Find symbols by query, file, kind, or symbol UID. Good follow-up when resolve_target reports ambiguity."),
    ("get_callers_and_callees", get_callers_and_callees_tool, "Show direct CALLS callers and callees for a symbol target."),
    ("get_graph_neighborhood", get_graph_neighborhood_tool, "Show filtered graph neighborhood for a target."),
    ("get_file_summary", get_file_summary_tool, "Summarize indexed symbols and chunks for a file."),
    ("get_source_context", get_source_context_tool, "Return source chunks and previews for a target."),
]
