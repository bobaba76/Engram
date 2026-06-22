"""Constants for investigation service — token sets, stopwords, behavior trace config."""
from __future__ import annotations

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
