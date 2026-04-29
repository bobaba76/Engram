from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING

from mcp_server.resolvers import resolve_tool_target
from services.app_context_service import app_context
from services.source_retrieval_service import get_source_context
from services.unified_context_service import get_unified_context

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore
    from storage.vector_store import VectorStore


LOCATION_TOKENS = {"where", "handled", "located", "defined", "implemented", "lives", "entrypoint", "entry", "owns", "owner"}
FLOW_TOKENS = {"why", "flow", "path", "happen", "happens", "trigger", "sequence", "execution", "called", "calls"}
IMPACT_TOKENS = {"impact", "break", "breaks", "affected", "affects", "change", "changing", "depends", "dependents", "blast"}
TEST_TOKENS = {"test", "tests", "verify", "coverage", "spec", "specs"}
API_TOKENS = {"api", "route", "endpoint", "request", "response", "consumer", "handler"}
BUG_TOKENS = {"bug", "broken", "issue", "wrong", "error", "failing", "fix", "problem"}
STOPWORD_TOKENS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "be",
    "do",
    "does",
    "did",
    "how",
    "what",
    "where",
    "why",
    "when",
    "which",
    "please",
    "me",
    "my",
    "this",
    "that",
    "it",
    "if",
    "after",
    "before",
    "with",
    "for",
    "to",
    "of",
    "in",
    "on",
    "at",
}


def _question_tokens(question: str) -> set[str]:
    return {token for token in re.split(r"[^a-zA-Z0-9]+", str(question or "").lower()) if token}


def _question_intent(question: str) -> dict[str, object]:
    tokens = _question_tokens(question)
    score_map = {
        "location": len(tokens & LOCATION_TOKENS),
        "flow": len(tokens & FLOW_TOKENS),
        "impact": len(tokens & IMPACT_TOKENS),
        "tests": len(tokens & TEST_TOKENS),
        "api": len(tokens & API_TOKENS),
        "bug": len(tokens & BUG_TOKENS),
    }
    primary = max(score_map, key=score_map.get) if any(score_map.values()) else "general"
    secondary = [name for name, score in sorted(score_map.items(), key=lambda item: item[1], reverse=True) if score > 0 and name != primary][:2]
    return {
        "primary": primary,
        "secondary": secondary,
        "scores": score_map,
        "tokens": sorted(tokens)[:20],
    }


def _symbolish_terms(question: str, limit: int = 8) -> list[str]:
    raw_question = str(question or "")
    candidates = re.findall(r"[A-Za-z_][A-Za-z0-9_\.\/:-]{2,}", raw_question)
    candidates.extend(re.findall(r"/[A-Za-z0-9_\-./:]+", raw_question))
    unique: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip(" .,:;()[]{}\"'")
        if not normalized:
            continue
        if normalized.lower() in STOPWORD_TOKENS:
            continue
        if normalized not in unique:
            unique.append(normalized)
        if len(unique) >= limit:
            break
    return unique


def _query_rewrite(question: str, intent: dict[str, object]) -> dict[str, object]:
    normalized = " ".join(str(question or "").strip().split())
    tokens = [token for token in _question_tokens(normalized) if token not in STOPWORD_TOKENS]
    symbol_terms = _symbolish_terms(normalized)
    route_terms = [term for term in symbol_terms if term.startswith("/") or "/api/" in term.lower()]
    file_terms = [term for term in symbol_terms if "/" in term or term.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))]
    primary_intent = str(intent.get("primary", "general") or "general")
    core_terms = [term for term in tokens if len(term) >= 3][:8]
    rewritten_variants: list[str] = []

    def add_variant(value: str) -> None:
        cleaned = " ".join(str(value or "").split()).strip()
        if cleaned and cleaned not in rewritten_variants:
            rewritten_variants.append(cleaned)

    if normalized:
        add_variant(normalized)
    if symbol_terms:
        add_variant(" ".join(symbol_terms[:4]))
    if core_terms:
        add_variant(" ".join(core_terms[:6]))

    if primary_intent == "location" and core_terms:
        add_variant("implementation location " + " ".join(core_terms[:5]))
    elif primary_intent == "flow" and core_terms:
        add_variant("execution flow " + " ".join(core_terms[:5]))
        add_variant("call path " + " ".join(core_terms[:5]))
    elif primary_intent == "impact" and core_terms:
        add_variant("change impact " + " ".join(core_terms[:5]))
        add_variant("dependents " + " ".join(core_terms[:5]))
    elif primary_intent == "tests" and core_terms:
        add_variant("tests " + " ".join(core_terms[:5]))
    elif primary_intent == "api" and core_terms:
        add_variant("api route handler " + " ".join(core_terms[:5]))
    elif primary_intent == "bug" and core_terms:
        add_variant("bug root cause " + " ".join(core_terms[:5]))

    search_seeds: list[str] = []
    for value in [*symbol_terms, *route_terms, *file_terms, *rewritten_variants]:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in search_seeds:
            search_seeds.append(cleaned)

    return {
        "normalized_question": normalized,
        "core_terms": core_terms,
        "symbol_terms": symbol_terms,
        "route_terms": route_terms,
        "file_terms": file_terms,
        "rewritten_queries": rewritten_variants[:6],
        "search_seeds": search_seeds[:10],
    }


def _best_seed_target(
    normalized_question: str,
    query_rewrite: dict[str, object],
    seed_hits: list[dict[str, object]],
    expanded_hits: list[dict[str, object]],
) -> str:
    for collection in (seed_hits, expanded_hits):
        if collection:
            first = collection[0]
            candidate = str(first.get("target") or first.get("file") or "").strip()
            if candidate:
                return candidate
    for field in ("symbol_terms", "route_terms", "file_terms", "search_seeds"):
        values = query_rewrite.get(field, [])
        if isinstance(values, list):
            for value in values:
                candidate = str(value or "").strip()
                if candidate:
                    return candidate
    return normalized_question


def _app_context_target(question: str, resolved_target: str, query_rewrite: dict[str, object]) -> tuple[str, str]:
    normalized = str(question or "").strip()
    symbol_terms = query_rewrite.get("symbol_terms", [])
    file_terms = query_rewrite.get("file_terms", [])
    route_terms = query_rewrite.get("route_terms", [])
    if isinstance(file_terms, list) and file_terms:
        return str(file_terms[0]), "file_term"
    if isinstance(route_terms, list) and route_terms:
        return str(route_terms[0]), "route_term"
    if isinstance(symbol_terms, list) and symbol_terms:
        return str(symbol_terms[0]), "symbol_term"
    if resolved_target and resolved_target != normalized:
        return resolved_target, "resolved_target"
    return normalized, "question"


def _broad_question_guardrails(question: str, intent: dict[str, object], query_rewrite: dict[str, object], limit: int) -> dict[str, object]:
    normalized = str(question or "").strip()
    tokens = _question_tokens(normalized)
    token_count = len(tokens)
    file_terms = query_rewrite.get("file_terms", [])
    route_terms = query_rewrite.get("route_terms", [])
    has_hard_anchor = any(isinstance(values, list) and values for values in (file_terms, route_terms))
    primary_intent = str(intent.get("primary", "general") or "general")
    broad_cues = {"behavior", "handled", "flow", "logic", "path", "works", "work"}
    broad_question = (
        primary_intent in {"location", "flow", "general"}
        and not has_hard_anchor
        and (token_count >= 5 or bool(broad_cues & set(tokens)))
    )
    warnings: list[str] = []
    if broad_question:
        warnings.append("Question is broad; retrieval was narrowed to avoid expensive fan-out.")
        warnings.append("Use an exact symbol or file path for a deeper follow-up if needed.")
    return {
        "broad_question": broad_question,
        "search_limit": max(3, min(limit, 4)) if broad_question else limit,
        "expanded_hit_limit": max(2, min(limit, 4)) if broad_question else max(limit + 1, 6),
        "evidence_limit": max(4, min(limit + 1, 5)) if broad_question else max(limit + 3, 8),
        "retry_limit": 1 if broad_question else 4,
        "allow_retry": not broad_question,
        "warnings": warnings,
    }


def investigation_search_task(question: str, limit: int = 5) -> tuple[str, dict[str, object]]:
    normalized_question = str(question or "").strip()
    intent = _question_intent(normalized_question)
    query_rewrite = _query_rewrite(normalized_question, intent)
    guardrails = _broad_question_guardrails(normalized_question, intent, query_rewrite, limit)
    task = normalized_question
    task_source = "question"
    for field, source in (
        ("file_terms", "file_term"),
        ("route_terms", "route_term"),
        ("symbol_terms", "symbol_term"),
        ("search_seeds", "search_seed"),
    ):
        values = query_rewrite.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            candidate = str(value or "").strip()
            if not candidate:
                continue
            if bool(guardrails.get("broad_question")) and source == "search_seed" and " " in candidate:
                continue
            task = candidate
            task_source = source
            return task, {
                "intent": intent,
                "query_rewrite": query_rewrite,
                "guardrails": guardrails,
                "task_source": task_source,
                "original_question": normalized_question,
            }
    return task, {
        "intent": intent,
        "query_rewrite": query_rewrite,
        "guardrails": guardrails,
        "task_source": task_source,
        "original_question": normalized_question,
    }


def _alternate_seed_targets(seed_target: str, query_rewrite: dict[str, object], limit: int = 4) -> list[str]:
    candidates: list[str] = []
    for field in ("symbol_terms", "route_terms", "file_terms", "search_seeds", "rewritten_queries"):
        values = query_rewrite.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            candidate = str(value or "").strip()
            if not candidate or candidate == seed_target or candidate in candidates:
                continue
            candidates.append(candidate)
            if len(candidates) >= limit:
                return candidates
    return candidates


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


def _file_relevance(search_hits: list[dict[str, object]], snippets: list[dict[str, object]], app: dict[str, object], limit: int = 8) -> list[dict[str, object]]:
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


def _evidence_items(
    seed_hits: list[dict[str, object]],
    expanded_hits: list[dict[str, object]],
    snippets: list[dict[str, object]],
    unified: dict[str, object],
    app: dict[str, object],
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for item in seed_hits[:4]:
        source_name = "graph_frontend_seed" if _is_frontend_graph_hit(item) else "search_seed"
        reason = item.get("why_relevant")
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
        source_name = "graph_frontend_expanded" if _is_frontend_graph_hit(item) else "search_expanded"
        reason = item.get("why_relevant")
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
        evidence.append(
            {
                "source": "source_context",
                "target": item.get("target"),
                "file": item.get("file") or item.get("file_path"),
                "lines": item.get("lines"),
                "reason": item.get("retrieval_source") or item.get("chunk_kind"),
            }
        )
    summary = unified.get("compact_summary", {}) if isinstance(unified, dict) else {}
    for neighbor in summary.get("top_neighbors", []) if isinstance(summary, dict) else []:
        if isinstance(neighbor, dict):
            evidence.append({"source": "graph", "target": neighbor.get("node"), "reason": f"{neighbor.get('edge_count', 0)} graph edges"})
    app_summary = app.get("compact_summary", {}) if isinstance(app, dict) else {}
    for file_path in app_summary.get("top_files", []) if isinstance(app_summary, dict) else []:
        evidence.append({"source": "app_context", "file": file_path, "reason": "app-level related file"})
    return evidence[:12]


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
    answer = (
        f"For '{question}', the best current target is {resolved_target}."
        f"{intent_text}{file_text}{graph_text}{route_text}{evidence_text}{indirect_frontend_text}{diagnostics_suffix}"
        " Use the evidence list for exact files and line ranges."
    )
    return answer, confidence, open_questions


def investigate_codebase(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    question: str,
    search_payload: dict[str, object] | None = None,
    limit: int = 5,
) -> dict[str, object]:
    normalized_question = str(question or "").strip()
    payload_search_plan = search_payload.get("investigation_search_plan", {}) if isinstance(search_payload, dict) else {}
    search_task, search_plan = investigation_search_task(normalized_question, limit=limit)
    if isinstance(payload_search_plan, dict):
        merged_plan = dict(search_plan)
        merged_plan.update({key: value for key, value in payload_search_plan.items() if value is not None})
        search_plan = merged_plan
    intent = search_plan["intent"] if isinstance(search_plan.get("intent"), dict) else _question_intent(normalized_question)
    query_rewrite = search_plan["query_rewrite"] if isinstance(search_plan.get("query_rewrite"), dict) else _query_rewrite(normalized_question, intent)
    guardrails = search_plan["guardrails"] if isinstance(search_plan.get("guardrails"), dict) else _broad_question_guardrails(normalized_question, intent, query_rewrite, limit)
    search_payload = search_payload or {"compact_results": []}
    search_hits = _compact_hits(search_payload, limit=int(guardrails.get("search_limit", limit) or limit))
    diagnostics = _retrieval_diagnostics(search_payload)
    warnings = list(guardrails.get("warnings", [])) if isinstance(guardrails.get("warnings"), list) else []
    seed_hits, expanded_hits = _classify_search_hits(search_hits)
    expanded_hit_limit = int(guardrails.get("expanded_hit_limit", max(limit + 1, 6)) or max(limit + 1, 6))
    if len(expanded_hits) > expanded_hit_limit:
        expanded_hits = expanded_hits[:expanded_hit_limit]
        warnings.append("Expanded retrieval was capped to keep the investigation responsive.")
    seed_target = _best_seed_target(normalized_question, query_rewrite, seed_hits, expanded_hits)
    if bool(guardrails.get("broad_question")) and str(search_plan.get("task_source", "question")) != "question":
        narrowed_task = str(search_task or "").strip()
        if narrowed_task:
            seed_target = narrowed_task
            warnings.append(f"Investigation was anchored to narrowed search term '{narrowed_task}'.")

    resolution = resolve_tool_target(duckdb_store, repo_root, target=seed_target, limit=limit)
    resolved_target = str(resolution.get("resolved_target") or seed_target)
    app_target, app_target_source = _app_context_target(normalized_question, resolved_target, query_rewrite)
    if bool(guardrails.get("broad_question")) and _is_generic_target(resolved_target) and app_target_source in {"file_term", "route_term", "symbol_term"}:
        narrowed_target = str(app_target or "").strip()
        if narrowed_target and narrowed_target != resolved_target:
            resolution = resolve_tool_target(duckdb_store, repo_root, target=narrowed_target, limit=limit)
            resolved_target = str(resolution.get("resolved_target") or narrowed_target)
            if _is_generic_target(resolved_target):
                resolved_target = narrowed_target
            warnings.append(f"Generic target resolution was replaced with narrowed term '{narrowed_target}'.")
    app = app_context(repo_root, duckdb_store, kuzu_store, target=app_target, limit=6)
    source_context = get_source_context(duckdb_store, resolved_target, limit=3, repo_root=repo_root)
    unified = get_unified_context(duckdb_store, kuzu_store, resolved_target, max_matches=3, neighborhood_depth=1)
    snippets = source_context.get("compact_results", [])
    snippets_list = [item for item in snippets if isinstance(item, dict)] if isinstance(snippets, list) else []
    attempted_passes = [seed_target]
    retry_used = False
    retry_reason = ""
    if bool(guardrails.get("allow_retry")) and _should_retry_investigation(seed_hits, expanded_hits, snippets_list):
        retry_reason = "weak_primary" if expanded_hits else "no_direct_evidence"
        current_strength = _investigation_strength(seed_hits, expanded_hits, snippets_list, resolved_target)
        retry_limit = int(guardrails.get("retry_limit", 4) or 4)
        for alternate_seed in _alternate_seed_targets(seed_target, query_rewrite, limit=retry_limit):
            attempted_passes.append(alternate_seed)
            retry_resolution = resolve_tool_target(duckdb_store, repo_root, target=alternate_seed, limit=limit)
            retry_target = str(retry_resolution.get("resolved_target") or alternate_seed)
            retry_source_context = get_source_context(duckdb_store, retry_target, limit=3, repo_root=repo_root)
            retry_snippets = retry_source_context.get("compact_results", [])
            retry_snippets_list = [item for item in retry_snippets if isinstance(item, dict)] if isinstance(retry_snippets, list) else []
            retry_strength = _investigation_strength(seed_hits, expanded_hits, retry_snippets_list, retry_target)
            if retry_strength > current_strength:
                resolution = retry_resolution
                resolved_target = retry_target
                source_context = retry_source_context
                snippets_list = retry_snippets_list
                snippets = retry_snippets
                unified = get_unified_context(duckdb_store, kuzu_store, resolved_target, max_matches=3, neighborhood_depth=1)
                retry_used = True
                break
    elif _should_retry_investigation(seed_hits, expanded_hits, snippets_list):
        retry_reason = "guardrail_skipped"
        warnings.append("Alternate-seed retries were skipped because the question is broad.")

    app_summary = app.get("compact_summary", {}) if isinstance(app, dict) else {}
    unified_summary = unified.get("compact_summary", {}) if isinstance(unified, dict) else {}
    evidence_limit = int(guardrails.get("evidence_limit", max(limit + 3, 8)) or max(limit + 3, 8))
    ranked_files = _file_relevance(search_hits, snippets_list, app, limit=evidence_limit)
    key_files = [str(item.get("file", "")) for item in ranked_files if str(item.get("file", "")).strip()]
    architecture = _architecture_summary(unified, app)
    graph_signal = _graph_frontend_signal(search_hits, ranked_files, architecture)
    data_flow_points = _data_flow_summary(architecture)
    evidence = _evidence_items(seed_hits, expanded_hits, snippets_list, unified, app)
    if len(evidence) > evidence_limit:
        evidence = evidence[:evidence_limit]
        warnings.append("Evidence was truncated to keep the result compact.")
    answer, confidence, open_questions = _synthesize_answer(normalized_question, resolved_target, ranked_files, evidence, diagnostics, architecture, seed_hits, expanded_hits, intent, graph_signal)
    profile = _guidance_profile(resolution, diagnostics, seed_hits, expanded_hits, snippets_list, ranked_files, architecture, intent, graph_signal)
    next_steps = _guidance_next_steps(profile, resolved_target, normalized_question)
    if unified_summary.get("caller_count") or unified_summary.get("callee_count"):
        if "Review callers/callees from unified_context." not in next_steps:
            next_steps.append("Review callers/callees from unified_context.")
    next_tools = _guidance_next_tools(profile, resolved_target, normalized_question)
    guidance_summary = _guidance_summary(profile)

    return {
        "question": normalized_question,
        "target": resolved_target,
        "intent": intent,
        "query_rewrite": query_rewrite,
        "seed_target": seed_target,
        "search_task": {"task": search_task, "source": search_plan.get("task_source", "question")},
        "guardrails": guardrails,
        "app_context_target": {"target": app_target, "source": app_target_source},
        "investigation_passes": {
            "attempted_seeds": attempted_passes,
            "retry_used": retry_used,
            "retry_reason": retry_reason,
        },
        "warnings": warnings,
        "answer": answer,
        "confidence": confidence,
        "evidence": evidence,
        "evidence_breakdown": {
            "seed_hits": seed_hits,
            "expanded_hits": expanded_hits,
            "source_snippets": snippets_list[:6],
        },
        "retrieval_diagnostics": diagnostics,
        "ranked_files": ranked_files,
        "architecture_summary": architecture,
        "graph_signal": graph_signal,
        "data_flow_summary": data_flow_points,
        "guidance_summary": guidance_summary,
        "open_questions": open_questions,
        "next_tools": next_tools,
        "resolution": resolution,
        "search": search_payload,
        "source_context": source_context,
        "unified_context": unified,
        "app_context": app,
        "answer_outline": [
            f"Primary target: {resolved_target}",
            f"Key files: {', '.join(key_files[:6])}" if key_files else "Key files: no strong file candidates",
            f"Search hits: {len(search_hits)} ({len(seed_hits)} seed, {len(expanded_hits)} expanded)",
            f"Snippet hits: {len(snippets_list)}",
        ] + data_flow_points[:3],
        "next_steps": next_steps,
        "compact_summary": {
            "target": resolved_target,
            "question": normalized_question,
            "confidence": confidence,
            "intent": intent,
            "query_rewrite": query_rewrite,
            "seed_target": seed_target,
            "search_task": {"task": search_task, "source": search_plan.get("task_source", "question")},
            "guardrails": guardrails,
            "app_context_target": {"target": app_target, "source": app_target_source},
            "investigation_passes": {
                "attempted_seeds": attempted_passes,
                "retry_used": retry_used,
                "retry_reason": retry_reason,
            },
            "warnings": warnings,
            "top_files": key_files[:8],
            "top_file_reasons": {str(item.get("file", "")): item.get("reasons", [])[:3] for item in ranked_files[:5]},
            "top_symbols": _unique_strings([item.get("target") for item in search_hits[:5] if item.get("target")]),
            "snippet_count": len(snippets_list),
            "evidence_count": len(evidence),
            "seed_hit_count": len(seed_hits),
            "expanded_hit_count": len(expanded_hits),
            "guidance": guidance_summary,
            "app_files": app_summary.get("top_files", []),
            "top_neighbors": unified_summary.get("top_neighbors", []),
            "graph_signal": graph_signal,
        },
    }
