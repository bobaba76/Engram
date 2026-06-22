"""Guidance — architecture summary, guidance profile, answer synthesis, behavior trace summaries."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from services.investigation_ranking import (
    _architecture_summary,
    _exploratory_file_groups,
    _is_exploratory_intent,
    _is_frontend_file,
    _unique_strings,
)
from services.test_intelligence_service import find_tests_for_target

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore


logger = logging.getLogger(__name__)


def _guidance_profile(
    resolution: dict[str, object],
    diagnostics: dict[str, object],
    seed_hits: list[dict[str, object]],
    expanded_hits: list[dict[str, object]],
    snippets: list[dict[str, object]],
    ranked_files: list[dict[str, object]],
    architecture: dict[str, object],
    intent: dict[str, object],
    graph_signal: dict[str, object],
) -> dict[str, object]:
    resolution_summary = resolution.get("compact_summary", {}) if isinstance(resolution, dict) else {}
    ambiguous = str(resolution.get("status", "") or "") == "ambiguous"
    weak_primary = not seed_hits and bool(expanded_hits)
    evidence_count = len(seed_hits) + len(expanded_hits) + len(snippets)
    caller_count = int(architecture.get("caller_count", 0) or 0)
    callee_count = int(architecture.get("callee_count", 0) or 0)
    route_count = len(architecture.get("top_routes", []) if isinstance(architecture.get("top_routes", []), list) else [])
    process_count = len(architecture.get("top_processes", []) if isinstance(architecture.get("top_processes", []), list) else [])
    top_file = ranked_files[0] if ranked_files else {}
    profile = {
        "ambiguous": ambiguous,
        "weak_primary": weak_primary,
        "evidence_count": evidence_count,
        "has_source_snippets": bool(snippets),
        "has_ranked_files": bool(ranked_files),
        "has_graph_context": bool(caller_count or callee_count),
        "has_routes": route_count > 0,
        "has_processes": process_count > 0,
        "has_indirect_frontend_path": bool(graph_signal.get("has_indirect_frontend_path")),
        "frontend_graph_hit_count": int(graph_signal.get("frontend_graph_hit_count", 0) or 0),
        "frontend_graph_files": graph_signal.get("frontend_graph_files", []),
        "top_file": top_file,
        "intent": intent,
        "resolution_warnings": resolution_summary.get("warnings", []) if isinstance(resolution_summary, dict) else [],
        "retrieval_signal_strength": {
            "vector": int(diagnostics.get("vector_candidates", 0) or 0),
            "regex": int(diagnostics.get("regex_candidates", 0) or 0),
            "expanded_regex": int(diagnostics.get("expanded_regex_candidates", 0) or 0),
            "window": int(diagnostics.get("window_candidates", 0) or 0),
        },
    }
    return profile


def _guidance_next_steps(profile: dict[str, object], resolved_target: str, question: str) -> list[str]:
    steps: list[str] = []
    intent = profile.get("intent", {}) if isinstance(profile.get("intent", {}), dict) else {}
    primary_intent = str(intent.get("primary", "general") or "general")
    if bool(profile.get("ambiguous")):
        steps.append("Narrow the target before editing by passing a file path, kind, or symbol UID.")
    if bool(profile.get("weak_primary")):
        steps.append("Start from the top ranked file and validate the exact symbol because current search is driven mostly by expanded context.")
        if bool(profile.get("has_indirect_frontend_path")):
            steps.append("Use graph-backed frontend evidence to trace the TypeScript/TSX implementation path when lexical hits are weak.")
    elif bool(profile.get("has_source_snippets")):
        steps.append("Open the top source snippets first to confirm the primary implementation path.")
    else:
        steps.append("Open the top ranked file before editing because no direct source snippet was available.")

    if primary_intent == "location":
        steps.append("Confirm the owning file and symbol before following secondary references.")
    elif primary_intent == "flow":
        steps.append("Trace callers, callees, or processes to verify the end-to-end execution path.")
    elif primary_intent == "impact":
        steps.append("Check impact and dependent callers before editing because the question is change-oriented.")
    elif primary_intent == "tests":
        steps.append("Find the closest tests before changing behavior so you can validate quickly.")
    elif primary_intent == "api":
        steps.append("Validate handler, route consumers, and response flow before making API changes.")
    elif primary_intent == "bug":
        steps.append("Verify the failing path in source first, then inspect the surrounding flow for root cause.")

    if bool(profile.get("has_graph_context")):
        steps.append("Use impact_analysis on the resolved target before changing shared behavior.")
    if bool(profile.get("has_routes")):
        steps.append("Check related routes and API consumers to confirm request flow.")
    if bool(profile.get("has_processes")):
        steps.append("Review related processes to understand end-to-end execution flow.")
    if bool(profile.get("has_indirect_frontend_path")) and not bool(profile.get("has_source_snippets")):
        steps.append("Treat frontend graph hits as implementation clues and verify the linked TS/TSX files before editing.")
    if not bool(profile.get("has_ranked_files")):
        steps.append(f"Retry the investigation with a more specific question than '{question}'.")

    unique: list[str] = []
    for step in steps:
        if step not in unique:
            unique.append(step)
    return unique[:6]


def _guidance_next_tools(profile: dict[str, object], resolved_target: str, question: str) -> list[dict[str, object]]:
    tools: list[dict[str, object]] = []
    intent = profile.get("intent", {}) if isinstance(profile.get("intent", {}), dict) else {}
    primary_intent = str(intent.get("primary", "general") or "general")

    def add_tool(name: str, target: str, why: str) -> None:
        candidate = {"tool": name, "target": target, "why": why}
        if any(existing.get("tool") == name and existing.get("target") == target for existing in tools):
            return
        if candidate not in tools:
            tools.append(candidate)

    add_tool("get_source_context", resolved_target, "Read exact source snippets for the best current target.")
    if bool(profile.get("ambiguous")):
        add_tool("resolve_target", resolved_target, "Disambiguate the target before making changes.")
    if bool(profile.get("has_graph_context")):
        add_tool("impact_analysis", resolved_target, "Check callers and dependents before changing behavior.")
        add_tool("unified_context", resolved_target, "Inspect callers, callees, and graph neighbors together.")
    if bool(profile.get("has_routes")) or bool(profile.get("has_processes")):
        add_tool("app_context", question, "Inspect app-level files, routes, and related processes.")
    if bool(profile.get("weak_primary")):
        add_tool("semantic_code_search", question, "Retry search with a narrower or more explicit query to get a stronger primary hit.")
    if primary_intent == "flow":
        add_tool("unified_context", resolved_target, "Follow callers, callees, and local graph flow for execution questions.")
    if primary_intent == "impact":
        add_tool("impact_analysis", resolved_target, "Estimate what breaks or changes if you modify this target.")
    if primary_intent == "tests":
        add_tool("find_tests_for_target", resolved_target, "Find the most relevant tests for this target first.")
    if primary_intent == "api":
        add_tool("app_context", question, "Inspect route handlers, consumers, and related app context.")
    if primary_intent == "location":
        add_tool("get_source_context", resolved_target, "Open the most likely implementation site directly.")
    add_tool("find_tests_for_target", resolved_target, "Find focused tests for the resolved area.")
    return tools[:6]


def _guidance_summary(profile: dict[str, object]) -> dict[str, object]:
    top_file = profile.get("top_file", {}) if isinstance(profile.get("top_file", {}), dict) else {}
    retrieval_signal_strength = profile.get("retrieval_signal_strength", {}) if isinstance(profile.get("retrieval_signal_strength", {}), dict) else {}
    intent = profile.get("intent", {}) if isinstance(profile.get("intent", {}), dict) else {}
    return {
        "ambiguous": bool(profile.get("ambiguous")),
        "weak_primary": bool(profile.get("weak_primary")),
        "evidence_count": int(profile.get("evidence_count", 0) or 0),
        "has_graph_context": bool(profile.get("has_graph_context")),
        "has_routes": bool(profile.get("has_routes")),
        "has_processes": bool(profile.get("has_processes")),
        "intent": intent,
        "top_file": str(top_file.get("file", "") or ""),
        "top_file_reasons": top_file.get("reasons", [])[:3] if isinstance(top_file, dict) else [],
        "retrieval_signal_strength": retrieval_signal_strength,
    }


def _change_guidance(
    duckdb_store: DuckDBStore,
    resolved_target: str,
    ranked_files: list[dict[str, object]],
    unified_summary: dict[str, object],
    app_summary: dict[str, object],
) -> dict[str, object]:
    try:
        test_payload = find_tests_for_target(duckdb_store, resolved_target, limit=4) if resolved_target else {"compact_results": [], "compact_summary": {}}
    except Exception:
        logger.warning("investigation: find_tests_for_target failed for %s", resolved_target, exc_info=True)
        test_payload = {"compact_results": [], "compact_summary": {}}
    test_results = test_payload.get("compact_results", []) if isinstance(test_payload, dict) else []
    app_files = app_summary.get("top_files", []) if isinstance(app_summary, dict) else []
    related_files = _unique_strings(
        [item.get("file", "") for item in ranked_files[:5] if isinstance(item, dict)] + list(app_files[:5] if isinstance(app_files, list) else []),
        limit=6,
    )
    top_neighbors = unified_summary.get("top_neighbors", []) if isinstance(unified_summary, dict) else []
    likely_impact_targets = _unique_strings(
        [item.get("node", "") for item in top_neighbors if isinstance(item, dict)],
        limit=5,
    )
    return {
        "related_files": related_files,
        "recommended_tests": [item for item in test_results[:4] if isinstance(item, dict)],
        "likely_impact_targets": likely_impact_targets,
        "test_count": len(test_results) if isinstance(test_results, list) else 0,
    }

def _merge_behavior_trace_summaries(summaries: list[dict[str, object]], limit: int = 6) -> dict[str, object]:
    top_files: list[str] = []
    top_routes: list[str] = []
    top_processes: list[str] = []
    attempted_features: list[str] = []
    file_kinds: dict[str, int] = {}
    role_groups = {"page_files": [], "shared_ui_files": [], "backend_files": []}
    partial = False

    def add_unique(values: object, target: list[str]) -> None:
        if not isinstance(values, list):
            return
        for value in values:
            normalized = str(value or "").strip()
            if normalized and normalized not in target:
                target.append(normalized)
            if len(target) >= limit:
                break

    for item in summaries:
        if not isinstance(item, dict):
            continue
        add_unique(item.get("top_files", []), top_files)
        add_unique(item.get("top_routes", []), top_routes)
        add_unique(item.get("top_processes", []), top_processes)
        feature_name = str(item.get("feature", "") or "").strip()
        if feature_name and feature_name not in attempted_features:
            attempted_features.append(feature_name)
        kinds = item.get("file_kinds", {})
        if isinstance(kinds, dict):
            for kind, count in kinds.items():
                normalized_kind = str(kind or "").strip()
                if not normalized_kind:
                    continue
                file_kinds[normalized_kind] = file_kinds.get(normalized_kind, 0) + int(count or 0)
        summary_roles = item.get("role_groups", {})
        if isinstance(summary_roles, dict):
            for role_name, values in summary_roles.items():
                if role_name not in role_groups:
                    continue
                add_unique(values, role_groups[role_name])
        partial = partial or bool(item.get("partial"))

    return {
        "feature": attempted_features[0] if attempted_features else "",
        "attempted_features": attempted_features[:limit],
        "top_files": top_files[:limit],
        "top_routes": top_routes[:limit],
        "top_processes": top_processes[:limit],
        "file_kinds": file_kinds,
        "role_groups": role_groups,
        "partial": partial,
        "file_count": len(top_files[:limit]),
    }


def _behavior_trace_summary(feature_payload: dict[str, object]) -> dict[str, object]:
    compact = feature_payload.get("compact_summary", {}) if isinstance(feature_payload, dict) else {}
    files = compact.get("top_files", []) if isinstance(compact, dict) else []
    routes = compact.get("top_routes", []) if isinstance(compact, dict) else []
    processes = compact.get("top_processes", []) if isinstance(compact, dict) else []
    file_kinds = compact.get("file_kinds", {}) if isinstance(compact, dict) else {}
    role_groups = compact.get("role_groups", {}) if isinstance(compact, dict) else {}
    return {
        "feature": str(feature_payload.get("feature", "") or ""),
        "top_files": files[:6] if isinstance(files, list) else [],
        "top_routes": routes[:6] if isinstance(routes, list) else [],
        "top_processes": processes[:6] if isinstance(processes, list) else [],
        "file_kinds": file_kinds if isinstance(file_kinds, dict) else {},
        "role_groups": role_groups if isinstance(role_groups, dict) else {},
        "attempted_features": [str(feature_payload.get("feature", "") or "")] if str(feature_payload.get("feature", "") or "").strip() else [],
        "partial": bool(feature_payload.get("partial")) or bool(compact.get("partial")),
        "file_count": int(compact.get("file_count", 0) or 0) if isinstance(compact, dict) else 0,
    }

def _synthesize_answer(
    question: str,
    resolved_target: str,
    ranked_files: list[dict[str, object]],
    evidence: list[dict[str, object]],
    diagnostics: dict[str, object],
    architecture: dict[str, object],
    seed_hits: list[dict[str, object]],
    expanded_hits: list[dict[str, object]],
    intent: dict[str, object],
    graph_signal: dict[str, object],
    exploratory_groups: dict[str, list[str]] | None = None,
) -> tuple[str, str, list[str]]:
    key_files = [str(item.get("file", "")) for item in ranked_files if str(item.get("file", "")).strip()]
    caller_count = int(architecture.get("caller_count", 0) or 0)
    callee_count = int(architecture.get("callee_count", 0) or 0)
    routes = architecture.get("top_routes", []) if isinstance(architecture.get("top_routes", []), list) else []
    confidence = "medium" if evidence else "low"
    if key_files and seed_hits and (caller_count or callee_count or routes):
        confidence = "high"
    open_questions = []
    if not key_files:
        open_questions.append("No strong file candidate was found; try a more specific symbol or path.")
    if not evidence:
        open_questions.append("No supporting evidence was collected.")
    if not seed_hits and expanded_hits:
        open_questions.append("Results are mostly expanded context; try a more exact symbol or route for a stronger primary hit.")
    if bool(graph_signal.get("has_indirect_frontend_path")) and not seed_hits:
        open_questions.append("The best frontend evidence is graph-backed rather than lexical; confirm the linked TypeScript/TSX implementation path in source.")
    diagnostics_text = []
    for field in ("vector_candidates", "regex_candidates", "expanded_regex_candidates", "window_candidates"):
        value = diagnostics.get(field)
        if value:
            diagnostics_text.append(f"{field.replace('_', ' ')}={value}")
    primary_intent = str(intent.get("primary", "general") or "general")
    intent_text = {
        "location": " This investigation is focused on locating the owning implementation.",
        "flow": " This investigation is focused on execution flow and why the behavior happens.",
        "impact": " This investigation is focused on likely change impact.",
        "tests": " This investigation is focused on finding fast validation paths through tests.",
        "api": " This investigation is focused on API handlers and request/response flow.",
        "bug": " This investigation is focused on isolating the likely failing path.",
    }.get(primary_intent, "")
    route_text = f" Related routes: {', '.join(str(route) for route in routes[:3])}." if routes else ""
    graph_text = f" Graph context shows {caller_count} callers and {callee_count} callees." if caller_count or callee_count else ""
    file_text = f" The strongest files are {', '.join(key_files[:4])}." if key_files else ""
    evidence_text = f" Primary evidence came from {len(seed_hits)} seed hits and {len(expanded_hits)} expanded hits."
    indirect_frontend_text = ""
    if bool(graph_signal.get("has_indirect_frontend_path")):
        frontend_files = graph_signal.get("frontend_graph_files", []) if isinstance(graph_signal.get("frontend_graph_files", []), list) else []
        if frontend_files:
            indirect_frontend_text = f" Frontend implementation evidence is partly graph-backed via {', '.join(str(path) for path in frontend_files[:2])}."
        else:
            indirect_frontend_text = " Frontend implementation evidence is partly graph-backed through TypeScript/TSX relationships."
    diagnostics_suffix = f" Retrieval diagnostics: {', '.join(diagnostics_text[:4])}." if diagnostics_text else ""
    groups = exploratory_groups if isinstance(exploratory_groups, dict) else {}
    if _is_exploratory_intent(intent):
        page_text = groups.get("page_files", []) if isinstance(groups.get("page_files", []), list) else []
        shared_ui_text = groups.get("shared_ui_files", []) if isinstance(groups.get("shared_ui_files", []), list) else []
        backend_text = groups.get("backend_files", []) if isinstance(groups.get("backend_files", []), list) else []
        grouped_bits: list[str] = []
        if page_text:
            grouped_bits.append(f"Likely page files: {', '.join(page_text[:3])}.")
        if shared_ui_text:
            grouped_bits.append(f"Likely shared UI files: {', '.join(shared_ui_text[:3])}.")
        if backend_text:
            grouped_bits.append(f"Likely backend files: {', '.join(backend_text[:3])}.")
        if routes:
            grouped_bits.append(f"Likely endpoint routes: {', '.join(str(route) for route in routes[:3])}.")
        grouped_text = " ".join(grouped_bits) if grouped_bits else file_text
        answer = (
            f"For '{question}', this looks more like an exploratory feature trace than a single-symbol lookup."
            f"{intent_text} {grouped_text}{graph_text}{evidence_text}{indirect_frontend_text}{diagnostics_suffix}"
            " Use the grouped files to open the frontend owner, shared UI logic, and backend flow in that order."
        )
    else:
        answer = (
            f"For '{question}', the best current target is {resolved_target}."
            f"{intent_text}{file_text}{graph_text}{route_text}{evidence_text}{indirect_frontend_text}{diagnostics_suffix}"
            " Use the evidence list for exact files and line ranges."
        )
    return answer, confidence, open_questions
