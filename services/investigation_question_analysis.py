"""Question analysis — intent classification, query rewrite, guardrails, search task planning."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from services.investigation_constants import (
    BEHAVIOR_OWNER_HINTS,
    BEHAVIOR_TRACE_ALIASES,
    BEHAVIOR_TRACE_TOKENS,
    EXPLORATION_TOKENS,
    FLOW_TOKENS,
    GENERIC_EXPLORATORY_NOUNS,
    GENERIC_SEARCH_TERMS,
    IMPACT_TOKENS,
    IMPERATIVE_SEED_TOKENS,
    LOCATION_TOKENS,
    STOPWORD_TOKENS,
    TEST_TOKENS,
    API_TOKENS,
    BUG_TOKENS,
    UI_TOKENS,
    WEAK_BROAD_SEED_TERMS,
)

if TYPE_CHECKING:
    pass


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
