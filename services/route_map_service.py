from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from config.settings import DEFAULT_SCAN_EXCLUDED_DIRS

logger = logging.getLogger(__name__)
from indexing.scanner import scan_repo
from services.route_parsing import BACKEND_HANDLER_PATTERN, JSON_RESPONSE_PATTERN, consumer_keys, csharp_model_shapes, enclosing_function_name, frontend_route_usages, function_call_pattern, iter_backend_route_decorators, iter_backend_route_mappings, iter_csharp_route_handlers, iter_express_route_handlers, iter_nestjs_route_handlers, iter_spring_route_handlers, nested_response_keys, normalize_route, pydantic_model_shapes, response_keys, response_model_name, returned_payload_source, route_matches

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        logger.debug("route_map: failed to read file %s", path)
        return ""


def _iter_candidate_files(repo_root: Path) -> list[Path]:
    return [
        repo_root / record.path
        for record in scan_repo(repo_root, excluded_dirs=DEFAULT_SCAN_EXCLUDED_DIRS)
        if Path(record.path).suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx", ".cs"}
    ]


def _iter_indexed_candidate_files(repo_root: Path, duckdb_store: DuckDBStore) -> list[Path]:
    files_repo = getattr(duckdb_store, "files", None)
    fetch_all = getattr(files_repo, "fetch_all", None)
    if not callable(fetch_all):
        return _iter_candidate_files(repo_root)
    candidates: list[Path] = []
    for row in fetch_all():
        relative_path = str(row.get("path", "") or "").strip()
        if not relative_path:
            continue
        candidate = (repo_root / relative_path).resolve()
        try:
            candidate.relative_to(repo_root.resolve())
        except ValueError:
            continue
        if candidate.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".jsx", ".cs", ".java"}:
            continue
        if candidate.exists() and candidate.is_file():
            candidates.append(candidate)
    return candidates or _iter_candidate_files(repo_root)


def _symbol_names(duckdb_store: DuckDBStore, relative_path: str) -> list[str]:
    return [
        name
        for name in [symbol.get("qualified_name", "") for symbol in duckdb_store.fetch_symbols_for_file(relative_path)[:6]]
        if name
    ]


def _unique(values: list[object], limit: int = 8) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def _is_test_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    return normalized.startswith("tests/") or "/tests/" in normalized or name.startswith("test_") or name.endswith(".test.tsx") or name.endswith(".test.ts")


def _is_backend_script_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    return (
        normalized.startswith(("backend/", "server/", "api/"))
        or "/backend/" in normalized
        or "/server/" in normalized
        or "/api/" in normalized
        or name in {"server.js", "server.ts", "app.js", "app.ts", "routes.js", "routes.ts"}
    )


def _backend_handlers(source: str, relative_path: str, requested_route: str) -> list[dict[str, object]]:
    handlers: list[dict[str, object]] = []
    model_shapes = pydantic_model_shapes(source)
    route_entries = [*iter_backend_route_decorators(source), *iter_backend_route_mappings(source)]
    for decorator in route_entries:
        found_route = str(decorator.get("route", "") or "")
        if not route_matches(found_route, requested_route):
            continue
        handler_name = str(decorator.get("handler", "") or "")
        if handler_name:
            handler_match = re.search(rf"(?:async\s+)?def\s+{re.escape(handler_name)}\s*\(", source)
            after = source[handler_match.start():] if handler_match is not None else source[int(decorator.get("end", 0) or 0):]
        else:
            after = source[int(decorator.get("end", 0) or 0):]
            handler_match = BACKEND_HANDLER_PATTERN.search(after)
            handler_name = handler_match.group("name") if handler_match is not None else ""
        json_match = JSON_RESPONSE_PATTERN.search(after[:2400])
        response_source = json_match.group("body") if json_match is not None else returned_payload_source(after[:2400])
        nested = nested_response_keys(response_source)
        model_name = response_model_name(str(decorator.get("args", "") or ""))
        detected_response_keys = response_keys(response_source)[:20]
        if model_name and model_name in model_shapes:
            model_shape = model_shapes[model_name]
            detected_response_keys = sorted(set(detected_response_keys) | set(model_shape.get("fields", [])))[:20]
            model_nested = model_shape.get("nested", {})
            if isinstance(model_nested, dict):
                for key, values in model_nested.items():
                    nested.setdefault(str(key), [])
                    nested[str(key)].extend(str(value) for value in values if value)
        handlers.append(
            {
                "route": found_route,
                "normalized_route": normalize_route(found_route),
                "method": str(decorator.get("method", "") or "").upper(),
                "router": decorator.get("router", ""),
                "handler": handler_name,
                "file_path": relative_path,
                "response_model": model_name,
                "response_keys": detected_response_keys,
                "nested_response_keys": {key: values[:20] for key, values in nested.items()},
            }
        )
    return handlers


def _express_handlers(source: str, relative_path: str, requested_route: str) -> list[dict[str, object]]:
    handlers: list[dict[str, object]] = []
    for entry in iter_express_route_handlers(source):
        found_route = str(entry.get("route", "") or "")
        if not route_matches(found_route, requested_route):
            continue
        handler_name = str(entry.get("handler", "") or "")
        if handler_name:
            handler_match = re.search(
                rf"(?:async\s+)?function\s+{re.escape(handler_name)}\s*\(|(?:const|let|var)\s+{re.escape(handler_name)}\s*=",
                source,
            )
            after = source[handler_match.start():] if handler_match is not None else source[int(entry.get("end", 0) or 0):]
        else:
            after = source[int(entry.get("end", 0) or 0):]
        json_match = JSON_RESPONSE_PATTERN.search(after[:2400])
        response_source = json_match.group("body") if json_match is not None else after[:2400]
        handlers.append(
            {
                "route": found_route,
                "normalized_route": normalize_route(found_route),
                "method": str(entry.get("method", "") or "").upper(),
                "router": entry.get("router", ""),
                "handler": handler_name,
                "file_path": relative_path,
                "response_model": "",
                "response_keys": response_keys(response_source)[:20],
                "nested_response_keys": nested_response_keys(response_source),
            }
        )
    return handlers


def _decorated_js_backend_handlers(source: str, relative_path: str, requested_route: str) -> list[dict[str, object]]:
    handlers: list[dict[str, object]] = []
    for entry in iter_nestjs_route_handlers(source):
        found_route = str(entry.get("route", "") or "")
        if not route_matches(found_route, requested_route):
            continue
        handler_name = str(entry.get("handler", "") or "")
        handler_match = re.search(rf"\b{re.escape(handler_name)}\s*\(", source) if handler_name else None
        after = source[handler_match.start():] if handler_match is not None else source[int(entry.get("end", 0) or 0):]
        json_match = JSON_RESPONSE_PATTERN.search(after[:2400])
        response_source = json_match.group("body") if json_match is not None else after[:2400]
        handlers.append(
            {
                "route": found_route,
                "normalized_route": normalize_route(found_route),
                "method": str(entry.get("method", "") or "").upper(),
                "router": entry.get("router", ""),
                "handler": handler_name,
                "file_path": relative_path,
                "response_model": "",
                "response_keys": response_keys(response_source)[:20],
                "nested_response_keys": nested_response_keys(response_source),
                "framework": entry.get("framework", "nestjs_controller"),
            }
        )
    return handlers


def _spring_handlers(source: str, relative_path: str, requested_route: str) -> list[dict[str, object]]:
    handlers: list[dict[str, object]] = []
    for entry in iter_spring_route_handlers(source):
        found_route = str(entry.get("route", "") or "")
        if not route_matches(found_route, requested_route):
            continue
        handlers.append(
            {
                "route": found_route,
                "normalized_route": normalize_route(found_route),
                "method": str(entry.get("method", "") or "").upper(),
                "router": entry.get("router", ""),
                "handler": entry.get("handler", ""),
                "file_path": relative_path,
                "response_model": "",
                "response_keys": [],
                "nested_response_keys": {},
                "framework": entry.get("framework", "spring_mvc"),
            }
        )
    return handlers


def _csharp_handlers(source: str, relative_path: str, requested_route: str) -> list[dict[str, object]]:
    handlers: list[dict[str, object]] = []
    model_shapes = csharp_model_shapes(source)
    for entry in iter_csharp_route_handlers(source):
        found_route = str(entry.get("route", "") or "")
        if not route_matches(found_route, requested_route):
            continue
        handler_name = str(entry.get("handler", "") or "")
        handler_match = re.search(rf"\b{re.escape(handler_name)}\s*\(", source) if handler_name else None
        after = source[handler_match.start():] if handler_match is not None else source[int(entry.get("end", 0) or 0):]
        json_match = JSON_RESPONSE_PATTERN.search(after[:2400])
        response_source = json_match.group("body") if json_match is not None else after[:2400]
        model_name = str(entry.get("response_model", "") or "")
        detected_response_keys = response_keys(response_source)[:20]
        nested = nested_response_keys(response_source)
        if model_name and model_name in model_shapes:
            model_shape = model_shapes[model_name]
            detected_response_keys = sorted(set(detected_response_keys) | set(model_shape.get("fields", [])))[:20]
            model_nested = model_shape.get("nested", {})
            if isinstance(model_nested, dict):
                for key, values in model_nested.items():
                    nested.setdefault(str(key), [])
                    nested[str(key)].extend(str(value) for value in values if value)
        handlers.append(
            {
                "route": found_route,
                "normalized_route": normalize_route(found_route),
                "method": str(entry.get("method", "") or "").upper(),
                "router": entry.get("router", ""),
                "handler": handler_name,
                "file_path": relative_path,
                "response_model": model_name,
                "response_keys": detected_response_keys,
                "nested_response_keys": {key: values[:20] for key, values in nested.items()},
                "framework": entry.get("framework", "aspnet"),
            }
        )
    return handlers


def _direct_frontend_consumers(source: str, relative_path: str, requested_route: str, duckdb_store: DuckDBStore) -> tuple[list[dict[str, object]], dict[str, str]]:
    consumers: list[dict[str, object]] = []
    wrapper_routes: dict[str, str] = {}
    language = "tsx" if Path(relative_path).suffix.lower() in {".tsx", ".jsx"} else "typescript"
    for usage in frontend_route_usages(source, language=language):
        found_route = str(usage.get("route", "") or "")
        if not route_matches(found_route, requested_route):
            continue
        start = int(usage.get("start", 0) or 0)
        snippet = source[max(0, start - 500):start + 1800]
        accessed_keys, nested_accesses = consumer_keys(snippet)
        function_name = enclosing_function_name(source, start)
        normalized_found_route = normalize_route(found_route)
        if function_name:
            wrapper_routes[function_name] = normalized_found_route
        consumers.append(
            {
                "route": found_route,
                "normalized_route": normalized_found_route,
                "method": str(usage.get("method") or "fetch").upper(),
                "file_path": relative_path,
                "function": function_name,
                "consumer_type": "direct_fetch",
                "parser": usage.get("parser", ""),
                "symbols": _symbol_names(duckdb_store, relative_path),
                "accessed_keys": accessed_keys[:20],
                "nested_accesses": nested_accesses,
            }
        )
    return consumers, wrapper_routes


def _wrapper_call_consumers(frontend_sources: list[tuple[str, str]], wrapper_routes: dict[str, str], duckdb_store: DuckDBStore) -> list[dict[str, object]]:
    consumers: list[dict[str, object]] = []
    for wrapper_name, wrapper_route in wrapper_routes.items():
        for relative_path, source in frontend_sources:
            for match in function_call_pattern(wrapper_name).finditer(source):
                caller_function = enclosing_function_name(source, match.start())
                if caller_function == wrapper_name:
                    continue
                snippet = source[max(0, match.start() - 800):]
                accessed_keys, nested_accesses = consumer_keys(snippet)
                if not accessed_keys and not nested_accesses:
                    continue
                consumers.append(
                    {
                        "route": wrapper_route,
                        "normalized_route": wrapper_route,
                        "method": "WRAPPER",
                        "file_path": relative_path,
                        "function": caller_function,
                        "calls_wrapper": wrapper_name,
                        "consumer_type": "wrapper_call",
                        "symbols": _symbol_names(duckdb_store, relative_path),
                        "accessed_keys": accessed_keys[:20],
                        "nested_accesses": nested_accesses,
                    }
                )
    return consumers


def route_map(repo_root: Path, duckdb_store: DuckDBStore, route: str = "") -> dict[str, object]:
    normalized_route = str(route or "").strip()
    handlers: list[dict[str, object]] = []
    consumers: list[dict[str, object]] = []
    frontend_sources: list[tuple[str, str]] = []
    wrapper_routes: dict[str, str] = {}
    for path in _iter_indexed_candidate_files(repo_root, duckdb_store):
        relative_path = str(path.relative_to(repo_root)).replace("\\", "/")
        if _is_test_path(relative_path):
            continue
        source = _read_text(path)
        if not source:
            continue
        if path.suffix.lower() == ".py":
            handlers.extend(_backend_handlers(source, relative_path, normalized_route))
        elif path.suffix.lower() == ".cs":
            handlers.extend(_csharp_handlers(source, relative_path, normalized_route))
        elif path.suffix.lower() == ".java":
            handlers.extend(_spring_handlers(source, relative_path, normalized_route))
        elif _is_backend_script_path(relative_path):
            handlers.extend(_express_handlers(source, relative_path, normalized_route))
            handlers.extend(_decorated_js_backend_handlers(source, relative_path, normalized_route))
        else:
            frontend_sources.append((relative_path, source))
            direct_consumers, direct_wrapper_routes = _direct_frontend_consumers(source, relative_path, normalized_route, duckdb_store)
            consumers.extend(direct_consumers)
            wrapper_routes.update(direct_wrapper_routes)
    consumers.extend(_wrapper_call_consumers(frontend_sources, wrapper_routes, duckdb_store))
    route_rows: list[dict[str, object]] = []
    all_routes = sorted({item["normalized_route"] for item in handlers} | {item["normalized_route"] for item in consumers})
    for found_route in all_routes:
        route_rows.append(
            {
                "route": found_route,
                "handlers": [item for item in handlers if item["normalized_route"] == found_route],
                "consumers": [item for item in consumers if item["normalized_route"] == found_route],
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
            "top_files": _unique([
                handler.get("file_path", "")
                for row in route_rows
                for handler in row.get("handlers", [])
                if isinstance(handler, dict)
            ] + [
                consumer.get("file_path", "")
                for row in route_rows
                for consumer in row.get("consumers", [])
                if isinstance(consumer, dict)
            ]),
            "top_symbols": _unique([
                handler.get("handler", "")
                for row in route_rows
                for handler in row.get("handlers", [])
                if isinstance(handler, dict)
            ] + [
                consumer.get("symbol", "") or consumer.get("function", "")
                for row in route_rows
                for consumer in row.get("consumers", [])
                if isinstance(consumer, dict)
            ]),
        },
    }
