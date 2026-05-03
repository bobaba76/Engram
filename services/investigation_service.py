from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING

from mcp_server.resolvers import resolve_tool_target
from services.app_context_service import app_context
from services.feature_context_service import feature_context
from services.source_retrieval_service import get_source_context
from services.test_intelligence_service import find_tests_for_target
from services.unified_context_service import get_unified_context

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore
    from storage.vector_store import VectorStore


LOCATION_TOKENS = {"where", "handled", "located", "defined", "implemented", "lives", "entrypoint", "entry", "owns", "owner"}
FLOW_TOKENS = {"why", "flow", "path", "happen", "happens", "trigger", "sequence", "execution", "called", "calls"}
IMPACT_TOKENS = {"impact", "break", "breaks", "affected", "affects", "affect", "change", "changing", "depends", "dependents", "blast"}
TEST_TOKENS = {"test", "tests", "verify", "coverage", "spec", "specs"}
API_TOKENS = {"api", "route", "endpoint", "request", "response", "consumer", "handler"}
BUG_TOKENS = {"bug", "broken", "issue", "wrong", "error", "failing", "fix", "problem"}
UI_TOKENS = {"page", "screen", "dashboard", "overview", "selector", "filter", "tab", "modal", "form", "frontend", "view", "landing"}
EXPLORATION_TOKENS = {"find", "show", "trace", "investigate", "check", "explore", "walk", "follow", "including", "shared"}
IMPERATIVE_SEED_TOKENS = {"find", "show", "trace", "investigate", "check", "explore", "walk", "follow", "including"}
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
GENERIC_SEARCH_TERMS = {
    "behavior",
    "handled",
    "logic",
    "flow",
    "path",
    "works",
    "work",
    "main",
    "app",
    "index",
    "default",
    "view",
}
BEHAVIOR_TRACE_TOKENS = {
    "page",
    "view",
    "selector",
    "filter",
    "frontend",
    "backend",
    "financial",
    "calendar",
    "period",
    "overview",
    "landing",
    "widget",
    "dropdown",
}
WEAK_BROAD_SEED_TERMS = {
    "mcp",
    "reporting",
    "status",
    "selection",
    "progress",
    "health",
    "index",
    "flow",
    "trace",
    "find",
    "app",
    "utility",
    "utilities",
    "shared",
}
GENERIC_EXPLORATORY_NOUNS = {
    "utility",
    "utilities",
    "shared",
    "code",
    "logic",
    "flow",
    "path",
}
BEHAVIOR_TRACE_ALIASES = {
    frozenset({"repo", "selection"}): ["select_repo", "select_repo_tool"],
    frozenset({"mcp", "repo"}): ["select_repo", "run_mcp"],
    frozenset({"indexing", "progress"}): ["_log_progress", "run_index"],
    frozenset({"progress", "reporting"}): ["_log_progress", "run_summary"],
    frozenset({"index", "health"}): ["index_health", "index_health_tool"],
    frozenset({"health", "status"}): ["index_status", "index_health"],
    frozenset({"period", "selector"}): ["PeriodSelector", "selectedPeriod"],
}
BEHAVIOR_OWNER_HINTS = {
    frozenset({"mcp", "repo", "selection"}): [
        ("scripts/run_mcp.py", "owner hint: MCP repo selection entrypoint"),
    ],
    frozenset({"indexing", "progress"}): [
        ("app/coordinator.py", "owner hint: indexing progress coordinator"),
        ("scripts/run_index.py", "owner hint: indexing entrypoint"),
    ],
    frozenset({"progress", "reporting"}): [
        ("app/coordinator.py", "owner hint: progress reporting coordinator"),
        ("scripts/run_index.py", "owner hint: progress reporting entrypoint"),
    ],
    frozenset({"index", "health"}): [
        ("services/index_health_service.py", "owner hint: index health service"),
    ],
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
        "ui_ownership": len(tokens & UI_TOKENS),
        "feature_exploration": len(tokens & EXPLORATION_TOKENS),
    }
    primary = max(score_map, key=score_map.get) if any(score_map.values()) else "general"
    if score_map.get("ui_ownership", 0) >= 2 and score_map.get("feature_exploration", 0) >= 1:
        primary = "ui_ownership"
    elif score_map.get("feature_exploration", 0) >= 2 and primary == "general":
        primary = "feature_exploration"
    secondary = [name for name, score in sorted(score_map.items(), key=lambda item: item[1], reverse=True) if score > 0 and name != primary][:2]
    return {
        "primary": primary,
        "secondary": secondary,
        "scores": score_map,
        "tokens": sorted(tokens)[:20],
    }


def _should_enrich_behavior_trace(question: str, intent: dict[str, object], guardrails: dict[str, object]) -> bool:
    tokens = _question_tokens(question)
    if not tokens:
        return False
    primary = str(intent.get("primary", "general") or "general")
    exploratory_tokens = BEHAVIOR_TRACE_TOKENS | {"mcp", "repo", "selection", "indexing", "progress", "health", "status"}
    return primary in {"location", "flow", "general", "ui_ownership", "feature_exploration"} and (
        bool(guardrails.get("broad_question"))
        or (len(tokens) >= 5 and bool(tokens & exploratory_tokens))
    )


def _symbolish_terms(question: str, limit: int = 8) -> list[str]:
    raw_question = str(question or "")
    candidates = re.findall(r"[A-Za-z_][A-Za-z0-9_\.\/:-]{2,}", raw_question)
    candidates.extend(re.findall(r"/[A-Za-z0-9_\-./:]+", raw_question))
    scored: list[tuple[int, int, str]] = []
    for candidate in candidates:
        normalized = candidate.strip(" .,:;()[]{}\"'")
        if not normalized:
            continue
        if normalized.lower() in STOPWORD_TOKENS:
            continue
        if normalized.lower() in IMPERATIVE_SEED_TOKENS:
            continue
        if normalized.lower() in GENERIC_EXPLORATORY_NOUNS:
            continue
        score = 0
        if any(marker in normalized for marker in (".", "/", ":", "\\")):
            score += 5
        if normalized.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
            score += 3
        if re.search(r"[a-z][A-Z]", normalized):
            score += 3
        if not normalized.islower():
            score += 1
        if normalized.lower() in GENERIC_SEARCH_TERMS:
            score -= 3
        if normalized.lower() in GENERIC_EXPLORATORY_NOUNS:
            score -= 4
        if normalized.isalpha() and normalized.islower():
            score -= 2
        if normalized.lower() in IMPERATIVE_SEED_TOKENS:
            score -= 8
        scored.append((score, len(normalized), normalized))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    unique: list[str] = []
    for _, _, candidate in scored:
        if candidate not in unique:
            unique.append(candidate)
        if len(unique) >= limit:
            break
    return unique


def _query_rewrite(question: str, intent: dict[str, object]) -> dict[str, object]:
    normalized = " ".join(str(question or "").strip().split())
    tokens = [token for token in _question_tokens(normalized) if token not in STOPWORD_TOKENS and token not in IMPERATIVE_SEED_TOKENS]
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
    elif primary_intent in {"ui_ownership", "feature_exploration"} and core_terms:
        add_variant("frontend page " + " ".join(core_terms[:5]))
        add_variant("shared selector context " + " ".join(core_terms[:5]))
        add_variant("backend endpoint " + " ".join(core_terms[:5]))

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
    for field in ("file_terms", "route_terms", "symbol_terms"):
        values = query_rewrite.get(field, [])
        if isinstance(values, list):
            for value in values:
                candidate = str(value or "").strip()
                if candidate:
                    return candidate
    for collection in (seed_hits, expanded_hits):
        if collection:
            first = collection[0]
            candidate = str(first.get("target") or first.get("file") or "").strip()
            if candidate:
                return candidate
    for field in ("search_seeds",):
        values = query_rewrite.get(field, [])
        if isinstance(values, list):
            for value in values:
                candidate = str(value or "").strip()
                if candidate:
                    return candidate
    return normalized_question


def _app_context_target(question: str, resolved_target: str, query_rewrite: dict[str, object]) -> tuple[str, str]:
    normalized = str(question or "").strip()
    behavior_seed = _ui_feature_seed_from_behavior(normalized, query_rewrite)
    if behavior_seed:
        return behavior_seed, "behavior_trace_feature"
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


def _is_weak_broad_seed(candidate: str) -> bool:
    normalized = str(candidate or "").strip().lower()
    if not normalized:
        return True
    tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", normalized) if token]
    if not tokens:
        return True
    if len(tokens) == 1 and (normalized in WEAK_BROAD_SEED_TERMS or len(normalized) <= 4):
        return True
    return all(
        token in WEAK_BROAD_SEED_TERMS
        or token in GENERIC_SEARCH_TERMS
        or token in GENERIC_EXPLORATORY_NOUNS
        or token in STOPWORD_TOKENS
        for token in tokens
    )


def _ui_feature_seed_from_behavior(question: str, query_rewrite: dict[str, object]) -> str:
    for feature in _behavior_trace_features(question, query_rewrite, limit=3):
        normalized = str(feature or "").strip()
        if normalized and not _is_weak_broad_seed(normalized):
            return normalized
    return ""


def _should_prefer_ui_feature_seed(candidate: str, question: str, intent: dict[str, object], query_rewrite: dict[str, object]) -> bool:
    primary = str(intent.get("primary", "general") or "general")
    if primary not in {"ui_ownership", "feature_exploration"}:
        return False
    normalized = str(candidate or "").strip().lower()
    if not normalized:
        return True
    if _is_weak_broad_seed(normalized):
        return True
    if normalized in {"backend", "frontend", "endpoint", "endpoints", "selector", "page", "overview", "period"}:
        return True
    behavior_seed = _ui_feature_seed_from_behavior(question, query_rewrite)
    return bool(behavior_seed and normalized != behavior_seed.lower() and normalized not in behavior_seed.lower())


def _page_primary_prompt(question_tokens: set[str]) -> bool:
    return bool(question_tokens & {"page", "pages", "screen", "screens", "overview", "landing", "frontend", "view"})


def _is_page_owner_file(normalized_path: str) -> bool:
    return any(part in normalized_path for part in ("/pages/", "/page/", "page.", "landing", "overview"))


def _is_shared_ui_file(normalized_path: str) -> bool:
    return any(part in normalized_path for part in ("/components/", "selector", "/contexts/", "/hooks/", "filter", "period"))


def _is_backend_flow_file(normalized_path: str) -> bool:
    return any(part in normalized_path for part in ("/api/", "/endpoints/", "/controllers/", "/services/"))


def _is_implausible_exploratory_file(normalized_path: str) -> bool:
    return any(part in normalized_path for part in ("test-utils", "/tests/", "/test/", ".test.", ".spec.", "/scripts/", "/script/", "installer", "monitor"))


def _is_noise_reason(reason: object) -> bool:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return False
    return any(part in normalized for part in ("test-utils", "memorymonitor", "memory monitor", "xssprotection", "xss protection"))


def _meaningful_prompt_overlap(question_tokens: set[str], normalized_path: str) -> int:
    ignored = STOPWORD_TOKENS | GENERIC_SEARCH_TERMS | GENERIC_EXPLORATORY_NOUNS | {
        "frontend",
        "backend",
        "page",
        "pages",
        "screen",
        "screens",
        "api",
        "endpoint",
        "endpoints",
        "service",
        "services",
        "code",
        "calls",
        "shared",
        "date",
    }
    prompt_terms = {token for token in question_tokens if len(token) >= 4 and token not in ignored}
    if not prompt_terms:
        return 0
    split_text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized_path)
    path_tokens = {token.lower() for token in re.split(r"[^a-zA-Z0-9]+", split_text) if token}
    return len(prompt_terms & path_tokens)


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
            if _should_prefer_ui_feature_seed(candidate, normalized_question, intent, query_rewrite):
                behavior_seed = _ui_feature_seed_from_behavior(normalized_question, query_rewrite)
                if behavior_seed:
                    return behavior_seed, {
                        "intent": intent,
                        "query_rewrite": query_rewrite,
                        "guardrails": guardrails,
                        "task_source": "behavior_trace_seed",
                        "original_question": normalized_question,
                    }
            if bool(guardrails.get("broad_question")) and source in {"symbol_term", "search_seed"} and _is_weak_broad_seed(candidate):
                exploratory_features = _behavior_trace_features(normalized_question, query_rewrite, limit=3)
                for exploratory in exploratory_features:
                    if not _is_weak_broad_seed(exploratory):
                        return exploratory, {
                            "intent": intent,
                            "query_rewrite": query_rewrite,
                            "guardrails": guardrails,
                            "task_source": "behavior_trace_seed",
                            "original_question": normalized_question,
                        }
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


def should_allow_broad_vector_fallback(search_task: str, query_rewrite: dict[str, object]) -> bool:
    candidate = str(search_task or "").strip()
    if not candidate:
        return False
    route_terms = query_rewrite.get("route_terms", [])
    file_terms = query_rewrite.get("file_terms", [])
    if isinstance(route_terms, list) and candidate in route_terms:
        return True
    if isinstance(file_terms, list) and candidate in file_terms:
        return True
    if "/" in candidate or candidate.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        return True
    if "." in candidate or ":" in candidate:
        return True
    if re.search(r"[a-z][A-Z]", candidate):
        lowered = candidate.lower()
        if lowered in GENERIC_SEARCH_TERMS:
            return False
        parts = [part for part in re.split(r"[^a-zA-Z0-9]+", candidate) if part]
        if len(parts) == 1 and len(candidate) >= 14:
            return True
        if len(parts) >= 2:
            return True
    lowered_tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", candidate.lower()) if token]
    if not lowered_tokens:
        return False
    if all(token in GENERIC_SEARCH_TERMS or token in STOPWORD_TOKENS for token in lowered_tokens):
        return False
    return False


def broad_lexical_search_terms(search_task: str, query_rewrite: dict[str, object], limit: int = 4) -> list[str]:
    terms: list[str] = []

    def token_key(value: str) -> tuple[str, ...]:
        return tuple(token for token in re.split(r"[^a-zA-Z0-9]+", value.lower()) if token)

    def add_term(value: object) -> None:
        candidate = str(value or "").strip()
        if not candidate or candidate in terms:
            return
        lowered_tokens = list(token_key(candidate))
        if lowered_tokens and all(token in GENERIC_SEARCH_TERMS or token in STOPWORD_TOKENS for token in lowered_tokens):
            return
        terms.append(candidate)

    add_term(search_task)
    for field in ("route_terms", "file_terms", "symbol_terms", "search_seeds"):
        values = query_rewrite.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            candidate = str(value or "").strip()
            if not candidate or " " in candidate:
                continue
            if field in {"route_terms", "file_terms"}:
                add_term(candidate)
            elif should_allow_broad_vector_fallback(candidate, query_rewrite):
                add_term(candidate)
            if len(terms) >= limit:
                return terms[:limit]
    if len(terms) < limit:
        for value in list(terms):
            split_variant = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value).strip()
            if split_variant and split_variant != value:
                add_term(split_variant)
            compact_variant = "".join(token_key(value))
            if compact_variant and compact_variant != value.lower():
                add_term(compact_variant)
            if len(terms) >= limit:
                return terms[:limit]
    if len(terms) < limit:
        core_terms = query_rewrite.get("core_terms", [])
        if isinstance(core_terms, list):
            focused_terms = [term for term in core_terms if term not in GENERIC_SEARCH_TERMS and term not in STOPWORD_TOKENS]
            if len(focused_terms) >= 2:
                add_term(" ".join(focused_terms[:2]))
            elif focused_terms:
                add_term(focused_terms[0])
    return terms[:limit]


def cheap_symbol_discovery_terms(search_task: str, query_rewrite: dict[str, object], limit: int = 4) -> list[str]:
    terms = broad_lexical_search_terms(search_task, query_rewrite, limit=limit)
    for value in list(terms):
        split_variant = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value).strip()
        if split_variant and split_variant not in terms:
            terms.append(split_variant)
        if len(terms) >= limit:
            return terms[:limit]
    return terms[:limit]


def alternate_discovery_anchors(
    search_task: str,
    query_rewrite: dict[str, object],
    app_target: str = "",
    limit: int = 2,
) -> list[str]:
    anchors: list[str] = []
    normalized_seed = str(search_task or "").strip().lower()

    def add_anchor(value: object) -> None:
        candidate = str(value or "").strip()
        if not candidate:
            return
        normalized = candidate.lower()
        if normalized == normalized_seed or candidate in anchors:
            return
        tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", normalized) if token]
        if tokens and all(token in GENERIC_SEARCH_TERMS or token in STOPWORD_TOKENS for token in tokens):
            return
        if " " in candidate and not any(marker in candidate for marker in ("/", ".", ":")):
            return
        if not (
            should_allow_broad_vector_fallback(candidate, query_rewrite)
            or "/" in candidate
            or "." in candidate
            or ":" in candidate
            or re.search(r"[a-z][A-Z]", candidate)
            or len(candidate) >= 8
        ):
            return
        anchors.append(candidate)

    for value in [app_target]:
        add_anchor(value)
    for field in ("route_terms", "file_terms", "symbol_terms", "search_seeds"):
        values = query_rewrite.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            add_anchor(value)
            if len(anchors) >= limit:
                return anchors[:limit]
    core_terms = query_rewrite.get("core_terms", [])
    if isinstance(core_terms, list):
        for value in core_terms:
            add_anchor(value)
            if len(anchors) >= limit:
                return anchors[:limit]
    return anchors[:limit]


def cheap_symbol_discovery(
    duckdb_store: DuckDBStore,
    search_task: str,
    query_rewrite: dict[str, object],
    limit: int = 5,
) -> list[dict[str, object]]:
    fetch_symbols = getattr(duckdb_store, "fetch_symbols_for_target", None)
    if not callable(fetch_symbols):
        return []
    matches: list[dict[str, object]] = []
    seen: set[tuple[str, str, object, object]] = set()
    for term in cheap_symbol_discovery_terms(search_task, query_rewrite, limit=max(limit, 4)):
        for symbol in fetch_symbols(term, limit=max(limit * 3, 12)):
            key = (
                str(symbol.get("qualified_name", "") or ""),
                str(symbol.get("file_path", "") or ""),
                symbol.get("start_line"),
                symbol.get("end_line"),
            )
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                {
                    "qualified_name": symbol.get("qualified_name", ""),
                    "name": symbol.get("name", ""),
                    "file_path": symbol.get("file_path", ""),
                    "kind": symbol.get("kind", ""),
                    "start_line": symbol.get("start_line"),
                    "end_line": symbol.get("end_line"),
                    "discovery_term": term,
                }
            )
            if len(matches) >= limit:
                return matches
    return matches


def cheap_ui_symbol_discovery_terms(search_task: str, query_rewrite: dict[str, object], limit: int = 4) -> list[str]:
    terms: list[str] = []

    def add_term(value: object) -> None:
        candidate = str(value or "").strip()
        if not candidate or candidate in terms:
            return
        tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", candidate.lower()) if token]
        if tokens and all(token in GENERIC_SEARCH_TERMS or token in STOPWORD_TOKENS for token in tokens):
            return
        terms.append(candidate)

    split_variant = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(search_task or "")).strip()
    if split_variant and split_variant != search_task:
        add_term(split_variant)
    core_terms = query_rewrite.get("core_terms", [])
    if isinstance(core_terms, list):
        focused = [str(term).strip() for term in core_terms if str(term).strip() and str(term) not in GENERIC_SEARCH_TERMS and str(term) not in STOPWORD_TOKENS]
        if len(focused) >= 2:
            add_term(" ".join(focused[:2]))
        for term in focused:
            add_term(term)
            if len(terms) >= limit:
                return terms[:limit]
    if split_variant:
        add_term(split_variant.replace(" ", ""))
    return terms[:limit]


def cheap_ui_symbol_discovery(
    duckdb_store: DuckDBStore,
    search_task: str,
    query_rewrite: dict[str, object],
    limit: int = 5,
) -> list[dict[str, object]]:
    search_chunks = getattr(duckdb_store, "search_chunks_content", None)
    fetch_symbols_for_file = getattr(duckdb_store, "fetch_symbols_for_file", None)
    if not callable(search_chunks) or not callable(fetch_symbols_for_file):
        return []
    matches: list[dict[str, object]] = []
    seen: set[tuple[str, str, object, object]] = set()
    for term in cheap_ui_symbol_discovery_terms(search_task, query_rewrite, limit=max(limit, 4)):
        chunk_rows = search_chunks(term, limit=max(limit * 2, 8))
        for chunk in chunk_rows:
            file_path = str(chunk.get("file_path", "") or "")
            if not file_path:
                continue
            for symbol in fetch_symbols_for_file(file_path)[:4]:
                key = (
                    str(symbol.get("qualified_name", "") or ""),
                    str(symbol.get("file_path", file_path) or file_path),
                    symbol.get("start_line"),
                    symbol.get("end_line"),
                )
                if key in seen:
                    continue
                seen.add(key)
                matches.append(
                    {
                        "qualified_name": symbol.get("qualified_name", symbol.get("name", "")),
                        "name": symbol.get("name", ""),
                        "file_path": symbol.get("file_path", file_path) or file_path,
                        "kind": symbol.get("kind", ""),
                        "start_line": symbol.get("start_line"),
                        "end_line": symbol.get("end_line"),
                        "discovery_term": term,
                        "discovery_source": "chunk_content",
                    }
                )
                if len(matches) >= limit:
                    return matches
    return matches


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


def _behavior_trace_features(question: str, query_rewrite: dict[str, object], limit: int = 3) -> list[str]:
    features: list[str] = []
    normalized_question = " ".join(str(question or "").split()).strip()
    tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", normalized_question.lower()) if token]
    filtered_tokens = [
        token
        for token in tokens
        if token not in STOPWORD_TOKENS and token not in GENERIC_SEARCH_TERMS and len(token) >= 3
    ]

    def add_feature(value: object) -> None:
        candidate = " ".join(str(value or "").split()).strip(" ,.:;")
        if not candidate or candidate in features:
            return
        features.append(candidate)

    trace_pairs = [
        ("mcp", "repo"),
        ("repo", "selection"),
        ("mcp", "selection"),
        ("indexing", "progress"),
        ("progress", "reporting"),
        ("index", "health"),
        ("health", "status"),
        ("period", "selector"),
        ("financial", "year"),
        ("calendar", "year"),
        ("national", "overview"),
        ("overview", "page"),
        ("landing", "page"),
        ("repo", "selection"),
        ("index", "health"),
    ]
    token_set = set(filtered_tokens)
    for left, right in trace_pairs:
        if left in token_set and right in token_set:
            add_feature(f"{left} {right}")
            if len(features) >= limit:
                return features[:limit]

    for alias_tokens, aliases in BEHAVIOR_TRACE_ALIASES.items():
        if alias_tokens.issubset(token_set):
            for alias in aliases:
                add_feature(alias)
                if len(features) >= limit:
                    return features[:limit]

    if len(filtered_tokens) >= 2:
        for size in (3, 2):
            for index in range(0, max(0, len(filtered_tokens) - size + 1)):
                window = filtered_tokens[index : index + size]
                if not window:
                    continue
                if not set(window) & BEHAVIOR_TRACE_TOKENS and not {"mcp", "repo", "selection", "indexing", "progress", "health", "status"} & set(window):
                    continue
                add_feature(" ".join(window))
                if len(features) >= limit:
                    return features[:limit]

    symbol_terms = query_rewrite.get("symbol_terms", [])
    route_terms = query_rewrite.get("route_terms", [])
    file_terms = query_rewrite.get("file_terms", [])
    if isinstance(symbol_terms, list):
        for value in symbol_terms[:3]:
            candidate = str(value or "").strip()
            if candidate.isalpha() and candidate.islower():
                continue
            add_feature(candidate)
            if len(features) >= limit:
                return features[:limit]
    if isinstance(route_terms, list):
        for value in route_terms[:1]:
            add_feature(value)
            if len(features) >= limit:
                return features[:limit]
    if isinstance(file_terms, list):
        for value in file_terms[:1]:
            add_feature(value)
            if len(features) >= limit:
                return features[:limit]

    if filtered_tokens:
        if len(filtered_tokens) >= 2:
            add_feature(" ".join(filtered_tokens[:2]))
        if len(filtered_tokens) >= 4:
            add_feature(" ".join(filtered_tokens[:4]))
    if normalized_question:
        add_feature(normalized_question)
    return features[:limit]


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
    if _is_exploratory_intent(intent) and bool(diagnostics.get("exploratory_lightweight_path")):
        behavior_features = _behavior_trace_features(normalized_question, query_rewrite, limit=2)
        behavior_summaries: list[dict[str, object]] = []
        warnings.append("Exploratory feature tracing used a lightweight budget to avoid timeouts.")
        for feature_name in behavior_features:
            try:
                feature_payload = feature_context(
                    repo_root,
                    duckdb_store,
                    kuzu_store,
                    feature=feature_name,
                    limit=max(6, limit + 1),
                    lightweight=True,
                )
            except Exception:
                continue
            behavior_summaries.append(_behavior_trace_summary(feature_payload))
        behavior_trace = _merge_behavior_trace_summaries(behavior_summaries, limit=6) if behavior_summaries else {"feature": "", "attempted_features": [], "top_files": [], "top_routes": [], "top_processes": [], "file_kinds": {}, "role_groups": {}, "file_count": 0, "partial": True}
        if behavior_trace.get("top_files") or behavior_trace.get("top_routes") or behavior_trace.get("top_processes"):
            warnings.append("Behavior trace surfaced exploratory candidate files for follow-up.")
        if behavior_trace.get("attempted_features"):
            warnings.append(f"Behavior trace attempted exploratory anchors: {', '.join(behavior_trace.get('attempted_features', [])[:3])}.")
        ranked_files = [
            {
                "file": file_path,
                "score": max(3.0 - (index * 0.35), 1.0),
                "seed_hits": 0,
                "expanded_hits": 0,
                "snippet_hits": 0,
                "app_context": False,
                "reasons": ["behavior trace candidate", "exploratory feature trace surfaced a frontend candidate"] if _is_frontend_file(file_path) else ["behavior trace candidate"],
                "lines": [],
            }
            for index, file_path in enumerate(behavior_trace.get("top_files", [])[:8])
        ]
        architecture = {
            "caller_count": 0,
            "callee_count": 0,
            "top_neighbors": [],
            "top_routes": behavior_trace.get("top_routes", [])[:6] if isinstance(behavior_trace.get("top_routes", []), list) else [],
            "top_processes": behavior_trace.get("top_processes", [])[:6] if isinstance(behavior_trace.get("top_processes", []), list) else [],
            "file_kinds": behavior_trace.get("file_kinds", {}) if isinstance(behavior_trace.get("file_kinds", {}), dict) else {},
            "dependency_counts": {},
            "graph_edge_count": 0,
        }
        exploratory_groups = _exploratory_file_groups(ranked_files, behavior_trace, architecture)
        trace_roles = behavior_trace.get("role_groups", {}) if isinstance(behavior_trace.get("role_groups", {}), dict) else {}
        ordered_paths: list[str] = []
        for source_groups in (trace_roles, exploratory_groups):
            for group_name in ("page_files", "shared_ui_files", "backend_files"):
                group_values = source_groups.get(group_name, []) if isinstance(source_groups, dict) else []
                if isinstance(group_values, list):
                    for file_path in group_values:
                        normalized = str(file_path or "").strip()
                        if normalized and normalized not in ordered_paths:
                            ordered_paths.append(normalized)
        if ordered_paths:
            weighted_ranked_files: list[dict[str, object]] = []
            for index, file_path in enumerate(ordered_paths[:8]):
                reasons = ["behavior trace candidate"]
                if file_path in exploratory_groups.get("page_files", []):
                    reasons.extend(["exploratory role: page owner", "page-owner bias: prompt asks for the owning page first"])
                elif file_path in exploratory_groups.get("shared_ui_files", []):
                    reasons.extend(["exploratory role: shared period state", "secondary-role ordering: shared UI follows the page owner"])
                elif file_path in exploratory_groups.get("backend_files", []):
                    reasons.extend(["exploratory role: backend flow", "secondary-role ordering: backend flow follows page and shared UI"])
                if _is_frontend_file(file_path):
                    reasons.append("exploratory feature trace surfaced a frontend candidate")
                weighted_ranked_files.append(
                    {
                        "file": file_path,
                        "score": max(4.5 - (index * 0.4), 1.0),
                        "seed_hits": 0,
                        "expanded_hits": 0,
                        "snippet_hits": 0,
                        "app_context": False,
                        "reasons": reasons,
                        "lines": [],
                    }
                )
            ranked_files = weighted_ranked_files
        evidence = _evidence_items(
            [],
            [],
            [],
            {"compact_summary": {"top_neighbors": []}},
            {"compact_summary": {"top_files": behavior_trace.get("top_files", [])[:6] if isinstance(behavior_trace.get("top_files", []), list) else []}},
            ranked_files=ranked_files,
            intent=intent,
        )
        top_target = str(exploratory_groups.get("page_files", [behavior_trace.get("feature", "")])[:1][0] if exploratory_groups.get("page_files") else behavior_trace.get("feature", "") or normalized_question)
        graph_signal = {"frontend_graph_hit_count": 0, "frontend_graph_files": [], "top_frontend_ranked_files": [item.get("file", "") for item in ranked_files[:3]], "frontend_file_count": 0, "graph_edge_count": 0, "has_indirect_frontend_path": False}
        answer, confidence, open_questions = _synthesize_answer(
            normalized_question,
            top_target,
            ranked_files,
            evidence,
            diagnostics,
            architecture,
            [],
            [],
            intent,
            graph_signal,
            exploratory_groups=exploratory_groups,
        )
        next_tools = [{"tool": "feature_context", "target": behavior_trace.get("feature") or normalized_question, "why": "Trace exploratory feature or behavior context across files, routes, and processes."}]
        if ranked_files:
            next_tools.append({"tool": "get_source_context", "why": "Read exact source snippets for the strongest candidate file or symbol."})
        return {
            "question": normalized_question,
            "target": top_target,
            "intent": intent,
            "query_rewrite": query_rewrite,
            "seed_target": search_task,
            "search_task": {"task": search_task, "source": search_plan.get("task_source", "question")},
            "guardrails": guardrails,
            "app_context_target": {"target": behavior_trace.get("feature", "") or search_task, "source": "behavior_trace_feature"},
            "investigation_passes": {"attempted_seeds": [search_task], "retry_used": False, "retry_reason": "", "alternate_discovery_anchors": []},
            "warnings": warnings,
            "answer": answer,
            "confidence": confidence,
            "evidence": evidence,
            "evidence_breakdown": {"seed_hits": [], "expanded_hits": [], "source_snippets": []},
            "retrieval_diagnostics": diagnostics,
            "ranked_files": ranked_files,
            "architecture_summary": architecture,
            "graph_signal": graph_signal,
            "data_flow_summary": [],
            "guidance_summary": {"ambiguous": True, "weak_primary": False, "evidence_count": len(evidence), "has_graph_context": False, "has_routes": bool(architecture["top_routes"]), "has_processes": bool(architecture["top_processes"]), "intent": intent, "top_file": ranked_files[0]["file"] if ranked_files else "", "top_file_reasons": ranked_files[0]["reasons"][:3] if ranked_files else [], "retrieval_signal_strength": {}},
            "exploratory_groups": exploratory_groups,
            "behavior_trace": behavior_trace,
            "change_guidance": {"related_files": [item.get("file", "") for item in ranked_files[:6]], "recommended_tests": [], "likely_impact_targets": [], "test_count": 0},
            "discovered_symbols": [],
            "open_questions": open_questions,
            "next_tools": next_tools,
            "answer_outline": [
                f"Exploratory page files: {', '.join(exploratory_groups.get('page_files', [])[:3])}" if exploratory_groups.get("page_files") else "Exploratory page files: none",
                f"Exploratory shared UI files: {', '.join(exploratory_groups.get('shared_ui_files', [])[:3])}" if exploratory_groups.get("shared_ui_files") else "Exploratory shared UI files: none",
                f"Exploratory backend files: {', '.join(exploratory_groups.get('backend_files', [])[:3])}" if exploratory_groups.get("backend_files") else "Exploratory backend files: none",
            ],
            "next_steps": ["Open the top exploratory files first to confirm the owning page, shared period state, and backend flow."],
            "compact_summary": {
                "target": top_target,
                "question": normalized_question,
                "confidence": confidence,
                "intent": intent,
                "query_rewrite": query_rewrite,
                "seed_target": search_task,
                "search_task": {"task": search_task, "source": search_plan.get("task_source", "question")},
                "guardrails": guardrails,
                "warnings": warnings,
                "top_files": [item.get("file", "") for item in ranked_files[:8]],
                "top_symbols": [],
                "snippet_count": 0,
                "evidence_count": len(evidence),
                "seed_hit_count": 0,
                "expanded_hit_count": 0,
                "behavior_trace": behavior_trace,
                "exploratory_groups": exploratory_groups,
                "status": "partial",
                "next_tools": next_tools,
                "partial": True,
            },
        }
    seed_hits, expanded_hits = _classify_search_hits(search_hits)
    discovered_symbols: list[dict[str, object]] = []
    alternate_anchors: list[str] = []
    if bool(guardrails.get("broad_question")) and not search_hits:
        discovered_symbols = cheap_symbol_discovery(duckdb_store, search_task, query_rewrite, limit=5)
        if not discovered_symbols:
            alternate_anchors = alternate_discovery_anchors(search_task, query_rewrite, app_target=str(search_task or ""), limit=2)
            if alternate_anchors:
                seen_keys = {
                    (
                        str(symbol.get("qualified_name", "") or ""),
                        str(symbol.get("file_path", "") or ""),
                        symbol.get("start_line"),
                        symbol.get("end_line"),
                    )
                    for symbol in discovered_symbols
                }
                for anchor in alternate_anchors:
                    remaining = max(1, 5 - len(discovered_symbols))
                    for symbol in cheap_symbol_discovery(duckdb_store, anchor, query_rewrite, limit=remaining):
                        key = (
                            str(symbol.get("qualified_name", "") or ""),
                            str(symbol.get("file_path", "") or ""),
                            symbol.get("start_line"),
                            symbol.get("end_line"),
                        )
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        discovered_symbols.append(symbol)
                        if len(discovered_symbols) >= 5:
                            break
                    if len(discovered_symbols) >= 5:
                        break
        if not discovered_symbols:
            discovered_symbols = cheap_ui_symbol_discovery(duckdb_store, search_task, query_rewrite, limit=5)
        if discovered_symbols:
            warnings.append("Broad search found nearby symbols via cheap lexical discovery.")
        if alternate_anchors:
            warnings.append(f"Broad search also tried alternate anchors: {', '.join(alternate_anchors)}.")
        if discovered_symbols and any(str(item.get("discovery_source", "")) == "chunk_content" for item in discovered_symbols):
            warnings.append("Weak UI-like target was expanded through nearby chunk text to surface candidate symbols.")
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
            if narrowed_target == seed_target:
                resolved_target = narrowed_target
            else:
                resolution = resolve_tool_target(duckdb_store, repo_root, target=narrowed_target, limit=limit)
                resolved_target = str(resolution.get("resolved_target") or narrowed_target)
                if _is_generic_target(resolved_target):
                    resolved_target = narrowed_target
            warnings.append(f"Generic target resolution was replaced with narrowed term '{narrowed_target}'.")
    search_hits = _prioritize_search_hits(search_hits, seed_target, resolved_target)
    seed_hits, expanded_hits = _classify_search_hits(search_hits)
    app = app_context(repo_root, duckdb_store, kuzu_store, target=app_target, limit=6)
    source_context = get_source_context(duckdb_store, resolved_target, limit=3, repo_root=repo_root)
    unified = get_unified_context(duckdb_store, kuzu_store, resolved_target, max_matches=3, neighborhood_depth=1)
    behavior_trace = {"feature": "", "attempted_features": [], "top_files": [], "top_routes": [], "top_processes": [], "file_kinds": {}, "role_groups": {}, "file_count": 0, "partial": False}
    if _should_enrich_behavior_trace(normalized_question, intent, guardrails):
        try:
            exploratory_intent = _is_exploratory_intent(intent)
            lightweight_behavior = bool(exploratory_intent and (guardrails.get("broad_question") or len(_question_tokens(normalized_question)) >= 8))
            broad_behavior_budget = 2 if lightweight_behavior else 3
            behavior_features = _behavior_trace_features(normalized_question, query_rewrite, limit=broad_behavior_budget)
            behavior_summaries = [
                _behavior_trace_summary(
                    feature_context(
                        repo_root,
                        duckdb_store,
                        kuzu_store,
                        feature=feature,
                        limit=4 if lightweight_behavior else 6,
                        lightweight=lightweight_behavior,
                    )
                )
                for feature in behavior_features
            ]
            behavior_trace = _merge_behavior_trace_summaries(behavior_summaries, limit=6)
            if lightweight_behavior:
                behavior_trace["partial"] = True
                warnings.append("Exploratory feature tracing used a lightweight budget to avoid timeouts.")
        except Exception:
            behavior_trace = {"feature": "", "attempted_features": [], "top_files": [], "top_routes": [], "top_processes": [], "file_kinds": {}, "role_groups": {}, "file_count": 0, "partial": False}
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
    ranked_files = _file_relevance(
        search_hits,
        snippets_list,
        app,
        behavior_trace=behavior_trace,
        question=normalized_question,
        intent=intent,
        limit=evidence_limit,
    )
    key_files = [str(item.get("file", "")) for item in ranked_files if str(item.get("file", "")).strip()]
    architecture = _architecture_summary(unified, app)
    exploratory_groups = _exploratory_file_groups(ranked_files, behavior_trace, architecture)
    graph_signal = _graph_frontend_signal(search_hits, ranked_files, architecture)
    data_flow_points = _data_flow_summary(architecture)
    evidence = _evidence_items(
        seed_hits,
        expanded_hits,
        snippets_list,
        unified,
        app,
        ranked_files=ranked_files,
        intent=intent,
    )
    if len(evidence) > evidence_limit:
        evidence = evidence[:evidence_limit]
        warnings.append("Evidence was truncated to keep the result compact.")
    answer, confidence, open_questions = _synthesize_answer(
        normalized_question,
        resolved_target,
        ranked_files,
        evidence,
        diagnostics,
        architecture,
        seed_hits,
        expanded_hits,
        intent,
        graph_signal,
        exploratory_groups=exploratory_groups,
    )
    if not evidence and discovered_symbols:
        discovered_names = [
            str(item.get("qualified_name") or item.get("name") or "").strip()
            for item in discovered_symbols
            if str(item.get("qualified_name") or item.get("name") or "").strip()
        ][:3]
        if discovered_names:
            answer += f" Cheap symbol discovery found nearby candidates: {', '.join(discovered_names)}."
        open_questions = ["No direct evidence was found, but nearby symbols may help narrow the follow-up."]
    if behavior_trace.get("top_files"):
        trace_files = ", ".join(str(path) for path in behavior_trace.get("top_files", [])[:3])
        answer += f" Feature trace candidates include {trace_files}."
        if "Behavior trace surfaced exploratory candidate files for follow-up." not in warnings:
            warnings.append("Behavior trace surfaced exploratory candidate files for follow-up.")
    if behavior_trace.get("attempted_features"):
        attempted = ", ".join(str(item) for item in behavior_trace.get("attempted_features", [])[:3])
        warnings.append(f"Behavior trace attempted exploratory anchors: {attempted}.")
    profile = _guidance_profile(resolution, diagnostics, seed_hits, expanded_hits, snippets_list, ranked_files, architecture, intent, graph_signal)
    next_steps = _guidance_next_steps(profile, resolved_target, normalized_question)
    if unified_summary.get("caller_count") or unified_summary.get("callee_count"):
        if "Review callers/callees from unified_context." not in next_steps:
            next_steps.append("Review callers/callees from unified_context.")
    next_tools = _guidance_next_tools(profile, resolved_target, normalized_question)
    if behavior_trace.get("top_files") or behavior_trace.get("top_routes") or behavior_trace.get("top_processes"):
        feature_hint_target = str(behavior_trace.get("feature") or normalized_question)
        feature_hint = {"tool": "feature_context", "target": feature_hint_target, "why": "Trace exploratory feature or behavior context across files, routes, and processes."}
        if feature_hint not in next_tools:
            next_tools.insert(0, feature_hint)
    guidance_summary = _guidance_summary(profile)
    change_guidance = _change_guidance(duckdb_store, resolved_target, ranked_files, unified_summary, app_summary)

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
            "alternate_discovery_anchors": alternate_anchors,
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
        "exploratory_groups": exploratory_groups,
        "behavior_trace": behavior_trace,
        "change_guidance": change_guidance,
        "discovered_symbols": discovered_symbols,
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
            f"Cheap symbol candidates: {len(discovered_symbols)}",
            f"Alternate anchors tried: {', '.join(alternate_anchors)}" if alternate_anchors else "Alternate anchors tried: none",
            f"Suggested tests: {change_guidance.get('test_count', 0)}",
            f"Behavior trace files: {len(behavior_trace.get('top_files', []))}",
            f"Behavior anchors tried: {', '.join(behavior_trace.get('attempted_features', [])[:3])}" if behavior_trace.get("attempted_features") else "Behavior anchors tried: none",
            f"Exploratory page files: {', '.join(exploratory_groups.get('page_files', [])[:2])}" if exploratory_groups.get("page_files") else "Exploratory page files: none",
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
                "alternate_discovery_anchors": alternate_anchors,
            },
            "warnings": warnings,
            "top_files": key_files[:8],
            "top_file_reasons": {str(item.get("file", "")): item.get("reasons", [])[:3] for item in ranked_files[:5]},
            "top_symbols": _unique_strings([item.get("target") for item in search_hits[:5] if item.get("target")]),
            "discovered_symbols": discovered_symbols[:5],
            "snippet_count": len(snippets_list),
            "evidence_count": len(evidence),
            "seed_hit_count": len(seed_hits),
            "expanded_hit_count": len(expanded_hits),
            "guidance": guidance_summary,
            "behavior_trace": behavior_trace,
            "exploratory_groups": exploratory_groups,
            "change_guidance": change_guidance,
            "app_files": app_summary.get("top_files", []),
            "top_neighbors": unified_summary.get("top_neighbors", []),
            "graph_signal": graph_signal,
        },
    }
