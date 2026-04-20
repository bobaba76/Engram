from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

APP_PATH_HINTS = ("frontend", "backend", "src", "app", "api", "components", "pages", "routes", "services", "finance_mvp")
PREFERRED_APP_SUBTREES = (
    "frontend/",
    "frontend-v2/",
    "backend/",
    "src/",
    "app/",
    "api.py",
    "finance_mvp/",
)
INFRA_PATH_HINTS = (
    "mcp_server/",
    "scripts/",
    "storage/",
    "indexing/",
    "reviewers/",
    "app/coordinator.py",
    "run_mcp.py",
)
FRONTEND_TOKENS = {"component", "page", "button", "drawer", "modal", "frontend", "ui", "screen", "view", "settings", "react", "hook"}
BACKEND_TOKENS = {"backend", "endpoint", "api", "service", "repository", "store", "database", "db", "ingest", "ingestion", "router"}


def _normalize_path(path: object) -> str:
    return str(path or "").replace("\\", "/").lower()


def _query_tokens(query: str) -> set[str]:
    return {token for token in query.lower().replace("-", " ").replace("_", " ").split() if token}


def classify_confidence(score: float) -> str:
    if score >= 0.9:
        return "high"
    if score >= 0.72:
        return "medium"
    return "low"


def summarize_relevance(reasons: list[str]) -> str:
    if not reasons:
        return "semantic or fuzzy match"
    unique: list[str] = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return ", ".join(unique[:3])


def _line_range(result: dict[str, Any]) -> list[int | None]:
    return [result.get("start_line"), result.get("end_line")]


def compact_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": result.get("qualified_name") or result.get("symbol_name") or result.get("file_path") or "",
        "file": result.get("file_path", ""),
        "lines": _line_range(result),
        "confidence": result.get("confidence", "low"),
        "why_relevant": result.get("relevance", "semantic or fuzzy match"),
        "score": result.get("score", 0.0),
    }


def score_path_relevance(query: str, file_path: object) -> tuple[float, list[str]]:
    normalized_path = _normalize_path(file_path)
    tokens = _query_tokens(query)
    score = 0.0
    reasons: list[str] = []
    if not normalized_path:
        return score, reasons
    if any(normalized_path.startswith(prefix) or prefix in normalized_path for prefix in PREFERRED_APP_SUBTREES):
        score += 0.28
        reasons.append("preferred app subtree")
    if any(hint in normalized_path for hint in APP_PATH_HINTS):
        score += 0.12
        reasons.append("app-code path")
    if any(hint in normalized_path for hint in INFRA_PATH_HINTS):
        score -= 0.35
        reasons.append("tooling/internal path")
    if FRONTEND_TOKENS & tokens:
        if normalized_path.endswith((".tsx", ".jsx")):
            score += 0.3
            reasons.append("frontend file type boost")
        if "/frontend" in normalized_path or "/components" in normalized_path or "/pages" in normalized_path or "/ui" in normalized_path:
            score += 0.24
            reasons.append("frontend path boost")
    if BACKEND_TOKENS & tokens:
        if normalized_path.endswith(".py"):
            score += 0.26
            reasons.append("python/backend file boost")
        if "/backend" in normalized_path or "/api" in normalized_path or "/services" in normalized_path or normalized_path.endswith("api.py"):
            score += 0.22
            reasons.append("backend path boost")
    path_name = normalized_path.rsplit("/", 1)[-1]
    query_lower = query.lower()
    if path_name and path_name == query_lower:
        score += 0.6
        reasons.append("exact filename match")
    elif path_name and path_name in query_lower:
        score += 0.3
        reasons.append("filename mentioned in query")
    return score, reasons


def score_symbol_relevance(query: str, name: object, qualified_name: object, file_path: object, kind: object = "") -> tuple[float, list[str]]:
    query_lower = query.lower().strip()
    name_text = str(name or "")
    qualified_text = str(qualified_name or "")
    haystack = f"{name_text} {qualified_text}".lower().strip()
    score = 0.0
    reasons: list[str] = []
    if not haystack:
        return score, reasons
    if query_lower == name_text.lower() or query_lower == qualified_text.lower():
        score += 1.0
        reasons.append("exact symbol match")
    elif query_lower and query_lower in haystack:
        score += 0.72
        reasons.append("direct symbol match")
    if name_text and query_lower and name_text.lower().startswith(query_lower):
        score += 0.24
        reasons.append("symbol prefix match")
    fuzzy_score = SequenceMatcher(None, query_lower, haystack).ratio() if query_lower else 0.0
    score += fuzzy_score * 0.35
    if fuzzy_score >= 0.75:
        reasons.append("strong fuzzy symbol match")
    normalized_kind = str(kind or "").lower()
    if normalized_kind in {"function", "class", "method", "interface", "hook", "component"}:
        score += 0.05
    if query_lower.startswith("use") and str(name_text).startswith("use"):
        score += 0.16
        reasons.append("hook naming match")
    if FRONTEND_TOKENS & _query_tokens(query) and normalized_kind in {"component", "interface", "function"}:
        score += 0.08
    path_score, path_reasons = score_path_relevance(query, file_path)
    score += path_score
    reasons.extend(path_reasons)
    return score, reasons


def rerank_search_results(task: str, results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    reranked: list[dict[str, Any]] = []
    for result in results:
        base_score = float(result.get("_distance", 0.0) or 0.0)
        file_path = result.get("file_path", "")
        symbol_name = result.get("symbol_name", "")
        qualified_name = result.get("qualified_name", symbol_name)
        path_score, path_reasons = score_path_relevance(task, file_path)
        symbol_score, symbol_reasons = score_symbol_relevance(task, symbol_name, qualified_name, file_path)
        final_score = base_score + path_score + (symbol_score * 0.45)
        reranked.append(
            {
                **result,
                "score": round(final_score, 4),
                "confidence": classify_confidence(final_score),
                "relevance": summarize_relevance(path_reasons + symbol_reasons),
            }
        )
    reranked.sort(key=lambda item: (item.get("score", 0.0), item.get("file_path", "")), reverse=True)
    return reranked[:limit]
