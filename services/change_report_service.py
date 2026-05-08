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


def _slice_key_for_file(file_path: str, changed_routes: list[object], affected_consumers: list[object]) -> tuple[str, str]:
    normalized = file_path.replace("\\", "/").lower()
    name = Path(normalized).name
    if normalized.endswith((".md", ".rst", ".txt")) or "/docs/" in normalized or normalized.startswith("docs/"):
        return ("docs", "Docs and handoff notes")
    if (
        normalized.startswith("tests/")
        or "/tests/" in normalized
        or normalized.startswith("test_")
        or name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", "_test.py"))
    ):
        return ("tests", "Tests")
    routes_for_file = [
        str(route or "")
        for route in changed_routes
        if str(route or "") and (
            "/routers/" in normalized
            or "/routes/" in normalized
            or "/api/" in normalized
            or str(route or "").strip("/").replace("/", "_").lower() in normalized.replace("-", "_")
        )
    ]
    for consumer in affected_consumers:
        if not isinstance(consumer, dict):
            continue
        consumer_file = str(consumer.get("file", "") or "").replace("\\", "/").lower()
        route = str(consumer.get("route", "") or "")
        if consumer_file == normalized and route:
            route_label = route.strip("/") or "root"
            return (f"route:{route}", f"API contract: {route_label}")
    if routes_for_file:
        route = routes_for_file[0]
        route_label = route.strip("/") or "root"
        return (f"route:{route}", f"API contract: {route_label}")
    if normalized.startswith("indexing/") or "/indexing/" in normalized:
        if "/parsers/" in normalized:
            return ("indexing-parsers", "Indexer/parser graph extraction")
        return ("indexing-graph", "Indexer graph construction")
    if normalized.startswith("scripts/run_mcp.py") or normalized.startswith("mcp_server/") or "/mcp_server/" in normalized:
        return ("mcp-runtime", "MCP runtime and tool orchestration")
    if normalized.startswith("storage/") or "/storage/" in normalized:
        return ("graph-storage", "Graph/index storage")
    if normalized.startswith("services/") or "/services/" in normalized:
        if any(part in normalized for part in ("api_impact", "route_map", "shape_check", "detect_changes", "change_report", "process_service", "symbol_context", "impact_service", "unified_context")):
            return ("code-intelligence-services", "Code intelligence services")
        return ("support-services", "Support services")
    if normalized.startswith("frontend/") or "/frontend/" in normalized or normalized.endswith((".tsx", ".jsx", ".ts", ".js")):
        return ("frontend", "Frontend behavior")
    if any(part in normalized for part in ("/repositories/", "/services/", "/processors/", "/database", "backend/database")):
        return ("backend-core", "Backend data/service logic")
    if normalized.startswith("backend/") or "/backend/" in normalized:
        return ("backend", "Backend behavior")
    return ("other", "Other changes")


def _unique(items: list[object], limit: int = 12) -> list[str]:
    values: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in values:
            values.append(text)
        if len(values) >= limit:
            break
    return values


def _unique_dicts(items: list[object], limit: int = 12) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        row = {
            "tool": str(item.get("tool", "") or ""),
            "target": str(item.get("target", "") or ""),
            "why": str(item.get("why", "") or ""),
        }
        key = (row["tool"], row["target"], row["why"])
        if row["tool"] and key not in seen:
            seen.add(key)
            values.append(row)
        if len(values) >= limit:
            break
    return values


def _target_matches_path(target: str, file_path: str) -> bool:
    normalized_target = target.replace("\\", "/").strip().lower()
    normalized_path = file_path.replace("\\", "/").strip().lower()
    if not normalized_target:
        return True
    return normalized_path == normalized_target or normalized_path.endswith("/" + normalized_target) or normalized_target in normalized_path


def _filter_changes_to_target(changes: dict[str, object], target: str) -> dict[str, object]:
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


SLICE_BREAKAGE_HINTS = {
    "indexing-parsers": "Symbol, import, route, or field extraction may be incomplete or over-broad.",
    "indexing-graph": "Graph edges such as CALLS, FETCHES, READS_FIELD, inheritance, or property access may be wrong.",
    "mcp-runtime": "MCP tools may time out, return stale cache data, or miss lazy-loaded graph context.",
    "code-intelligence-services": "Impact, route, shape, process, or change reports may give misleading guidance.",
    "support-services": "Search, context, ranking, or test recommendations may become noisy or incomplete.",
    "graph-storage": "Persisted graph schema or edge reads may break downstream intelligence tools.",
    "frontend": "UI consumers may read stale API fields or render incorrect state.",
    "backend-core": "Backend calculations, repository access, or shared service behavior may change.",
    "backend": "Backend endpoint or service behavior may change.",
    "tests": "Validation coverage or expected behavior may no longer match implementation.",
}


SLICE_ORDER = {
    "route:": 0,
    "backend-core": 1,
    "indexing-parsers": 2,
    "indexing-graph": 3,
    "graph-storage": 4,
    "code-intelligence-services": 5,
    "mcp-runtime": 6,
    "support-services": 7,
    "frontend": 8,
    "backend": 9,
    "tests": 20,
    "docs": 21,
    "other": 22,
}


def _slice_order_key(slice_id: str) -> int:
    if slice_id.startswith("route:"):
        return SLICE_ORDER["route:"]
    return SLICE_ORDER.get(slice_id, 19)


def _slice_followups(row: dict[str, object], broad_limited: bool) -> list[dict[str, str]]:
    slice_id = str(row.get("id", "") or "")
    files = row.get("files", []) if isinstance(row.get("files", []), list) else []
    first_file = str(files[0]) if files else ""
    routes = row.get("routes", []) if isinstance(row.get("routes", []), list) else []
    first_route = str(routes[0]) if routes else ""
    fields = row.get("fields", []) if isinstance(row.get("fields", []), list) else []
    followups: list[dict[str, str]] = []

    def add(tool: str, target: str, why: str) -> None:
        item = {"tool": tool, "target": target, "why": why}
        if item not in followups:
            followups.append(item)

    if first_route:
        add("api_impact", first_route, "Check route consumers, field reads, shape status, and route blast radius for this slice.")
        add("shape_check", first_route, "Verify response fields still satisfy frontend/API consumers.")
        for field in fields[:2]:
            add("field_impact", f"{first_route} {field}", "Inspect which consumers read this response field and whether the backend still returns it.")
    if first_file:
        add("get_source_context", first_file, "Inspect the highest-risk changed file in this slice.")
    if slice_id in {"indexing-parsers", "indexing-graph", "graph-storage"}:
        add("find_tests_for_target", first_file or slice_id, "Find focused parser/graph/storage tests for this slice.")
    elif slice_id in {"code-intelligence-services", "support-services", "mcp-runtime"}:
        add("impact_analysis", first_file or slice_id, "Trace downstream tool behavior affected by this implementation slice.")
    if broad_limited and first_file:
        add("change_impact_report", first_file, "Run a narrower follow-up if whole-tree graph/process traversal was capped.")
    return followups[:6]


def _field_blast_radius(row: dict[str, object]) -> list[dict[str, object]]:
    routes = row.get("routes", []) if isinstance(row.get("routes", []), list) else []
    fields = row.get("fields", []) if isinstance(row.get("fields", []), list) else []
    consumers = row.get("consumers", []) if isinstance(row.get("consumers", []), list) else []
    if not routes or not fields:
        return []
    first_route = str(routes[0])
    return [
        {
            "route": first_route,
            "field": str(field),
            "consumer_count": len(consumers),
            "consumers": consumers[:6],
            "follow_up": {
                "tool": "field_impact",
                "target": f"{first_route} {field}",
                "why": "Show exact field readers and missing-response risk for this route field.",
            },
        }
        for field in fields[:8]
    ]


def _process_blast_radius(process_rows: list[object]) -> list[dict[str, object]]:
    blast_radius: list[dict[str, object]] = []
    for process in process_rows:
        if not isinstance(process, dict):
            continue
        step_details = process.get("step_details", []) if isinstance(process.get("step_details", []), list) else []
        files = _unique([step.get("file", "") for step in step_details if isinstance(step, dict)], limit=8)
        changed_steps = [
            {
                "symbol": step.get("symbol", ""),
                "file": step.get("file", ""),
                "step": step.get("step", 0),
            }
            for step in step_details
            if isinstance(step, dict) and bool(step.get("changed"))
        ]
        blast_radius.append(
            {
                "name": str(process.get("name", "") or ""),
                "risk": str(process.get("risk", "LOW") or "LOW"),
                "steps": int(process.get("steps", 0) or 0),
                "entry_symbol": str(process.get("entry_symbol", "") or ""),
                "changed_symbol": str(process.get("changed_symbol", "") or ""),
                "changed_symbols": process.get("changed_symbols", []) if isinstance(process.get("changed_symbols", []), list) else [],
                "changed_steps": changed_steps[:6],
                "files": files,
                "risk_reasons": process.get("risk_reasons", []) if isinstance(process.get("risk_reasons", []), list) else [],
            }
        )
    return blast_radius[:8]


def _commit_title_for_slice(row: dict[str, object]) -> str:
    slice_id = str(row.get("id", "") or "")
    title = str(row.get("title", "") or slice_id)
    if slice_id.startswith("route:"):
        routes = row.get("routes", []) if isinstance(row.get("routes", []), list) else []
        route = str(routes[0]) if routes else slice_id.removeprefix("route:")
        return f"Update API contract for {route}"
    verbs = {
        "indexing-parsers": "Improve parser extraction",
        "indexing-graph": "Improve graph construction",
        "graph-storage": "Update graph storage support",
        "code-intelligence-services": "Update code intelligence services",
        "mcp-runtime": "Harden MCP runtime behavior",
        "support-services": "Update support intelligence services",
        "frontend": "Update frontend behavior",
        "backend-core": "Update backend data logic",
        "backend": "Update backend behavior",
        "tests": "Update test coverage",
        "docs": "Update documentation",
    }
    return verbs.get(slice_id, f"Update {title.lower()}")


def _commit_plan_for_slices(slices: list[dict[str, object]]) -> list[dict[str, object]]:
    plan = []
    for index, row in enumerate(slices, start=1):
        files = row.get("files", []) if isinstance(row.get("files", []), list) else []
        plan.append(
            {
                "step": index,
                "slice_id": row.get("id", ""),
                "title": _commit_title_for_slice(row),
                "risk": row.get("risk", "LOW"),
                "files": files,
                "test_before_commit": row.get("what_to_test", []) if isinstance(row.get("what_to_test", []), list) else [],
                "why_separate": row.get("what_can_break", [])[:3] if isinstance(row.get("what_can_break", []), list) else [],
            }
        )
    return plan


def _slice_validation(row: dict[str, object], broad_limited: bool) -> dict[str, object]:
    slice_id = str(row.get("id", "") or "unknown")
    risk = str(row.get("risk", "LOW") or "LOW")
    tests = row.get("tests", []) if isinstance(row.get("tests", []), list) else []
    breakage = row.get("what_can_break", []) if isinstance(row.get("what_can_break", []), list) else []
    followups = row.get("follow_up_tools", []) if isinstance(row.get("follow_up_tools", []), list) else []
    routes = row.get("routes", []) if isinstance(row.get("routes", []), list) else []
    consumers = row.get("consumers", []) if isinstance(row.get("consumers", []), list) else []
    fields = row.get("fields", []) if isinstance(row.get("fields", []), list) else []
    processes = row.get("processes", []) if isinstance(row.get("processes", []), list) else []
    blockers: list[str] = []
    required_actions: list[str] = []
    evidence: list[str] = []
    validation_plan: list[str] = []
    if tests:
        evidence.append(f"{len(tests)} focused test candidate(s) identified.")
    if routes:
        evidence.append(f"{len(routes)} route contract(s) tied to this slice.")
        validation_plan.append("Run api_impact and shape_check for affected route contracts.")
        if consumers or fields:
            evidence.append(f"{len(consumers)} consumer file(s) and {len(fields)} field read(s) tied to this slice.")
            if routes and fields:
                validation_plan.append("Run field_impact for high-value or missing response fields.")
    if processes:
        evidence.append(f"{len(processes)} execution flow(s) tied to this slice.")
        validation_plan.append("Run trace_processes for the changed route/service entrypoint.")
    if any("Missing response fields" in str(item) for item in breakage):
        blockers.append("Resolve or explicitly accept response-shape mismatches for this slice.")
    if broad_limited and risk in {"HIGH", "CRITICAL"}:
        required_actions.append("Run the focused follow-up tools for this slice because whole-tree traversal was capped.")
    if risk in {"HIGH", "CRITICAL"} and not tests:
        required_actions.append("Add or identify focused tests for this high-risk slice.")
    if risk == "MEDIUM" and not tests:
        required_actions.append("Run at least one focused test or context check before committing this slice.")
    if not validation_plan and followups:
        validation_plan.extend(str(item.get("tool", "")) + ": " + str(item.get("target", "")) for item in followups if isinstance(item, dict))
    status = "ready" if not blockers and not required_actions else "needs_validation" if not blockers else "blocked"
    residual_risk = risk
    if status == "ready" and risk == "HIGH":
        residual_risk = "MEDIUM"
    elif status == "ready" and risk == "MEDIUM":
        residual_risk = "LOW"
    return {
        "status": status,
        "ready_to_commit": status == "ready",
        "blockers": _unique(blockers, limit=4),
        "required_actions": _unique(required_actions, limit=6),
        "evidence": _unique(evidence, limit=6),
        "validation_plan": _unique(validation_plan, limit=6),
        "risk": risk,
        "residual_risk_after_validation": residual_risk,
        "slice_id": slice_id,
    }


def _pre_commit_readiness(changes: dict[str, object], workflow: dict[str, object]) -> dict[str, object]:
    warnings = changes.get("warnings", []) if isinstance(changes.get("warnings", []), list) else []
    risk = str(changes.get("risk", "LOW") or "LOW")
    shape_mismatches = changes.get("shape_mismatches", []) if isinstance(changes.get("shape_mismatches", []), list) else []
    slices = workflow.get("recommended_commit_slices", []) if isinstance(workflow.get("recommended_commit_slices", []), list) else []
    blockers: list[str] = []
    required_actions: list[str] = []
    broad_limited = any("skipped" in str(warning).lower() or "capped" in str(warning).lower() for warning in warnings)
    if broad_limited:
        blockers.append("Whole-tree graph/process traversal was capped; run focused follow-up tools for high-risk slices.")
    if shape_mismatches:
        blockers.append(f"{len(shape_mismatches)} response-shape mismatch(es) must be resolved or accepted.")
    if risk == "CRITICAL":
        blockers.append("Whole working tree risk is CRITICAL; split or validate slices before committing.")
    high_risk_slices = [row for row in slices if isinstance(row, dict) and row.get("risk") in {"HIGH", "CRITICAL"}]
    unvalidated_high_risk_slices = [
        row
        for row in high_risk_slices
        if not (
            isinstance(row.get("validation"), dict)
            and row.get("validation", {}).get("status") == "ready"
        )
    ]
    if unvalidated_high_risk_slices:
        required_actions.append(f"Validate {len(unvalidated_high_risk_slices)} high-risk slice(s) before commit.")
    blocked_slices = [
        row
        for row in slices
        if isinstance(row, dict)
        and isinstance(row.get("validation"), dict)
        and row.get("validation", {}).get("status") == "blocked"
    ]
    if blocked_slices:
        blockers.append(f"{len(blocked_slices)} commit slice(s) are blocked.")
    needs_validation_slices = [
        row
        for row in slices
        if isinstance(row, dict)
        and isinstance(row.get("validation"), dict)
        and row.get("validation", {}).get("status") == "needs_validation"
    ]
    if needs_validation_slices:
        required_actions.append(f"Complete focused validation for {len(needs_validation_slices)} slice(s).")
    for row in slices:
        if not isinstance(row, dict):
            continue
        tests = row.get("what_to_test", []) if isinstance(row.get("what_to_test", []), list) else []
        if row.get("risk") in {"HIGH", "CRITICAL"} and not tests:
            required_actions.append(f"Add or identify tests for {row.get('id', 'unknown slice')}.")
    residual_risks = [
        str(row.get("validation", {}).get("residual_risk_after_validation", row.get("risk", "LOW")) if isinstance(row.get("validation"), dict) else row.get("risk", "LOW"))
        for row in slices
        if isinstance(row, dict)
    ]
    risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    risk_after_validation = max(residual_risks or [risk], key=lambda item: risk_order.get(str(item), 0))
    status = "ready" if not blockers and not required_actions else "needs_validation" if not blockers else "not_ready"
    return {
        "status": status,
        "ready_to_commit": status == "ready",
        "blockers": _unique(blockers, limit=8),
        "required_actions": _unique(required_actions, limit=8),
        "highest_risk": risk,
        "risk_after_validation": risk_after_validation,
        "risk_calibration": {
            "basis": "slice validation evidence and residual risk after focused test/API/process checks",
            "improved_by_validation": risk_order.get(risk_after_validation, 0) < risk_order.get(risk, 0),
        },
        "validation_plan": _unique(
            [
                item
                for row in slices
                if isinstance(row, dict) and isinstance(row.get("validation"), dict)
                for item in row.get("validation", {}).get("validation_plan", [])
            ],
            limit=10,
        ),
        "slice_validation": {
            "ready": sum(
                1
                for row in slices
                if isinstance(row, dict)
                and isinstance(row.get("validation"), dict)
                and row.get("validation", {}).get("status") == "ready"
            ),
            "needs_validation": len(needs_validation_slices),
            "blocked": len(blocked_slices),
        },
        "residual_risk_by_slice": [
            {
                "slice_id": row.get("id", ""),
                "risk": row.get("risk", "LOW"),
                "residual_risk_after_validation": row.get("validation", {}).get("residual_risk_after_validation", row.get("risk", "LOW")) if isinstance(row.get("validation"), dict) else row.get("risk", "LOW"),
            }
            for row in slices
            if isinstance(row, dict)
        ],
    }


def _build_pre_commit_workflow(changes: dict[str, object], tests: dict[str, object]) -> dict[str, object]:
    changed_files = [str(path) for path in changes.get("changed_files", []) if str(path)] if isinstance(changes.get("changed_files", []), list) else []
    risk_by_file = changes.get("risk_by_file", []) if isinstance(changes.get("risk_by_file", []), list) else []
    risk_by_path = {str(row.get("file", "")): row for row in risk_by_file if isinstance(row, dict)}
    changed_routes = changes.get("changed_routes", []) if isinstance(changes.get("changed_routes", []), list) else []
    affected_consumers = changes.get("affected_consumers", []) if isinstance(changes.get("affected_consumers", []), list) else []
    affected_processes = changes.get("affected_processes", []) if isinstance(changes.get("affected_processes", []), list) else []
    risk_by_route = changes.get("risk_by_route", []) if isinstance(changes.get("risk_by_route", []), list) else []
    shape_mismatches = changes.get("shape_mismatches", []) if isinstance(changes.get("shape_mismatches", []), list) else []
    recommended_tests = tests.get("recommended_tests", []) if isinstance(tests, dict) and isinstance(tests.get("recommended_tests", []), list) else []
    test_files = _unique([item.get("file", "") for item in recommended_tests if isinstance(item, dict)], limit=20)
    warnings = changes.get("warnings", []) if isinstance(changes.get("warnings", []), list) else []
    broad_limited = any("skipped" in str(warning).lower() or "capped" in str(warning).lower() for warning in warnings)

    grouped: dict[str, dict[str, object]] = {}
    for file_path in changed_files:
        key, title = _slice_key_for_file(file_path, changed_routes, affected_consumers)
        row = grouped.setdefault(
            key,
            {
                "id": key,
                "title": title,
                "files": [],
                "routes": [],
                "consumers": [],
                "fields": [],
                "processes": [],
                "process_blast_radius": [],
                "tests": [],
                "risk": "LOW",
                "why_risky": [],
                "what_can_break": [],
                "what_to_test": [],
            },
        )
        row["files"].append(file_path)
        file_risk = str(risk_by_path.get(file_path, {}).get("risk", "LOW"))
        if file_risk in {"CRITICAL", "HIGH"}:
            row["risk"] = file_risk
        elif file_risk == "MEDIUM" and row.get("risk") == "LOW":
            row["risk"] = "MEDIUM"
        for factor in risk_by_path.get(file_path, {}).get("risk_factors", []) if isinstance(risk_by_path.get(file_path, {}).get("risk_factors", []), list) else []:
            row["why_risky"].append(str(factor))

    if not grouped and not changed_files:
        return {
            "summary": "No changed files detected; no pre-commit slices needed.",
            "recommended_commit_slices": [],
            "recommended_order": [],
            "what_can_break": [],
            "what_to_test": [],
        }

    for route in risk_by_route:
        if not isinstance(route, dict):
            continue
        route_name = str(route.get("route", "") or "")
        key = f"route:{route_name}" if route_name else "backend"
        row = grouped.get(key) or grouped.setdefault(key, {"id": key, "title": f"API contract: {route_name.strip('/')}", "files": [], "routes": [], "consumers": [], "fields": [], "processes": [], "process_blast_radius": [], "tests": [], "risk": "LOW", "why_risky": [], "what_can_break": [], "what_to_test": []})
        row["routes"].append(route_name)
        row["why_risky"].append(f"Route {route_name} risk is {route.get('risk', 'UNKNOWN')}")
        if route.get("risk") in {"HIGH", "CRITICAL"}:
            row["risk"] = str(route.get("risk"))
        elif route.get("risk") == "MEDIUM" and row.get("risk") == "LOW":
            row["risk"] = "MEDIUM"

    for consumer in affected_consumers:
        if not isinstance(consumer, dict):
            continue
        route = str(consumer.get("route", "") or "")
        key = f"route:{route}" if route else _slice_key_for_file(str(consumer.get("file", "")), changed_routes, affected_consumers)[0]
        row = grouped.get(key) or grouped.setdefault(key, {"id": key, "title": f"API contract: {route.strip('/')}", "files": [], "routes": [], "consumers": [], "fields": [], "processes": [], "process_blast_radius": [], "tests": [], "risk": "LOW", "why_risky": [], "what_can_break": [], "what_to_test": []})
        file_path = str(consumer.get("file", "") or "")
        if file_path:
            row["consumers"].append(file_path)
        for field in consumer.get("field_reads", []) if isinstance(consumer.get("field_reads", []), list) else []:
            row["fields"].append(str(field))
        if route:
            row["routes"].append(route)
            row["what_can_break"].append(f"{route} response consumers in {file_path or 'frontend/API clients'}")

    for process in affected_processes:
        if not isinstance(process, dict):
            continue
        route_context = process.get("changed_routes", []) if isinstance(process.get("changed_routes", []), list) else []
        key = f"route:{route_context[0]}" if route_context else "backend-core"
        row = grouped.get(key) or grouped.setdefault(key, {"id": key, "title": "Backend data/service logic", "files": [], "routes": [], "consumers": [], "fields": [], "processes": [], "process_blast_radius": [], "tests": [], "risk": "LOW", "why_risky": [], "what_can_break": [], "what_to_test": []})
        row["processes"].append(str(process.get("name", "") or ""))
        row["process_blast_radius"].extend(_process_blast_radius([process]))
        row["why_risky"].extend(str(reason) for reason in process.get("risk_reasons", []) if reason)
        if process.get("risk") in {"HIGH", "CRITICAL"}:
            row["risk"] = str(process.get("risk"))
        elif process.get("risk") == "MEDIUM" and row.get("risk") == "LOW":
            row["risk"] = "MEDIUM"
        if process.get("name"):
            row["what_can_break"].append(f"Execution flow: {process.get('name')}")

    for mismatch in shape_mismatches:
        if not isinstance(mismatch, dict):
            continue
        route = str(mismatch.get("route", "") or "")
        key = f"route:{route}" if route else "backend"
        row = grouped.get(key)
        if row is None:
            continue
        row["risk"] = "HIGH" if row.get("risk") != "CRITICAL" else row["risk"]
        fields = [*mismatch.get("missing_fields", []), *mismatch.get("nested_missing_fields", [])]
        row["what_can_break"].append(f"Missing response fields: {', '.join(str(field) for field in fields if field) or 'unknown'}")

    for row in grouped.values():
        slice_id = str(row.get("id", "") or "")
        if slice_id in SLICE_BREAKAGE_HINTS:
            row["what_can_break"].append(SLICE_BREAKAGE_HINTS[slice_id])
        title_tokens = set(str(row.get("title", "")).lower().replace("/", " ").replace("-", " ").split())
        files = [str(path) for path in row.get("files", []) if str(path)]
        matched_tests = [
            test_file
            for test_file in test_files
            if title_tokens & set(test_file.lower().replace("/", " ").replace("_", " ").replace("-", " ").split())
            or any(Path(file_path).stem.lower() in test_file.lower() for file_path in files)
        ]
        row["tests"] = matched_tests[:8] or test_files[:5]
        if row["tests"]:
            row["what_to_test"].append("Run: " + ", ".join(row["tests"][:5]))
        elif row.get("risk") in {"HIGH", "CRITICAL", "MEDIUM"}:
            row["what_to_test"].append("Add or run focused integration coverage for this slice.")
        row["files"] = _unique(row.get("files", []), limit=20)
        row["routes"] = _unique(row.get("routes", []), limit=8)
        row["consumers"] = _unique(row.get("consumers", []), limit=8)
        row["fields"] = _unique(row.get("fields", []), limit=12)
        row["processes"] = _unique(row.get("processes", []), limit=8)
        row["process_blast_radius"] = row.get("process_blast_radius", [])[:8] if isinstance(row.get("process_blast_radius", []), list) else []
        row["why_risky"] = _unique(row.get("why_risky", []), limit=8)
        row["what_can_break"] = _unique(row.get("what_can_break", []), limit=8)
        row["what_to_test"] = _unique(row.get("what_to_test", []), limit=6)
        row["field_blast_radius"] = _field_blast_radius(row)
        row["follow_up_tools"] = _slice_followups(row, broad_limited=broad_limited)
        row["validation"] = _slice_validation(row, broad_limited=broad_limited)

    risk_order = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
    slices = sorted(
        grouped.values(),
        key=lambda row: (
            _slice_order_key(str(row.get("id", "") or "")),
            -risk_order.get(str(row.get("risk", "LOW")), 0),
            -len(row.get("files", [])),
        ),
    )
    commit_plan = _commit_plan_for_slices(slices)
    workflow = {
        "summary": f"{len(changed_files)} changed files grouped into {len(slices)} recommended commit slice(s).",
        "recommended_commit_slices": slices,
        "recommended_order": [str(row.get("id", "")) for row in slices],
        "commit_plan": commit_plan,
        "validation_summary": {
            "ready": sum(1 for row in slices if isinstance(row.get("validation"), dict) and row.get("validation", {}).get("status") == "ready"),
            "needs_validation": sum(1 for row in slices if isinstance(row.get("validation"), dict) and row.get("validation", {}).get("status") == "needs_validation"),
            "blocked": sum(1 for row in slices if isinstance(row.get("validation"), dict) and row.get("validation", {}).get("status") == "blocked"),
        },
        "validation_plan": _unique(
            [
                item
                for row in slices
                if isinstance(row, dict) and isinstance(row.get("validation"), dict)
                for item in row.get("validation", {}).get("validation_plan", [])
            ],
            limit=12,
        ),
        "what_can_break": _unique([item for row in slices for item in row.get("what_can_break", [])], limit=12),
        "what_to_test": _unique([item for row in slices for item in row.get("what_to_test", [])], limit=12),
        "follow_up_tools": _unique_dicts([item for row in slices for item in row.get("follow_up_tools", [])], limit=12),
        "field_blast_radius": [
            item
            for row in slices
            if isinstance(row, dict) and isinstance(row.get("field_blast_radius", []), list)
            for item in row.get("field_blast_radius", [])
        ][:12],
        "process_blast_radius": [
            item
            for row in slices
            if isinstance(row, dict) and isinstance(row.get("process_blast_radius", []), list)
            for item in row.get("process_blast_radius", [])
        ][:12],
    }
    workflow["readiness"] = _pre_commit_readiness(changes, workflow)
    return workflow


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
