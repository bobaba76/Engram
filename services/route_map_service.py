from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore


BACKEND_ROUTE_DECORATOR_PATTERN = re.compile(
    r"@(?P<router>[A-Za-z_][A-Za-z0-9_]*)\.(?P<method>get|post|put|delete|patch)\(\s*['\"](?P<route>[^'\"]+)['\"]",
    re.IGNORECASE,
)
BACKEND_HANDLER_PATTERN = re.compile(r"def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(")
BACKEND_RESPONSE_KEY_PATTERN = re.compile(r"['\"](?P<key>[A-Za-z_][A-Za-z0-9_]*)['\"]\s*:")
FRONTEND_ROUTE_USAGE_PATTERN = re.compile(
    r"(?:apiClient\.(?:get|post|put|delete|patch)|fetch)\(\s*[`'\"](?P<route>/[^`'\"]+)[`'\"]",
    re.IGNORECASE,
)
FRONTEND_ACCESS_KEY_PATTERN = re.compile(r"\.data\.(?P<key>[A-Za-z_][A-Za-z0-9_]*)|\.response\.(?P<response_key>[A-Za-z_][A-Za-z0-9_]*)")
NESTED_ACCESS_PATTERN = re.compile(r"\.data\.(?P<path>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
JSON_RESPONSE_PATTERN = re.compile(r"json\((?P<body>\{[\s\S]{0,2000}?\})\)", re.IGNORECASE)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _iter_candidate_files(repo_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for suffix in ("*.py", "*.ts", "*.tsx", "*.js", "*.jsx"):
        candidates.extend(repo_root.rglob(suffix))
    return candidates


def _response_keys(snippet: str) -> list[str]:
    keys = {match.group("key") for match in BACKEND_RESPONSE_KEY_PATTERN.finditer(snippet) if match.group("key")}
    return sorted(keys)[:30]


def _consumer_keys(snippet: str) -> tuple[list[str], list[str]]:
    flat = {
        access.group("key") or access.group("response_key")
        for access in FRONTEND_ACCESS_KEY_PATTERN.finditer(snippet)
        if access.group("key") or access.group("response_key")
    }
    nested = {access.group("path") for access in NESTED_ACCESS_PATTERN.finditer(snippet) if access.group("path")}
    return sorted(flat)[:30], sorted(nested)[:20]


def route_map(repo_root: Path, duckdb_store: DuckDBStore, route: str = "") -> dict[str, object]:
    normalized_route = str(route or "").strip()
    handlers: list[dict[str, object]] = []
    consumers: list[dict[str, object]] = []
    for path in _iter_candidate_files(repo_root):
        relative_path = str(path.relative_to(repo_root)).replace("\\", "/")
        source = _read_text(path)
        if not source:
            continue
        if path.suffix.lower() == ".py":
            for match in BACKEND_ROUTE_DECORATOR_PATTERN.finditer(source):
                found_route = match.group("route")
                if normalized_route and found_route != normalized_route:
                    continue
                after = source[match.end():]
                handler_match = BACKEND_HANDLER_PATTERN.search(after)
                handler_name = handler_match.group("name") if handler_match is not None else ""
                json_match = JSON_RESPONSE_PATTERN.search(after[:2400])
                response_source = json_match.group("body") if json_match is not None else after[:1600]
                response_keys = _response_keys(response_source)
                handlers.append(
                    {
                        "route": found_route,
                        "method": match.group("method").upper(),
                        "router": match.group("router"),
                        "handler": handler_name,
                        "file_path": relative_path,
                        "response_keys": response_keys[:20],
                    }
                )
        else:
            for match in FRONTEND_ROUTE_USAGE_PATTERN.finditer(source):
                found_route = match.group("route")
                if normalized_route and found_route != normalized_route:
                    continue
                symbol_names = [symbol.get("qualified_name", "") for symbol in duckdb_store.fetch_symbols_for_file(relative_path)[:6]]
                snippet = source[max(0, match.start() - 300):match.start() + 600]
                accessed_keys, nested_accesses = _consumer_keys(snippet)
                consumers.append(
                    {
                        "route": found_route,
                        "file_path": relative_path,
                        "symbols": [name for name in symbol_names if name],
                        "accessed_keys": accessed_keys[:20],
                        "nested_accesses": nested_accesses,
                    }
                )
    route_rows: list[dict[str, object]] = []
    all_routes = sorted({item["route"] for item in handlers} | {item["route"] for item in consumers})
    for found_route in all_routes:
        route_rows.append(
            {
                "route": found_route,
                "handlers": [item for item in handlers if item["route"] == found_route],
                "consumers": [item for item in consumers if item["route"] == found_route],
            }
        )
    return {
        "repo_root": str(repo_root.resolve()),
        "route": normalized_route,
        "routes": route_rows,
        "total": len(route_rows),
        "compact_summary": {
            "target": normalized_route or str(repo_root.resolve()),
            "total": len(route_rows),
            "top_routes": [item["route"] for item in route_rows[:8]],
        },
    }
