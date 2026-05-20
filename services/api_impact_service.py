from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.route_map_service import route_map
from services.process_service import trace_execution_flows
from services.timeout_utils import run_with_timeout
from services.graph_edge_utils import edges_for_source_limited, edges_for_target_limited

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


MAX_GRAPH_FETCHERS = 16
MAX_READER_SYMBOLS_PER_ROUTE = 24
MAX_FIELD_READER_EDGES_PER_SYMBOL = 64
MAX_FIELD_READERS_PER_ROUTE = 200
GRAPH_CONTEXT_TIMEOUT_SECONDS = 1.5
HANDLER_PROCESS_TIMEOUT_SECONDS = 1.5


def _nested_missing_paths(nested_consumer_paths: list[str], response_keys: list[str], nested_response_keys: dict[str, list[str]]) -> list[str]:
    missing = []
    for path in nested_consumer_paths:
        parent, _, child = path.partition(".")
        shape_parent = parent
        top_level_parent = parent[:-2] if parent.endswith("[]") else parent
        if top_level_parent not in response_keys:
            missing.append(path)
            continue
        known_children = nested_response_keys.get(shape_parent, [])
        if child and known_children and child not in known_children:
            missing.append(path)
    return missing


def _augment_nested_shape_from_consumers(response_keys: list[str], nested_response_keys: dict[str, list[str]], nested_consumer_paths: list[str]) -> dict[str, list[str]]:
    augmented = {str(parent): list(values) for parent, values in nested_response_keys.items()}
    for path in nested_consumer_paths:
        parent, _, child = str(path or "").partition(".")
        top_level_parent = parent[:-2] if parent.endswith("[]") else parent
        if not parent or not child or top_level_parent not in response_keys:
            continue
        if parent in augmented:
            continue
        existing = set(augmented.get(parent, []))
        existing.add(child)
        augmented[parent] = sorted(existing)
    return augmented


def _shape_status(missing_keys: list[str], nested_missing_paths: list[str]) -> str:
    return "MISMATCH" if missing_keys or nested_missing_paths else "OK"


def _route_risk(consumers: list[dict[str, object]], missing_keys: list[str], nested_missing_paths: list[str], processes: list[dict[str, object]]) -> str:
    if missing_keys or nested_missing_paths:
        return "HIGH"
    max_steps = max((int(process.get("steps", 0) or 0) for process in processes), default=0)
    if len(consumers) >= 5 or len(processes) >= 6 or max_steps >= 6:
        return "HIGH"
    if consumers or processes:
        return "MEDIUM"
    return "LOW"


def _route_risk_factors(consumers: list[dict[str, object]], missing_keys: list[str], nested_missing_paths: list[str], processes: list[dict[str, object]]) -> list[str]:
    factors: list[str] = []
    if missing_keys or nested_missing_paths:
        factors.append("consumer response-shape mismatch")
    if consumers:
        factors.append(f"{len(consumers)} frontend/API consumers")
    if processes:
        factors.append(f"{len(processes)} traced execution flows")
    max_steps = max((int(process.get("steps", 0) or 0) for process in processes), default=0)
    if max_steps >= 6:
        factors.append(f"deepest traced flow has {max_steps} steps")
    return factors


def _route_flow_name(handler: dict[str, object], flow: dict[str, object]) -> str:
    method = str(handler.get("method", "") or "").upper()
    route = str(handler.get("route", "") or "")
    symbols = flow.get("symbols", []) if isinstance(flow.get("symbols", []), list) else []
    if method and route and symbols:
        compact_steps = [str(symbol).rsplit(".", 1)[-1] for symbol in symbols[:4]]
        return f"{method} {route} -> {' -> '.join(compact_steps)}"
    return str(flow.get("name", "") or "")


def _handler_processes(duckdb_store: DuckDBStore, kuzu_store: KuzuStore | None, handlers: list[dict[str, object]]) -> list[dict[str, object]]:
    if kuzu_store is None:
        return []
    processes: list[dict[str, object]] = []
    seen: set[str] = set()
    for handler in handlers[:4]:
        handler_name = str(handler.get("handler", "") or "").strip()
        file_path = str(handler.get("file_path", "") or "").strip()
        if not handler_name:
            continue
        traced = trace_execution_flows(
            duckdb_store,
            kuzu_store,
            target=handler_name,
            file_path=file_path or None,
            max_depth=4,
            max_flows=4,
        )
        for flow in traced.get("flows", []) if isinstance(traced, dict) else []:
            if not isinstance(flow, dict):
                continue
            key = str(flow.get("name") or flow.get("entry_symbol") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            processes.append(
                {
                    "name": _route_flow_name(handler, flow),
                    "flow_name": flow.get("name", ""),
                    "process_type": flow.get("process_type", ""),
                    "entry_symbol": flow.get("entry_symbol", ""),
                    "steps": flow.get("steps", 0),
                    "module": flow.get("module", ""),
                    "symbols": flow.get("symbols", [])[:12] if isinstance(flow.get("symbols", []), list) else [],
                    "step_details": flow.get("step_details", [])[:12] if isinstance(flow.get("step_details", []), list) else [],
                }
            )
            if len(processes) >= 8:
                return processes
    return processes


def _route_node(route: str) -> str:
    route_text = "/" + str(route or "").strip().strip("/")
    return f"route:{route_text.rstrip('/') or '/'}"


def _unique_values(values: list[object], limit: int = 8) -> list[str]:
    unique: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in unique:
            unique.append(text)
        if len(unique) >= limit:
            break
    return unique


def _symbol_file(duckdb_store: DuckDBStore, symbol_name: str) -> str:
    rows = duckdb_store.fetch_symbols_for_target(symbol_name, limit=1)
    return str(rows[0].get("file_path", "") or "") if rows else ""


def _graph_contract_context(duckdb_store: DuckDBStore, kuzu_store: KuzuStore | None, route: str) -> dict[str, object]:
    if kuzu_store is None:
        return {"fetchers": [], "field_readers": [], "field_reads": [], "field_to_readers": {}}
    fetch_edges = edges_for_target_limited(kuzu_store, _route_node(route), relation="FETCHES", limit=MAX_GRAPH_FETCHERS)
    fetchers = []
    for edge in fetch_edges:
        source = str(edge.get("source", "") or "")
        if not source:
            continue
        if source.rsplit(".", 1)[-1] in {"response", "data", "payload", "result"}:
            continue
        file_path = _symbol_file(duckdb_store, source)
        fetchers.append({"symbol": source, "file_path": file_path, "route": route})
        if len(fetchers) >= MAX_GRAPH_FETCHERS:
            break
    field_readers = []
    field_to_readers: dict[str, list[str]] = {}
    seen_reader_edges: set[tuple[str, str]] = set()
    for fetcher in fetchers:
        source = str(fetcher.get("symbol", "") or "")
        file_path = str(fetcher.get("file_path", "") or "")
        candidate_edges = edges_for_source_limited(kuzu_store, source, relation="READS_FIELD", limit=MAX_FIELD_READER_EDGES_PER_SYMBOL)
        for edge in candidate_edges:
            target = str(edge.get("target", "") or "")
            if not target.startswith("field:"):
                continue
            field_path = target.removeprefix("field:")
            key = (source, field_path)
            if key in seen_reader_edges:
                continue
            seen_reader_edges.add(key)
            field_readers.append({"symbol": source, "file_path": file_path, "field": field_path})
            field_to_readers.setdefault(field_path, []).append(source)
            if len(field_readers) >= MAX_FIELD_READERS_PER_ROUTE:
                break
        if len(field_readers) >= MAX_FIELD_READERS_PER_ROUTE:
            break
    # Components often read fields after calling an API wrapper, so include readers
    # from files already associated with this route via text/wrapper analysis later.
    return {
        "fetchers": fetchers,
        "field_readers": field_readers,
        "field_reads": sorted(field_to_readers),
        "field_to_readers": {field: sorted(set(readers)) for field, readers in field_to_readers.items()},
    }


def _merge_graph_consumers(consumers: list[dict[str, object]], graph_context: dict[str, object], duckdb_store: DuckDBStore) -> list[dict[str, object]]:
    merged = list(consumers)
    existing = {
        (str(item.get("file_path", "")), str(item.get("function", "") or item.get("symbol", "")), str(item.get("consumer_type", "")))
        for item in merged
        if isinstance(item, dict)
    }
    for fetcher in graph_context.get("fetchers", []) if isinstance(graph_context, dict) else []:
        if not isinstance(fetcher, dict):
            continue
        symbol = str(fetcher.get("symbol", "") or "")
        file_path = str(fetcher.get("file_path", "") or "")
        function = symbol.rsplit(".", 1)[-1] if symbol else ""
        key = (file_path, function, "graph_fetch")
        if key in existing:
            continue
        existing.add(key)
        merged.append(
            {
                "route": fetcher.get("route", ""),
                "normalized_route": fetcher.get("route", ""),
                "method": "GRAPH",
                "file_path": file_path,
                "function": function,
                "symbol": symbol,
                "consumer_type": "graph_fetch",
                "parser": "graph",
                "symbols": [symbol] if symbol else [],
                "accessed_keys": [],
                "nested_accesses": [],
            }
        )
    return merged


def _augment_field_readers_from_consumers(duckdb_store: DuckDBStore, kuzu_store: KuzuStore | None, consumers: list[dict[str, object]], graph_context: dict[str, object]) -> dict[str, object]:
    if kuzu_store is None:
        return graph_context
    field_readers = list(graph_context.get("field_readers", [])) if isinstance(graph_context.get("field_readers", []), list) else []
    field_to_readers = dict(graph_context.get("field_to_readers", {})) if isinstance(graph_context.get("field_to_readers", {}), dict) else {}
    seen = {
        (str(item.get("symbol", "") or ""), str(item.get("field", "") or ""))
        for item in field_readers
        if isinstance(item, dict)
    }
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        file_path = str(consumer.get("file_path", "") or "")
        symbols = [str(symbol) for symbol in consumer.get("symbols", []) if str(symbol)] if isinstance(consumer.get("symbols", []), list) else []
        symbol = str(consumer.get("symbol", "") or "")
        if symbol:
            symbols.append(symbol)
        function_name = str(consumer.get("function", "") or "")
        file_path = str(consumer.get("file_path", "") or "")
        if function_name and file_path:
            for row in duckdb_store.fetch_symbols_for_file(file_path):
                qualified = str(row.get("qualified_name", "") or "")
                name = str(row.get("name", "") or "")
                if name == function_name and qualified:
                    symbols.append(qualified)
        for candidate in symbols[:MAX_READER_SYMBOLS_PER_ROUTE]:
            for edge in edges_for_source_limited(kuzu_store, candidate, relation="READS_FIELD", limit=MAX_FIELD_READER_EDGES_PER_SYMBOL):
                target = str(edge.get("target", "") or "")
                if not target.startswith("field:"):
                    continue
                field_path = target.removeprefix("field:")
                key = (candidate, field_path)
                if key in seen:
                    continue
                seen.add(key)
                field_readers.append({"symbol": candidate, "file_path": file_path, "field": field_path})
                field_to_readers.setdefault(field_path, [])
                if candidate not in field_to_readers[field_path]:
                    field_to_readers[field_path].append(candidate)
                if len(field_readers) >= MAX_FIELD_READERS_PER_ROUTE:
                    break
            if len(field_readers) >= MAX_FIELD_READERS_PER_ROUTE:
                break
        if len(field_readers) >= MAX_FIELD_READERS_PER_ROUTE:
            break
    return {
        **graph_context,
        "field_readers": field_readers,
        "field_reads": sorted(field_to_readers),
        "field_to_readers": {field: sorted(set(readers)) for field, readers in field_to_readers.items()},
    }


def api_impact(repo_root: Path, duckdb_store: DuckDBStore, route: str = "", kuzu_store: KuzuStore | None = None) -> dict[str, object]:
    mapping = route_map(repo_root, duckdb_store, route=route)
    rows = []
    for item in mapping.get("routes", []):
        handlers = item.get("handlers", []) if isinstance(item, dict) else []
        consumers = item.get("consumers", []) if isinstance(item, dict) else []
        graph_warnings: list[str] = []
        graph_contract = run_with_timeout(
            lambda: _graph_contract_context(duckdb_store, kuzu_store, str(item.get("route", "") or route)),
            timeout_seconds=GRAPH_CONTEXT_TIMEOUT_SECONDS,
            default={"fetchers": [], "field_readers": [], "field_reads": [], "field_to_readers": {}, "partial": True},
            label="Graph contract expansion",
        )
        if graph_contract.get("partial"):
            graph_warnings.append("Graph contract expansion timed out; returned route/text analysis only.")
        consumers = _merge_graph_consumers(consumers, graph_contract, duckdb_store)
        if kuzu_store is not None:
            graph_contract = run_with_timeout(
                lambda: _augment_field_readers_from_consumers(duckdb_store, kuzu_store, consumers, graph_contract),
                timeout_seconds=GRAPH_CONTEXT_TIMEOUT_SECONDS,
                default={**graph_contract, "partial": True},
                label="Graph field-reader expansion",
            )
        if graph_contract.get("partial") and "Graph contract expansion timed out; returned route/text analysis only." not in graph_warnings:
            graph_warnings.append("Graph field-reader expansion timed out; returned route/text analysis only.")
        processes = run_with_timeout(
            lambda: _handler_processes(duckdb_store, kuzu_store, handlers),
            timeout_seconds=HANDLER_PROCESS_TIMEOUT_SECONDS,
            default=[],
            label="Route handler process tracing",
        )
        response_keys = sorted({key for handler in handlers for key in handler.get("response_keys", []) if key})
        nested_response_keys: dict[str, list[str]] = {}
        for handler in handlers:
            nested = handler.get("nested_response_keys", {}) if isinstance(handler, dict) else {}
            if not isinstance(nested, dict):
                continue
            for parent, keys in nested.items():
                nested_response_keys.setdefault(str(parent), [])
                nested_response_keys[str(parent)].extend(str(key) for key in keys if key)
        consumer_keys = sorted({key for consumer in consumers for key in consumer.get("accessed_keys", []) if key})
        nested_consumer_paths = sorted(
            {path for consumer in consumers for path in consumer.get("nested_accesses", []) if path}
            | {str(path) for path in graph_contract.get("field_reads", []) if str(path)}
        )
        shape_inferred_from_consumers = False
        if not response_keys and consumer_keys:
            response_keys = consumer_keys
            shape_inferred_from_consumers = True
        nested_response_keys = _augment_nested_shape_from_consumers(response_keys, {parent: sorted(set(keys)) for parent, keys in nested_response_keys.items()}, nested_consumer_paths)
        missing = [key for key in consumer_keys if key not in response_keys]
        nested_missing = _nested_missing_paths(nested_consumer_paths, response_keys, nested_response_keys)
        shape_status = _shape_status(missing, nested_missing)
        risk = _route_risk(consumers, missing, nested_missing, processes)
        risk_factors = _route_risk_factors(consumers, missing, nested_missing, processes)
        rows.append(
            {
                "route": item.get("route", ""),
                "handlers": handlers,
                "consumers": consumers,
                "processes": processes,
                "graph_contract": graph_contract,
                "response_keys": response_keys,
                "response_shape": {
                    "top_level_keys": response_keys,
                    "nested_keys": nested_response_keys,
                },
                "consumer_keys": consumer_keys,
                "nested_consumer_paths": nested_consumer_paths,
                "consumer_field_reads": nested_consumer_paths,
                "mismatch": bool(missing),
                "missing_keys": missing,
                "nested_mismatch": bool(nested_missing),
                "nested_missing_paths": nested_missing,
                "shape_check": {
                    "status": shape_status,
                    "missing_fields": missing,
                    "nested_missing_fields": nested_missing,
                    "checked_consumers": len(consumers),
                    "inferred_from_consumers": shape_inferred_from_consumers,
                },
                "risk": risk,
                "risk_factors": risk_factors,
                "warnings": graph_warnings,
                "blast_radius": {
                    "fetchers": graph_contract.get("fetchers", []),
                    "field_readers": graph_contract.get("field_readers", []),
                    "summary": f"This route is fetched by {', '.join(item.get('symbol', '') for item in graph_contract.get('fetchers', [])[:3] if isinstance(item, dict) and item.get('symbol')) or 'no graph fetchers'}, and fields are read by {', '.join(sorted({str(reader.get('symbol', '')) for reader in graph_contract.get('field_readers', []) if isinstance(reader, dict) and reader.get('symbol')})) or 'no graph field readers'}."
                },
                "reason": "Consumer field reads are missing from the response shape." if shape_status == "MISMATCH" else "Consumers and traced processes are compatible with detected response keys." if consumers and processes else "Consumers are compatible with detected response keys." if consumers else "No consumers detected for this route.",
            }
        )
    return {
        "repo_root": str(repo_root.resolve()),
        "route": route,
        "routes": rows,
        "total": len(rows),
        "compact_summary": {
            "target": route or str(repo_root.resolve()),
            "total": len(rows),
            "top_routes": [row.get("route", "") for row in rows[:8]],
            "top_files": _unique_values([
                str(handler.get("file_path", "") or "")
                for row in rows
                for handler in row.get("handlers", [])
                if isinstance(handler, dict)
            ] + [
                str(consumer.get("file_path", "") or "")
                for row in rows
                for consumer in row.get("consumers", [])
                if isinstance(consumer, dict)
            ]),
            "top_symbols": _unique_values([
                str(handler.get("handler", "") or "")
                for row in rows
                for handler in row.get("handlers", [])
                if isinstance(handler, dict)
            ] + [
                str(consumer.get("symbol", "") or consumer.get("function", "") or "")
                for row in rows
                for consumer in row.get("consumers", [])
                if isinstance(consumer, dict)
            ]),
            "mismatches": [row.get("route", "") for row in rows if row.get("shape_check", {}).get("status") == "MISMATCH"][:8],
            "top_processes": [process.get("name", "") for row in rows for process in row.get("processes", []) if isinstance(process, dict)][:8],
            "graph_fetchers": _unique_values([fetcher.get("symbol", "") for row in rows for fetcher in row.get("graph_contract", {}).get("fetchers", []) if isinstance(fetcher, dict)]),
            "graph_field_readers": _unique_values([reader.get("symbol", "") for row in rows for reader in row.get("graph_contract", {}).get("field_readers", []) if isinstance(reader, dict)]),
            "graph_field_count": len({str(reader.get("field", "") or "") for row in rows for reader in row.get("graph_contract", {}).get("field_readers", []) if isinstance(reader, dict) and reader.get("field")}),
            "highest_risk": "HIGH" if any(row.get("risk") == "HIGH" for row in rows) else "MEDIUM" if any(row.get("risk") == "MEDIUM" for row in rows) else "LOW",
        },
    }
