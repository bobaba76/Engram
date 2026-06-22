"""Ranking — hit classification, file relevance, evidence items, frontend graph signal."""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.investigation_constants import (
    BEHAVIOR_OWNER_HINTS,
    GENERIC_EXPLORATORY_NOUNS,
    GENERIC_SEARCH_TERMS,
    STOPWORD_TOKENS,
)
from services.investigation_question_analysis import (
    _is_implausible_exploratory_file,
    _is_noise_reason,
    _is_page_owner_file,
    _is_shared_ui_file,
    _meaningful_prompt_overlap,
    _page_primary_prompt,
    _question_tokens,
)

if TYPE_CHECKING:
    pass


def _is_generic_target(target: str) -> bool:
    normalized = str(target or "").strip().lower()
    return normalized in {"main", "app", "index", "__init__"}


def _should_retry_investigation(seed_hits: list[dict[str, object]], expanded_hits: list[dict[str, object]], snippets_list: list[dict[str, object]]) -> bool:
    if not seed_hits and expanded_hits:
        return True
    if not seed_hits and not snippets_list:
        return True
    return False


def _investigation_strength(seed_hits: list[dict[str, object]], expanded_hits: list[dict[str, object]], snippets_list: list[dict[str, object]], resolved_target: str) -> tuple[int, int, int, int, str]:
    return (
        len(seed_hits),
        len(snippets_list),
        len(expanded_hits),
        len(resolved_target.strip()),
        resolved_target,
    )


def _compact_hits(search_payload: dict[str, object], limit: int = 5) -> list[dict[str, object]]:
    compact = search_payload.get("compact_results", [])
    return [item for item in compact[:limit] if isinstance(item, dict)] if isinstance(compact, list) else []


def _unique_strings(values: list[object], limit: int = 8) -> list[str]:
    unique: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in unique:
            unique.append(text)
        if len(unique) >= limit:
            break
    return unique

def _retrieval_diagnostics(search_payload: dict[str, object]) -> dict[str, object]:
    diagnostics = search_payload.get("retrieval_diagnostics", {})
    return diagnostics if isinstance(diagnostics, dict) else {}


def _is_expanded_hit(item: dict[str, object]) -> bool:
    sources = item.get("sources", [])
    if not isinstance(sources, list):
        sources = [sources]
    normalized = {str(source or "").strip().lower() for source in sources if str(source or "").strip()}
    return any(source in {"regex_expanded", "window", "graph"} for source in normalized)


def _normalized_sources(item: dict[str, object]) -> set[str]:
    sources = item.get("sources", [])
    if not isinstance(sources, list):
        sources = [sources]
    return {str(source or "").strip().lower() for source in sources if str(source or "").strip()}


def _is_frontend_file(file_path: str) -> bool:
    normalized = str(file_path or "").replace("\\", "/").lower()
    return normalized.endswith((".ts", ".tsx", ".js", ".jsx"))


def _is_frontend_graph_hit(item: dict[str, object]) -> bool:
    file_path = str(item.get("file") or item.get("file_path") or "").strip()
    return _is_frontend_file(file_path) and "graph" in _normalized_sources(item)


def _graph_frontend_signal(
    search_hits: list[dict[str, object]],
    ranked_files: list[dict[str, object]],
    architecture: dict[str, object],
) -> dict[str, object]:
    frontend_graph_hits = [item for item in search_hits if _is_frontend_graph_hit(item)]
    indirect_frontend_files = [
        str(item.get("file") or item.get("file_path") or "").strip()
        for item in frontend_graph_hits
        if str(item.get("file") or item.get("file_path") or "").strip()
    ]
    top_frontend_ranked = [
        str(item.get("file") or "").strip()
        for item in ranked_files
        if _is_frontend_file(str(item.get("file") or ""))
    ]
    file_kinds = architecture.get("file_kinds", {}) if isinstance(architecture.get("file_kinds", {}), dict) else {}
    frontend_file_count = int(file_kinds.get("frontend", 0) or 0) + int(file_kinds.get("frontend_component", 0) or 0)
    return {
        "frontend_graph_hit_count": len(frontend_graph_hits),
        "frontend_graph_files": indirect_frontend_files[:6],
        "top_frontend_ranked_files": top_frontend_ranked[:4],
        "frontend_file_count": frontend_file_count,
        "graph_edge_count": int(architecture.get("graph_edge_count", 0) or 0),
        "has_indirect_frontend_path": bool(frontend_graph_hits),
    }


def _classify_search_hits(search_hits: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    seed_hits: list[dict[str, object]] = []
    expanded_hits: list[dict[str, object]] = []
    for item in search_hits:
        if _is_expanded_hit(item):
            expanded_hits.append(item)
        else:
            seed_hits.append(item)
    return seed_hits, expanded_hits

def _target_affinity_score(item: dict[str, object], seed_target: str, resolved_target: str) -> tuple[int, int, int]:
    item_target = str(item.get("target") or item.get("qualified_name") or item.get("name") or "").strip()
    item_file = str(item.get("file") or item.get("file_path") or "").strip()
    normalized_target = item_target.lower()
    normalized_file = item_file.lower()
    normalized_seed = str(seed_target or "").strip().lower()
    normalized_resolved = str(resolved_target or "").strip().lower()

    exact_match = int(bool(normalized_resolved and normalized_target == normalized_resolved))
    seed_match = int(bool(normalized_seed and normalized_target == normalized_seed))
    partial_match = int(
        bool(
            normalized_resolved
            and (
                normalized_resolved in normalized_target
                or normalized_target in normalized_resolved
                or normalized_resolved in normalized_file
            )
        )
        or bool(
            normalized_seed
            and (
                normalized_seed in normalized_target
                or normalized_target in normalized_seed
                or normalized_seed in normalized_file
            )
        )
    )
    return exact_match, seed_match, partial_match


def _is_exploratory_intent(intent: dict[str, object]) -> bool:
    primary = str(intent.get("primary", "general") or "general")
    return primary in {"ui_ownership", "feature_exploration"}


def _prioritize_search_hits(search_hits: list[dict[str, object]], seed_target: str, resolved_target: str) -> list[dict[str, object]]:
    return sorted(
        search_hits,
        key=lambda item: (
            _target_affinity_score(item, seed_target, resolved_target),
            float(item.get("score", 0.0) or 0.0),
            int(bool(not _is_expanded_hit(item))),
        ),
        reverse=True,
    )

def _file_relevance(
    search_hits: list[dict[str, object]],
    snippets: list[dict[str, object]],
    app: dict[str, object],
    behavior_trace: dict[str, object] | None = None,
    question: str = "",
    intent: dict[str, object] | None = None,
    limit: int = 8,
) -> list[dict[str, object]]:
    file_map: dict[str, dict[str, object]] = {}

    def ensure_entry(file_path: str) -> dict[str, object]:
        entry = file_map.get(file_path)
        if entry is None:
            entry = {
                "file": file_path,
                "score": 0.0,
                "reasons": [],
                "seed_hits": 0,
                "expanded_hits": 0,
                "snippet_hits": 0,
                "app_context": False,
                "lines": [],
                "match_texts": [],
            }
            file_map[file_path] = entry
        return entry

    for item in search_hits:
        file_path = str(item.get("file") or item.get("file_path") or "").strip()
        if not file_path:
            continue
        entry = ensure_entry(file_path)
        if _is_expanded_hit(item):
            entry["score"] = float(entry["score"]) + 0.85
            entry["expanded_hits"] = int(entry["expanded_hits"]) + 1
            reason = f"expanded search: {item.get('why_relevant') or 'supporting context'}"
        else:
            entry["score"] = float(entry["score"]) + 1.6
            entry["seed_hits"] = int(entry["seed_hits"]) + 1
            reason = f"direct search: {item.get('why_relevant') or 'primary hit'}"
        reasons = entry["reasons"]
        if isinstance(reasons, list) and reason not in reasons:
            reasons.append(reason)
        match_texts = entry.get("match_texts", [])
        if isinstance(match_texts, list):
            for value in (item.get("target"), item.get("why_relevant")):
                text = str(value or "").strip()
                if text and text not in match_texts:
                    match_texts.append(text)
        if _is_frontend_graph_hit(item):
            entry["score"] = float(entry["score"]) + 0.55
            graph_reason = "graph-backed frontend path: indirect TypeScript/TSX implementation evidence"
            if isinstance(reasons, list) and graph_reason not in reasons:
                reasons.append(graph_reason)
        lines = item.get("lines")
        if isinstance(lines, list) and lines and lines not in entry["lines"]:
            entry["lines"].append(lines)

    for item in snippets:
        file_path = str(item.get("file") or item.get("file_path") or "").strip()
        if not file_path:
            continue
        entry = ensure_entry(file_path)
        entry["score"] = float(entry["score"]) + 1.0
        entry["snippet_hits"] = int(entry["snippet_hits"]) + 1
        reason = f"source snippet: {item.get('retrieval_source') or item.get('chunk_kind') or 'source context'}"
        reasons = entry["reasons"]
        if isinstance(reasons, list) and reason not in reasons:
            reasons.append(reason)
        match_texts = entry.get("match_texts", [])
        if isinstance(match_texts, list):
            for value in (item.get("target"), item.get("retrieval_source"), item.get("chunk_kind")):
                text = str(value or "").strip()
                if text and text not in match_texts:
                    match_texts.append(text)
        lines = item.get("lines")
        if isinstance(lines, list) and lines and lines not in entry["lines"]:
            entry["lines"].append(lines)

    app_summary = app.get("compact_summary", {}) if isinstance(app, dict) else {}
    for file_path in app_summary.get("top_files", []) if isinstance(app_summary, dict) else []:
        normalized = str(file_path or "").strip()
        if not normalized:
            continue
        entry = ensure_entry(normalized)
        entry["score"] = float(entry["score"]) + 0.45
        entry["app_context"] = True
        reasons = entry["reasons"]
        if isinstance(reasons, list) and "app context related file" not in reasons:
            reasons.append("app context related file")
        if _is_frontend_file(normalized) and int(app_summary.get("graph_edge_count", 0) or 0) > 0:
            frontend_reason = "frontend graph context: implementation may be discovered indirectly through graph edges"
            if isinstance(reasons, list) and frontend_reason not in reasons:
                reasons.append(frontend_reason)

    trace_summary = behavior_trace if isinstance(behavior_trace, dict) else {}
    for file_path in trace_summary.get("top_files", []) if isinstance(trace_summary.get("top_files", []), list) else []:
        normalized = str(file_path or "").strip()
        if not normalized:
            continue
        entry = ensure_entry(normalized)
        existing_score = float(entry.get("score", 0.0) or 0.0)
        boost = 1.15 if existing_score <= 0.45 else 0.6
        entry["score"] = existing_score + boost
        reasons = entry["reasons"]
        trace_reason = "behavior trace candidate"
        if isinstance(reasons, list) and trace_reason not in reasons:
            reasons.append(trace_reason)
        if _is_frontend_file(normalized):
            frontend_reason = "exploratory feature trace surfaced a frontend candidate"
            if isinstance(reasons, list) and frontend_reason not in reasons:
                reasons.append(frontend_reason)

    question_tokens = _question_tokens(question)
    exploratory_mode = _is_exploratory_intent(intent or {})
    wants_period_state = bool(question_tokens & {"period", "selector", "context", "contexts", "hook", "hooks", "date", "calendar", "financial"})
    mentions_export_reporting = bool(question_tokens & {"export", "report", "reporting"})
    wants_backend_endpoint = bool(question_tokens & {"backend", "endpoint", "endpoints", "api", "service", "services"})
    wants_page_primary = _page_primary_prompt(question_tokens)
    for token_set, hints in BEHAVIOR_OWNER_HINTS.items():
        if not token_set.issubset(question_tokens):
            continue
        for file_path, reason in hints:
            entry = ensure_entry(file_path)
            existing_score = float(entry.get("score", 0.0) or 0.0)
            boost = 2.1 if existing_score <= 0.45 else 1.0
            entry["score"] = existing_score + boost
            reasons = entry["reasons"]
            if isinstance(reasons, list) and reason not in reasons:
                reasons.append(reason)

    if exploratory_mode:
        for item in file_map.values():
            file_path = str(item.get("file", "") or "")
            normalized_path = file_path.replace("\\", "/").lower()
            match_text = " ".join(
                str(value or "").strip()
                for value in item.get("match_texts", [])
                if str(value or "").strip()
            )
            prompt_overlap = _meaningful_prompt_overlap(question_tokens, normalized_path)
            if match_text:
                prompt_overlap = max(prompt_overlap, _meaningful_prompt_overlap(question_tokens, match_text))
            reasons = item.get("reasons", [])
            if any(part in normalized_path for part in ("test-utils", "/tests/", "/test/", ".test.", ".spec.")):
                item["score"] = float(item.get("score", 0.0) or 0.0) - 2.5
                if isinstance(reasons, list) and "implausibility penalty: test/helper file for exploratory product-flow question" not in reasons:
                    reasons.append("implausibility penalty: test/helper file for exploratory product-flow question")
            elif any(part in normalized_path for part in ("/scripts/", "/script/", "installer", "monitor")):
                item["score"] = float(item.get("score", 0.0) or 0.0) - 1.4
                if isinstance(reasons, list) and "implausibility penalty: tooling/support file for exploratory product-flow question" not in reasons:
                    reasons.append("implausibility penalty: tooling/support file for exploratory product-flow question")
            if not mentions_export_reporting and any(part in normalized_path for part in ("export", "reportexport", "report_export")):
                item["score"] = float(item.get("score", 0.0) or 0.0) - 1.9
                if isinstance(reasons, list) and "implausibility penalty: export/report file does not match the prompt focus" not in reasons:
                    reasons.append("implausibility penalty: export/report file does not match the prompt focus")
            if any(part in normalized_path for part in ("/pages/", "page.", "landing", "/components/", "selector", "/contexts/", "/hooks/", "overview")):
                item["score"] = float(item.get("score", 0.0) or 0.0) + 1.25
                if isinstance(reasons, list) and "ui ownership bias: likely frontend owner/support file" not in reasons:
                    reasons.append("ui ownership bias: likely frontend owner/support file")
            if wants_page_primary and _is_page_owner_file(normalized_path):
                item["score"] = float(item.get("score", 0.0) or 0.0) + 1.35
                if isinstance(reasons, list) and "page-owner bias: prompt asks for the owning page first" not in reasons:
                    reasons.append("page-owner bias: prompt asks for the owning page first")
            if wants_page_primary and _is_shared_ui_file(normalized_path) and not _is_page_owner_file(normalized_path):
                item["score"] = float(item.get("score", 0.0) or 0.0) - 0.45
                if isinstance(reasons, list) and "secondary-role penalty: shared UI file should not outrank the owning page" not in reasons:
                    reasons.append("secondary-role penalty: shared UI file should not outrank the owning page")
            if wants_period_state and any(part in normalized_path for part in ("selector", "period", "context", "hook", "/contexts/", "/hooks/")):
                item["score"] = float(item.get("score", 0.0) or 0.0) + 1.35
                if isinstance(reasons, list) and "period-state bias: likely selector/context/hook file" not in reasons:
                    reasons.append("period-state bias: likely selector/context/hook file")
            if any(part in normalized_path for part in ("/api/", "/endpoints/", "/controllers/", "/services/")):
                item["score"] = float(item.get("score", 0.0) or 0.0) + 0.55
                if isinstance(reasons, list) and "flow bias: likely backend endpoint/service file" not in reasons:
                    reasons.append("flow bias: likely backend endpoint/service file")
            if wants_backend_endpoint and any(part in normalized_path for part in ("/api/", "/endpoints/", "/controllers/")):
                if prompt_overlap > 0:
                    item["score"] = float(item.get("score", 0.0) or 0.0) + 0.9
                    if isinstance(reasons, list) and "endpoint bias: likely backend route/controller file tied to the feature terms" not in reasons:
                        reasons.append("endpoint bias: likely backend route/controller file tied to the feature terms")
                elif wants_page_primary:
                    item["score"] = float(item.get("score", 0.0) or 0.0) - 1.6
                    if isinstance(reasons, list) and "endpoint mismatch penalty: backend route/controller is not tied to the page feature terms" not in reasons:
                        reasons.append("endpoint mismatch penalty: backend route/controller is not tied to the page feature terms")
            if wants_backend_endpoint and any(part in normalized_path for part in ("client_service", "export", "monitor")):
                item["score"] = float(item.get("score", 0.0) or 0.0) - 0.8
                if isinstance(reasons, list) and "backend mismatch penalty: weak endpoint/service fit for this prompt" not in reasons:
                    reasons.append("backend mismatch penalty: weak endpoint/service fit for this prompt")

    ranked = sorted(
        file_map.values(),
        key=lambda item: (
            float(item.get("score", 0.0) or 0.0),
            int(item.get("seed_hits", 0) or 0),
            int(item.get("snippet_hits", 0) or 0),
            str(item.get("file", "")),
        ),
        reverse=True,
    )
    compact: list[dict[str, object]] = []
    for item in ranked[:limit]:
        compact.append(
            {
                "file": item["file"],
                "score": round(float(item.get("score", 0.0) or 0.0), 4),
                "seed_hits": item.get("seed_hits", 0),
                "expanded_hits": item.get("expanded_hits", 0),
                "snippet_hits": item.get("snippet_hits", 0),
                "app_context": item.get("app_context", False),
                "reasons": item.get("reasons", [])[:4],
                "lines": item.get("lines", [])[:3],
            }
        )
    return compact

def _architecture_summary(unified: dict[str, object], app: dict[str, object]) -> dict[str, object]:
    unified_summary = unified.get("compact_summary", {}) if isinstance(unified, dict) else {}
    app_summary = app.get("compact_summary", {}) if isinstance(app, dict) else {}
    dependency_counts = unified_summary.get("dependency_counts", {}) if isinstance(unified_summary, dict) else {}
    file_kinds = app_summary.get("file_kinds", {}) if isinstance(app_summary, dict) else {}
    return {
        "caller_count": int(unified_summary.get("caller_count", 0) or 0) if isinstance(unified_summary, dict) else 0,
        "callee_count": int(unified_summary.get("callee_count", 0) or 0) if isinstance(unified_summary, dict) else 0,
        "top_neighbors": unified_summary.get("top_neighbors", []) if isinstance(unified_summary, dict) else [],
        "top_routes": app_summary.get("top_routes", []) if isinstance(app_summary, dict) else [],
        "top_processes": app_summary.get("top_processes", []) if isinstance(app_summary, dict) else [],
        "file_kinds": file_kinds if isinstance(file_kinds, dict) else {},
        "dependency_counts": dependency_counts if isinstance(dependency_counts, dict) else {},
        "graph_edge_count": int(app_summary.get("graph_edge_count", 0) or 0) if isinstance(app_summary, dict) else 0,
    }


def _data_flow_summary(architecture: dict[str, object]) -> list[str]:
    points: list[str] = []
    caller_count = int(architecture.get("caller_count", 0) or 0)
    callee_count = int(architecture.get("callee_count", 0) or 0)
    if caller_count or callee_count:
        points.append(f"Graph context shows {caller_count} callers and {callee_count} callees.")
    top_routes = architecture.get("top_routes", [])
    if isinstance(top_routes, list) and top_routes:
        points.append(f"Related routes: {', '.join(str(route) for route in top_routes[:3])}.")
    top_processes = architecture.get("top_processes", [])
    if isinstance(top_processes, list) and top_processes:
        points.append(f"Relevant processes: {', '.join(str(process) for process in top_processes[:3])}.")
    dependency_counts = architecture.get("dependency_counts", {})
    if isinstance(dependency_counts, dict) and dependency_counts:
        top_groups = sorted(dependency_counts.items(), key=lambda item: int(item[1] or 0), reverse=True)[:3]
        points.append("Dependencies touched: " + ", ".join(f"{name}={count}" for name, count in top_groups) + ".")
    return points

def _exploratory_file_groups(
    ranked_files: list[dict[str, object]],
    behavior_trace: dict[str, object],
    architecture: dict[str, object],
) -> dict[str, list[str]]:
    page_files: list[str] = []
    shared_ui_files: list[str] = []
    backend_files: list[str] = []
    endpoint_routes: list[str] = []

    def add_unique(target: list[str], value: object, limit: int = 4) -> None:
        candidate = str(value or "").strip()
        if candidate and candidate not in target and len(target) < limit:
            target.append(candidate)

    trace_roles = behavior_trace.get("role_groups", {}) if isinstance(behavior_trace.get("role_groups", {}), dict) else {}
    for value in trace_roles.get("page_files", []) if isinstance(trace_roles.get("page_files", []), list) else []:
        add_unique(page_files, value)
    for value in trace_roles.get("shared_ui_files", []) if isinstance(trace_roles.get("shared_ui_files", []), list) else []:
        add_unique(shared_ui_files, value)
    for value in trace_roles.get("backend_files", []) if isinstance(trace_roles.get("backend_files", []), list) else []:
        add_unique(backend_files, value)

    for item in ranked_files[:8]:
        file_path = str(item.get("file", "") or "")
        normalized = file_path.replace("\\", "/").lower()
        if any(part in normalized for part in ("/pages/", "landing", "overview")):
            add_unique(page_files, file_path)
        if any(part in normalized for part in ("/components/", "selector", "/contexts/", "/hooks/", "filter", "period")):
            add_unique(shared_ui_files, file_path)
        if any(part in normalized for part in ("/api/", "/endpoints/", "/controllers/", "/services/")):
            add_unique(backend_files, file_path)

    for file_path in behavior_trace.get("top_files", []) if isinstance(behavior_trace.get("top_files", []), list) else []:
        normalized = str(file_path or "").replace("\\", "/").lower()
        if any(part in normalized for part in ("/pages/", "landing", "overview")):
            add_unique(page_files, file_path)
        elif any(part in normalized for part in ("/components/", "selector", "/contexts/", "/hooks/", "filter", "period")):
            add_unique(shared_ui_files, file_path)
        elif any(part in normalized for part in ("/api/", "/endpoints/", "/controllers/", "/services/")):
            add_unique(backend_files, file_path)

    for route in architecture.get("top_routes", []) if isinstance(architecture.get("top_routes", []), list) else []:
        add_unique(endpoint_routes, route)

    return {
        "page_files": page_files,
        "shared_ui_files": shared_ui_files,
        "backend_files": backend_files,
        "endpoint_routes": endpoint_routes,
    }

def _evidence_items(
    seed_hits: list[dict[str, object]],
    expanded_hits: list[dict[str, object]],
    snippets: list[dict[str, object]],
    unified: dict[str, object],
    app: dict[str, object],
    ranked_files: list[dict[str, object]] | None = None,
    intent: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    exploratory_mode = _is_exploratory_intent(intent or {})
    ranked_files = ranked_files if isinstance(ranked_files, list) else []
    allowed_files = {
        str(item.get("file", "")).strip()
        for item in ranked_files[:6]
        if str(item.get("file", "")).strip()
    }

    def include_file(file_path: object) -> bool:
        normalized = str(file_path or "").strip()
        if not normalized:
            return not exploratory_mode
        lowered = normalized.replace("\\", "/").lower()
        if exploratory_mode:
            if _is_implausible_exploratory_file(lowered):
                return False
            if allowed_files and normalized not in allowed_files:
                return False
        return True

    evidence: list[dict[str, object]] = []
    for item in seed_hits[:4]:
        if not include_file(item.get("file")):
            continue
        source_name = "graph_frontend_seed" if _is_frontend_graph_hit(item) else "search_seed"
        reason = item.get("why_relevant")
        if exploratory_mode and _is_noise_reason(reason):
            continue
        if _is_frontend_graph_hit(item):
            reason = f"graph-backed frontend evidence: {reason or 'indirect TypeScript/TSX implementation path'}"
        evidence.append(
            {
                "source": source_name,
                "target": item.get("target"),
                "file": item.get("file"),
                "lines": item.get("lines"),
                "reason": reason,
            }
        )
    for item in expanded_hits[:4]:
        if not include_file(item.get("file")):
            continue
        source_name = "graph_frontend_expanded" if _is_frontend_graph_hit(item) else "search_expanded"
        reason = item.get("why_relevant")
        if exploratory_mode and _is_noise_reason(reason):
            continue
        if _is_frontend_graph_hit(item):
            reason = f"graph-backed frontend evidence: {reason or 'indirect TypeScript/TSX implementation path'}"
        evidence.append(
            {
                "source": source_name,
                "target": item.get("target"),
                "file": item.get("file"),
                "lines": item.get("lines"),
                "reason": reason,
            }
        )
    for item in snippets[:3]:
        file_path = item.get("file") or item.get("file_path")
        if not include_file(file_path):
            continue
        reason = item.get("retrieval_source") or item.get("chunk_kind")
        if exploratory_mode and _is_noise_reason(reason):
            continue
        evidence.append(
            {
                "source": "source_context",
                "target": item.get("target"),
                "file": file_path,
                "lines": item.get("lines"),
                "reason": reason,
            }
        )
    summary = unified.get("compact_summary", {}) if isinstance(unified, dict) else {}
    for neighbor in summary.get("top_neighbors", []) if isinstance(summary, dict) else []:
        if isinstance(neighbor, dict):
            evidence.append({"source": "graph", "target": neighbor.get("node"), "reason": f"{neighbor.get('edge_count', 0)} graph edges"})
    app_summary = app.get("compact_summary", {}) if isinstance(app, dict) else {}
    for file_path in app_summary.get("top_files", []) if isinstance(app_summary, dict) else []:
        if not include_file(file_path):
            continue
        evidence.append({"source": "app_context", "file": file_path, "reason": "app-level related file"})
    return evidence[:12]
