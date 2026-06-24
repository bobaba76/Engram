from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.app_context_service import app_context
from services.detect_changes_service import detect_changes
from services.impact_service import analyze_impact
from services.test_intelligence_service import suggest_tests_for_change

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


def _merge_frontend_graph_signals(symbol_reports: list[dict[str, object]], app_payloads: list[dict[str, object]]) -> dict[str, object]:
    frontend_files: list[str] = []
    relation_counts: dict[str, int] = {}
    has_indirect = False
    summaries: list[str] = []
    for report in symbol_reports:
        if not isinstance(report, dict):
            continue
        graph = report.get("frontend_graph") or report.get("compact_summary", {}).get("frontend_graph", {})
        if not isinstance(graph, dict):
            continue
        for file_path in graph.get("top_frontend_files", []) if isinstance(graph.get("top_frontend_files", []), list) else []:
            normalized = str(file_path or "").strip()
            if normalized and normalized not in frontend_files:
                frontend_files.append(normalized)
        for relation, count in graph.get("top_relations", {}).items() if isinstance(graph.get("top_relations", {}), dict) else []:
            relation_counts[str(relation)] = relation_counts.get(str(relation), 0) + int(count or 0)
        if bool(graph.get("has_indirect_frontend_path")):
            has_indirect = True
        summary = str(graph.get("summary") or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)
    for payload in app_payloads:
        if not isinstance(payload, dict):
            continue
        graph = payload.get("frontend_graph") or payload.get("compact_summary", {}).get("frontend_graph", {})
        if not isinstance(graph, dict):
            continue
        for file_path in graph.get("top_frontend_files", []) if isinstance(graph.get("top_frontend_files", []), list) else []:
            normalized = str(file_path or "").strip()
            if normalized and normalized not in frontend_files:
                frontend_files.append(normalized)
        for relation, count in graph.get("top_relations", {}).items() if isinstance(graph.get("top_relations", {}), dict) else []:
            relation_counts[str(relation)] = relation_counts.get(str(relation), 0) + int(count or 0)
        if bool(graph.get("has_indirect_frontend_path")):
            has_indirect = True
        summary = str(graph.get("summary") or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)
    merged_summary = summaries[0] if summaries else ""
    return {
        "frontend_file_count": len(frontend_files),
        "top_frontend_files": frontend_files[:6],
        "frontend_graph_edge_count": sum(relation_counts.values()),
        "top_relations": relation_counts,
        "has_indirect_frontend_path": has_indirect,
        "summary": merged_summary,
    }


def _merge_frontend_route_consumers(frontend_graph: dict[str, object], affected_consumers: object) -> dict[str, object]:
    if not isinstance(affected_consumers, list):
        return frontend_graph
    frontend_files = list(frontend_graph.get("top_frontend_files", [])) if isinstance(frontend_graph.get("top_frontend_files", []), list) else []
    fetch_edges: set[tuple[str, str]] = set()
    read_edges: set[tuple[str, str]] = set()
    for consumer in affected_consumers:
        if not isinstance(consumer, dict):
            continue
        file_path = str(consumer.get("file", "") or "").replace("\\", "/")
        if not file_path or not file_path.lower().split("?")[0].endswith((".ts", ".tsx", ".js", ".jsx")):
            continue
        if file_path not in frontend_files:
            frontend_files.append(file_path)
        reads = consumer.get("field_reads", [])
        route = str(consumer.get("route", "") or "")
        function = str(consumer.get("function", "") or consumer.get("symbol", "") or file_path)
        if route:
            fetch_edges.add((function, route))
        if isinstance(reads, list):
            for field in reads:
                field_text = str(field or "")
                if field_text:
                    read_edges.add((function, field_text))
        graph_contract = consumer.get("graph_contract", {}) if isinstance(consumer.get("graph_contract", {}), dict) else {}
        for fetcher in graph_contract.get("fetchers", []) if isinstance(graph_contract.get("fetchers", []), list) else []:
            if not isinstance(fetcher, dict):
                continue
            fetch_symbol = str(fetcher.get("symbol", "") or function)
            fetch_route = str(fetcher.get("route", "") or route)
            if fetch_symbol and fetch_route:
                fetch_edges.add((fetch_symbol, fetch_route))
        for reader in graph_contract.get("field_readers", []) if isinstance(graph_contract.get("field_readers", []), list) else []:
            if not isinstance(reader, dict):
                continue
            reader_symbol = str(reader.get("symbol", "") or function)
            field = str(reader.get("field", "") or "")
            if reader_symbol and field:
                read_edges.add((reader_symbol, field))
    if not frontend_files:
        return frontend_graph
    top_relations = dict(frontend_graph.get("top_relations", {})) if isinstance(frontend_graph.get("top_relations", {}), dict) else {}
    if fetch_edges:
        top_relations["FETCHES"] = max(int(top_relations.get("FETCHES", 0) or 0), len(fetch_edges))
    if read_edges:
        top_relations["READS_FIELD"] = max(int(top_relations.get("READS_FIELD", 0) or 0), len(read_edges))
    summary = str(frontend_graph.get("summary") or "").strip() or "Frontend API consumers are linked through route contracts and field reads."
    edge_count = sum(int(count or 0) for count in top_relations.values())
    return {
        **frontend_graph,
        "frontend_file_count": len(frontend_files),
        "top_frontend_files": frontend_files[:6],
        "frontend_graph_edge_count": max(edge_count, int(frontend_graph.get("frontend_graph_edge_count", 0) or 0)),
        "top_relations": top_relations,
        "has_indirect_frontend_path": bool(frontend_graph.get("has_indirect_frontend_path")) or True,
        "summary": summary,
    }


def _target_matches_path(target: str, file_path: str) -> bool:
    normalized_target = target.replace("\\", "/").strip().lower()
    normalized_path = file_path.replace("\\", "/").strip().lower()
    if not normalized_target:
        return True
    return normalized_path == normalized_target or normalized_path.endswith("/" + normalized_target) or normalized_target in normalized_path


def _filter_changes_to_target(changes: dict[str, object], target: str) -> dict[str, object]:
    from services.change_report_slices import _unique

    normalized_target = str(target or "").strip()
    if not normalized_target:
        return changes
    filtered = dict(changes)
    changed_files = [
        str(path)
        for path in changes.get("changed_files", [])
        if str(path) and _target_matches_path(normalized_target, str(path))
    ] if isinstance(changes.get("changed_files", []), list) else []
    changed_symbols = [
        symbol
        for symbol in changes.get("changed_symbols", [])
        if isinstance(symbol, dict)
        and (
            _target_matches_path(normalized_target, str(symbol.get("file_path", "") or ""))
            or normalized_target.lower() in str(symbol.get("qualified_name") or symbol.get("name") or "").lower()
        )
    ] if isinstance(changes.get("changed_symbols", []), list) else []
    if not changed_files and changed_symbols:
        changed_files = _unique([symbol.get("file_path", "") for symbol in changed_symbols if isinstance(symbol, dict)], limit=20)
    file_set = set(changed_files)
    risk_by_file = [
        row
        for row in changes.get("risk_by_file", [])
        if isinstance(row, dict) and str(row.get("file", "")) in file_set
    ] if isinstance(changes.get("risk_by_file", []), list) else []
    impacted_files = [
        str(path)
        for path in changes.get("impacted_files", [])
        if str(path) and (_target_matches_path(normalized_target, str(path)) or str(path) in file_set)
    ] if isinstance(changes.get("impacted_files", []), list) else []
    impacted_symbols = [
        symbol
        for symbol in changes.get("impacted_symbols", [])
        if isinstance(symbol, dict)
        and (
            _target_matches_path(normalized_target, str(symbol.get("file_path", "") or ""))
            or str(symbol.get("file_path", "") or "") in file_set
        )
    ] if isinstance(changes.get("impacted_symbols", []), list) else []
    affected_consumers = [
        row
        for row in changes.get("affected_consumers", [])
        if isinstance(row, dict)
        and (
            _target_matches_path(normalized_target, str(row.get("file", "") or row.get("file_path", "") or ""))
            or bool(set(row.get("files", []) if isinstance(row.get("files", []), list) else []) & file_set)
        )
    ] if isinstance(changes.get("affected_consumers", []), list) else []
    warnings = [
        str(warning)
        for warning in changes.get("warnings", [])
        if "broad diff" not in str(warning).lower()
        and "blast-radius traversal skipped" not in str(warning).lower()
    ] if isinstance(changes.get("warnings", []), list) else []
    if not changed_files and not changed_symbols:
        warnings.append(f"Focused target {normalized_target} did not match changed files or changed symbols.")
    else:
        warnings.append(f"Focused change report for {normalized_target}.")
    highest = "LOW"
    risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    for row in risk_by_file:
        risk = str(row.get("risk", "LOW") or "LOW")
        if risk_order.get(risk, 0) > risk_order.get(highest, 0):
            highest = risk
    risk_explanation = [
        f"{len(changed_files)} files changed",
        f"{len(changed_symbols)} indexed symbols changed",
        f"{len(impacted_files)} graph-impacted files detected",
    ]
    high_files = [row for row in risk_by_file if isinstance(row, dict) and row.get("risk") in {"HIGH", "CRITICAL"}]
    if high_files:
        risk_explanation.append(f"{len(high_files)} changed files have high-risk characteristics")
    focused_risk = highest if changed_files or changed_symbols else "LOW"
    focused_score = min(len(changed_files) * 2 + len(changed_symbols) * 2 + len(high_files) * 10, 100)
    focused_weighted_factors = [
        f"+{len(changed_files) * 2}: {len(changed_files)} focused changed file(s)",
        f"+{len(changed_symbols) * 2}: {len(changed_symbols)} focused changed symbol(s)",
    ]
    if high_files:
        focused_weighted_factors.append(f"+{len(high_files) * 10}: {len(high_files)} high-risk focused file(s)")
    filtered.update(
        {
            "focused_target": normalized_target,
            "risk_scope": "focused_change_target",
            "risk_applies_to": [normalized_target],
            "not_limited_to_recent_edits": False,
            "changed_files": changed_files,
            "changed_symbols": changed_symbols,
            "risk_by_file": risk_by_file,
            "impacted_files": impacted_files,
            "impacted_symbols": impacted_symbols,
            "affected_consumers": affected_consumers,
            "risk": focused_risk,
            "risk_score": focused_score,
            "risk_score_label": focused_risk,
            "weighted_risk_factors": focused_weighted_factors,
            "confidence_explanation": ["Focused report filtered from the git-aware working-tree snapshot."],
            "warnings": warnings,
            "risk_explanation": risk_explanation,
        }
    )
    compact = dict(changes.get("compact_summary", {}) if isinstance(changes.get("compact_summary", {}), dict) else {})
    compact.update(
        {
            "target": normalized_target,
            "risk_scope": "focused_change_target",
            "changed_file_count": len(changed_files),
            "changed_symbol_count": len(changed_symbols),
            "impacted_file_count": len(impacted_files),
            "risk": filtered["risk"],
            "risk_score": focused_score,
            "risk_score_label": focused_risk,
            "weighted_risk_factors": focused_weighted_factors,
            "risk_explanation": risk_explanation[:6],
            "top_risk_files": [row.get("file", "") for row in risk_by_file if isinstance(row, dict) and row.get("risk") in {"CRITICAL", "HIGH"}][:8],
            "top_changed_files": changed_files[:8],
            "top_changed_symbols": [item.get("qualified_name") or item.get("name") for item in changed_symbols[:8] if isinstance(item, dict)],
            "top_impacted_files": impacted_files[:8],
        }
    )
    filtered["compact_summary"] = compact
    return filtered


def change_impact_report(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    scope: str = "unstaged",
    base_ref: str = "",
    max_symbols: int = 5,
    changes: dict[str, object] | None = None,
    target: str = "",
) -> dict[str, object]:
    from services.change_report_slices import _build_pre_commit_workflow

    changes = changes or detect_changes(repo_root, duckdb_store, kuzu_store, scope=scope, base_ref=base_ref or None)
    if target:
        changes = _filter_changes_to_target(changes, target)
    changed_symbols = changes.get("changed_symbols", []) if isinstance(changes, dict) else []
    symbol_reports = []
    for symbol in changed_symbols[:max_symbols] if isinstance(changed_symbols, list) else []:
        if not isinstance(symbol, dict):
            continue
        target = str(symbol.get("qualified_name") or symbol.get("name") or "")
        if not target:
            continue
        symbol_reports.append(
            analyze_impact(
                duckdb_store,
                kuzu_store,
                target=target,
                file_path=str(symbol.get("file_path", "") or "") or None,
                direction="upstream",
                max_depth=2,
            )
        )
    changed_files = changes.get("changed_files", []) if isinstance(changes, dict) else []
    app_payloads = []
    for file_path in changed_files[:5] if isinstance(changed_files, list) else []:
        app_payloads.append(app_context(repo_root, duckdb_store, kuzu_store, target=str(file_path), limit=5))
    try:
        tests = suggest_tests_for_change(repo_root, duckdb_store, kuzu_store, scope=scope, base_ref=base_ref, changes=changes)
    except TypeError:
        tests = suggest_tests_for_change(repo_root, duckdb_store, kuzu_store, scope=scope, base_ref=base_ref)
    base_risk = changes.get("risk", "LOW") if isinstance(changes, dict) else "UNKNOWN"
    risk = base_risk
    risk_adjustments: list[str] = []
    if risk != "CRITICAL" and any(report.get("risk") == "HIGH" for report in symbol_reports if isinstance(report, dict)):
        risk = "HIGH"
        risk_adjustments.append("Focused graph impact raised report risk to HIGH.")
    elif risk == "LOW" and any(report.get("risk") == "MEDIUM" for report in symbol_reports if isinstance(report, dict)):
        risk = "MEDIUM"
        risk_adjustments.append("Focused graph impact raised report risk to MEDIUM.")
    changed_file_count = len(changed_files) if isinstance(changed_files, list) else 0
    frontend_graph = _merge_frontend_graph_signals(symbol_reports, app_payloads)
    risk_explanation = changes.get("risk_explanation", []) if isinstance(changes, dict) else []
    risk_by_file = changes.get("risk_by_file", []) if isinstance(changes, dict) else []
    risk_scope = changes.get("risk_scope", scope) if isinstance(changes, dict) else scope
    git_metadata = changes.get("git", {}) if isinstance(changes, dict) else {}
    changed_routes = changes.get("changed_routes", []) if isinstance(changes, dict) else []
    affected_consumers = changes.get("affected_consumers", []) if isinstance(changes, dict) else []
    frontend_graph = _merge_frontend_route_consumers(frontend_graph, affected_consumers)
    changed_response_shapes = changes.get("changed_response_shapes", []) if isinstance(changes, dict) else []
    risk_by_route = changes.get("risk_by_route", []) if isinstance(changes, dict) else []
    shape_mismatches = changes.get("shape_mismatches", []) if isinstance(changes, dict) else []
    affected_processes = changes.get("affected_processes", []) if isinstance(changes, dict) else []
    risk_by_process = changes.get("risk_by_process", []) if isinstance(changes, dict) else []
    pre_commit_workflow = _build_pre_commit_workflow(changes, tests) if isinstance(changes, dict) else {"summary": "No change data available.", "recommended_commit_slices": []}
    pre_commit_readiness = pre_commit_workflow.get("readiness", {}) if isinstance(pre_commit_workflow, dict) and isinstance(pre_commit_workflow.get("readiness", {}), dict) else {}
    report_target = str(changes.get("focused_target", "") or f"{scope} changes") if isinstance(changes, dict) else f"{scope} changes"
    return {
        "scope": scope,
        "base_ref": base_ref,
        "risk": risk,
        "risk_after_validation": pre_commit_readiness.get("risk_after_validation", risk),
        "base_change_risk": base_risk,
        "risk_score": changes.get("risk_score") if isinstance(changes, dict) else None,
        "risk_score_label": risk,
        "risk_adjustments": risk_adjustments,
        "weighted_risk_factors": changes.get("weighted_risk_factors", []) if isinstance(changes, dict) else [],
        "confidence": changes.get("confidence", "unknown") if isinstance(changes, dict) else "unknown",
        "confidence_explanation": changes.get("confidence_explanation", []) if isinstance(changes, dict) else [],
        "risk_scope": risk_scope,
        "risk_applies_to": changes.get("risk_applies_to", []) if isinstance(changes, dict) else [],
        "not_limited_to_recent_edits": changes.get("not_limited_to_recent_edits", True) if isinstance(changes, dict) else True,
        "risk_explanation": risk_explanation,
        "risk_by_file": risk_by_file,
        "git": git_metadata,
        "changed_routes": changed_routes,
        "affected_consumers": affected_consumers,
        "changed_response_shapes": changed_response_shapes,
        "risk_by_route": risk_by_route,
        "shape_mismatches": shape_mismatches,
        "affected_processes": affected_processes,
        "risk_by_process": risk_by_process,
        "changes": changes,
        "symbol_impacts": symbol_reports,
        "app_contexts": app_payloads,
        "frontend_graph": frontend_graph,
        "test_recommendations": tests,
        "pre_commit_workflow": pre_commit_workflow,
        "pre_commit_readiness": pre_commit_readiness,
        "what_changed": [
            f"{changed_file_count} files changed.",
            f"{len(changed_symbols) if isinstance(changed_symbols, list) else 0} indexed symbols changed.",
        ],
        "what_can_break": pre_commit_workflow.get("what_can_break", []) if isinstance(pre_commit_workflow, dict) else [],
        "what_to_test": pre_commit_workflow.get("what_to_test", []) if isinstance(pre_commit_workflow, dict) else tests.get("compact_summary", {}).get("top_files", []) if isinstance(tests, dict) else [],
        "warnings": changes.get("warnings", []) if isinstance(changes, dict) else [],
        "compact_summary": {
            "target": report_target,
            "risk": risk,
            "risk_after_validation": pre_commit_readiness.get("risk_after_validation", risk),
            "base_change_risk": base_risk,
            "confidence": changes.get("confidence", "unknown") if isinstance(changes, dict) else "unknown",
            "risk_scope": risk_scope,
            "changed_file_count": changed_file_count,
            "changed_symbol_count": len(changed_symbols) if isinstance(changed_symbols, list) else 0,
            "risk_explanation": risk_explanation[:6] if isinstance(risk_explanation, list) else [],
            "risk_adjustments": risk_adjustments,
            "changed_routes": changed_routes[:8] if isinstance(changed_routes, list) else [],
            "shape_mismatches": [item.get("route", "") for item in shape_mismatches[:8] if isinstance(item, dict)] if isinstance(shape_mismatches, list) else [],
            "affected_consumers": [item.get("file", "") for item in affected_consumers[:8] if isinstance(item, dict)] if isinstance(affected_consumers, list) else [],
            "affected_processes": [item.get("name", "") for item in affected_processes[:8] if isinstance(item, dict)] if isinstance(affected_processes, list) else [],
            "top_risk_files": [
                item.get("file", "")
                for item in risk_by_file[:8]
                if isinstance(item, dict) and item.get("risk") in {"CRITICAL", "HIGH"}
            ] if isinstance(risk_by_file, list) else [],
            "top_changed_files": changed_files[:8] if isinstance(changed_files, list) else [],
            "top_impacted": [
                report.get("compact_summary", {}).get("target", "")
                for report in symbol_reports[:6]
                if isinstance(report, dict)
            ],
            "top_tests": tests.get("compact_summary", {}).get("top_files", []) if isinstance(tests, dict) else [],
            "pre_commit_slices": [
                {
                    "id": item.get("id", ""),
                    "risk": item.get("risk", "LOW"),
                    "files": item.get("files", [])[:5] if isinstance(item.get("files", []), list) else [],
                    "routes": item.get("routes", [])[:5] if isinstance(item.get("routes", []), list) else [],
                    "fields": item.get("fields", [])[:5] if isinstance(item.get("fields", []), list) else [],
                    "field_blast_radius": item.get("field_blast_radius", [])[:3] if isinstance(item.get("field_blast_radius", []), list) else [],
                    "process_blast_radius": item.get("process_blast_radius", [])[:3] if isinstance(item.get("process_blast_radius", []), list) else [],
                    "validation": item.get("validation", {}) if isinstance(item.get("validation", {}), dict) else {},
                }
                for item in pre_commit_workflow.get("recommended_commit_slices", [])[:6]
                if isinstance(item, dict)
            ] if isinstance(pre_commit_workflow, dict) else [],
            "commit_plan": [
                {
                    "step": item.get("step", 0),
                    "slice_id": item.get("slice_id", ""),
                    "title": item.get("title", ""),
                    "risk": item.get("risk", "LOW"),
                }
                for item in pre_commit_workflow.get("commit_plan", [])[:6]
                if isinstance(item, dict)
            ] if isinstance(pre_commit_workflow, dict) else [],
            "pre_commit_readiness": pre_commit_readiness,
            "validation_summary": pre_commit_workflow.get("validation_summary", {}) if isinstance(pre_commit_workflow, dict) else {},
            "validation_plan": pre_commit_workflow.get("validation_plan", [])[:8] if isinstance(pre_commit_workflow, dict) and isinstance(pre_commit_workflow.get("validation_plan", []), list) else [],
            "residual_risk_by_slice": pre_commit_workflow.get("readiness", {}).get("residual_risk_by_slice", [])[:8] if isinstance(pre_commit_workflow, dict) and isinstance(pre_commit_workflow.get("readiness", {}), dict) else [],
            "field_blast_radius": pre_commit_workflow.get("field_blast_radius", [])[:8] if isinstance(pre_commit_workflow, dict) and isinstance(pre_commit_workflow.get("field_blast_radius", []), list) else [],
            "process_blast_radius": pre_commit_workflow.get("process_blast_radius", [])[:8] if isinstance(pre_commit_workflow, dict) and isinstance(pre_commit_workflow.get("process_blast_radius", []), list) else [],
            "follow_up_tools": pre_commit_workflow.get("follow_up_tools", [])[:6] if isinstance(pre_commit_workflow, dict) and isinstance(pre_commit_workflow.get("follow_up_tools", []), list) else [],
            "frontend_graph": frontend_graph,
        },
    }

