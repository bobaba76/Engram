"""Route and process change summary helpers for change detection."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore
from services.route_map_service import _backend_handlers, _direct_frontend_consumers, _read_text
from services.timeout_utils import run_with_timeout

ROUTE_OPERATION_TIMEOUT_SECONDS = 2.0
PROCESS_OPERATION_TIMEOUT_SECONDS = 2.0


def _process_target_priority(symbol: dict[str, object]) -> tuple[int, int, int, int, str]:
    file_path = str(symbol.get("file_path", "") or "").replace("\\", "/").lower()
    name = str(symbol.get("qualified_name") or symbol.get("name") or "")
    tail = name.rsplit(".", 1)[-1].lower()
    span = int(symbol.get("end_line", 0) or 0) - int(symbol.get("start_line", 0) or 0)
    broad_wrapper = int(tail in {"main", "__init__"} or span > 180)
    service_area = int(file_path.startswith("services/") and "detect_changes_service.py" not in file_path)
    graph_area = int("impact" in file_path or "process" in file_path or "route" in file_path or "context" in file_path)
    runtime_kind = int(str(symbol.get("kind", "") or "").lower() in {"function", "method"})
    return (-broad_wrapper, service_area, graph_area, runtime_kind, name)


def _indexed_process_rows(duckdb_store: DuckDBStore, targets: list[dict[str, str]], changed_routes: list[str], limit: int = 12) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for item in targets[:12]:
        target = item["target"]
        aliases = [target, target.rsplit(".", 1)[-1]]
        for alias in aliases:
            for process in duckdb_store.fetch_process_clusters_for_symbol(alias, limit=4):
                name = str(process.get("name", "") or "")
                key = (name, target)
                if not name or key in seen:
                    continue
                seen.add(key)
                route_context = [route for route in changed_routes if route.replace("/", "_").strip("_").lower() in name.lower()]
                step_count = int(process.get("avg_step_count", 0) or process.get("step_count", 0) or 0)
                rows.append({
                    "name": name,
                    "target": target,
                    "entry_symbol": process.get("canonical_entry_symbol", ""),
                    "module": process.get("module_tags", []),
                    "steps": step_count,
                    "step_details": [],
                    "changed_symbol": target,
                    "changed_symbols": [target],
                    "changed_routes": route_context,
                    "risk": "MEDIUM" if step_count >= 4 else "LOW",
                    "risk_reasons": ["indexed process cluster includes changed symbol"],
                })
                if len(rows) >= limit:
                    return rows
    return rows


def _process_change_summary(duckdb_store: DuckDBStore, kuzu_store: KuzuStore, changed_symbols: list[dict[str, object]], changed_routes: list[str], warnings: list[str] | None = None) -> dict[str, object]:
    from services.process_service import trace_execution_flows

    targets: list[dict[str, str]] = []
    ranked_symbols = sorted(
        [symbol for symbol in changed_symbols if isinstance(symbol, dict)],
        key=_process_target_priority,
        reverse=True,
    )
    for symbol in ranked_symbols[:10]:
        if not isinstance(symbol, dict):
            continue
        target = str(symbol.get("qualified_name") or symbol.get("name") or "")
        if not target:
            continue
        targets.append({
            "target": target,
            "file_path": str(symbol.get("file_path", "") or ""),
            "kind": str(symbol.get("kind", "") or ""),
        })
    seen = set()
    unique_targets = []
    for item in targets:
        key = (item["target"], item["file_path"], item["kind"])
        if key in seen:
            continue
        seen.add(key)
        unique_targets.append(item)
    affected_processes = []
    risk_by_process = []
    indexed_rows = _indexed_process_rows(duckdb_store, unique_targets, changed_routes, limit=12)
    affected_processes.extend(indexed_rows)
    for row in indexed_rows:
        risk_by_process.append({
            "name": row.get("name", ""),
            "risk": row.get("risk", "LOW"),
            "changed_symbol": row.get("changed_symbol", ""),
            "steps": row.get("steps", 0),
        })
    if indexed_rows:
        return {
            "affected_processes": affected_processes[:12],
            "risk_by_process": risk_by_process[:12],
        }
    for item in unique_targets[:3]:
        traced = run_with_timeout(
            lambda item=item: trace_execution_flows(
                duckdb_store,
                kuzu_store,
                target=item["target"],
                file_path=item["file_path"] or None,
                kind=item["kind"] or None,
                max_depth=4,
                max_flows=4,
                changed_symbols=[item["target"]],
            ),
            timeout_seconds=PROCESS_OPERATION_TIMEOUT_SECONDS,
            default={},
            warnings=warnings,
            label=f"Process tracing for {item['target']}",
        )
        if not traced:
            continue
        flows = traced.get("flows", []) if isinstance(traced, dict) else []
        for flow in flows[:4] if isinstance(flows, list) else []:
            if not isinstance(flow, dict):
                continue
            route_context = [route for route in changed_routes if route.replace("/", "_").strip("_").lower() in str(flow.get("name", "")).lower()]
            risk = str(flow.get("risk") or ("HIGH" if int(flow.get("steps", 0) or 0) >= 5 else "MEDIUM" if int(flow.get("steps", 0) or 0) >= 3 else "LOW"))
            process_row = {
                "name": flow.get("name", ""),
                "target": item["target"],
                "entry_symbol": flow.get("entry_symbol", ""),
                "module": flow.get("module", ""),
                "steps": flow.get("steps", 0),
                "step_details": flow.get("step_details", []),
                "changed_symbol": item["target"],
                "changed_symbols": flow.get("changed_symbols", [item["target"]]),
                "changed_routes": route_context,
                "risk": risk,
                "risk_reasons": flow.get("risk_reasons", []),
            }
            affected_processes.append(process_row)
            risk_by_process.append({
                "name": process_row["name"],
                "risk": risk,
                "changed_symbol": item["target"],
                "steps": process_row["steps"],
            })
    return {
        "affected_processes": affected_processes[:12],
        "risk_by_process": risk_by_process[:12],
    }


def _route_change_summary(repo_root: Path, duckdb_store: DuckDBStore, changed_files: list[str], changed_symbols: list[dict[str, object]] | None = None, kuzu_store: KuzuStore | None = None) -> dict[str, object]:
    if not changed_files:
        return {
            "changed_routes": [],
            "affected_consumers": [],
            "changed_response_shapes": [],
            "risk_by_route": [],
            "shape_mismatches": [],
        }
    changed_set = set(changed_files)
    changed_routes = []
    changed_symbols_by_file: dict[str, set[str]] = {}
    for symbol in changed_symbols or []:
        if not isinstance(symbol, dict):
            continue
        file_path = str(symbol.get("file_path", "") or "")
        names = {
            str(symbol.get("name", "") or ""),
            str(symbol.get("qualified_name", "") or "").rsplit(".", 1)[-1],
        }
        changed_symbols_by_file.setdefault(file_path, set()).update(name for name in names if name)
    affected_consumers: dict[str, dict[str, object]] = {}
    changed_response_shapes = []
    risk_by_route = []
    shape_mismatches = []
    candidate_routes: list[str] = []
    for file_path in changed_files:
        suffix = Path(file_path).suffix.lower()
        absolute_path = repo_root / file_path
        if suffix == ".py":
            source = _read_text(absolute_path)
            if not source:
                continue
            for handler in _backend_handlers(source, file_path, ""):
                handler_name = str(handler.get("handler", "") or "")
                changed_names = changed_symbols_by_file.get(file_path, set())
                if changed_names and handler_name not in changed_names:
                    continue
                route = str(handler.get("normalized_route") or handler.get("route") or "")
                if route and route not in candidate_routes:
                    candidate_routes.append(route)
        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            source = _read_text(absolute_path)
            if not source:
                continue
            direct_consumers, direct_wrapper_routes = _direct_frontend_consumers(source, file_path, "", duckdb_store)
            for consumer in direct_consumers:
                route = str(consumer.get("normalized_route") or consumer.get("route") or "")
                if route and route not in candidate_routes:
                    candidate_routes.append(route)
            for route in direct_wrapper_routes.values():
                if route and route not in candidate_routes:
                    candidate_routes.append(route)
    from services.api_impact_service import api_impact

    for route_name in candidate_routes[:8]:
        contract = run_with_timeout(
            lambda route_name=route_name: api_impact(repo_root, duckdb_store, route=route_name, kuzu_store=kuzu_store),
            timeout_seconds=ROUTE_OPERATION_TIMEOUT_SECONDS,
            default={},
            label=f"Route impact for {route_name}",
        )
        if not contract:
            continue
        for route_row in contract.get("routes", []) if isinstance(contract, dict) else []:
            if not isinstance(route_row, dict):
                continue
            route_row = {
                **route_row,
                "status": route_row.get("shape_check", {}).get("status", "UNKNOWN") if isinstance(route_row.get("shape_check", {}), dict) else "UNKNOWN",
                "missing_fields": route_row.get("shape_check", {}).get("missing_fields", []) if isinstance(route_row.get("shape_check", {}), dict) else [],
                "nested_missing_fields": route_row.get("shape_check", {}).get("nested_missing_fields", []) if isinstance(route_row.get("shape_check", {}), dict) else [],
                "checked_consumers": route_row.get("shape_check", {}).get("checked_consumers", 0) if isinstance(route_row.get("shape_check", {}), dict) else 0,
            }
            break
        else:
            continue
        if not isinstance(route_row, dict):
            continue
        consumers = route_row.get("consumers", []) if isinstance(route_row.get("consumers", []), list) else []
        graph_contract = route_row.get("graph_contract", {}) if isinstance(route_row.get("graph_contract", {}), dict) else {}
        handler_files = [
            str(handler.get("file_path", ""))
            for handler in route_row.get("handlers", []) if isinstance(handler, dict)
        ] if isinstance(route_row.get("handlers", []), list) else []
        consumer_files = [
            str(consumer.get("file_path", ""))
            for consumer in consumers if isinstance(consumer, dict)
        ]
        handler_touched = False
        for handler in route_row.get("handlers", []) if isinstance(route_row.get("handlers", []), list) else []:
            if not isinstance(handler, dict):
                continue
            handler_file = str(handler.get("file_path", "") or "")
            handler_name = str(handler.get("handler", "") or "")
            if handler_file not in changed_set:
                continue
            changed_names = changed_symbols_by_file.get(handler_file, set())
            if not changed_names or handler_name in changed_names:
                handler_touched = True
                break
        consumer_touched = any(file_path in changed_set for file_path in consumer_files)
        route_touched = handler_touched or consumer_touched
        if not route_touched:
            continue
        route_name = str(route_row.get("route", ""))
        if route_name in changed_routes:
            continue
        changed_routes.append(route_name)
        if handler_touched:
            changed_response_shapes.append({
                "route": route_name,
                "response_shape": route_row.get("response_shape", {}),
                "status": route_row.get("status", "UNKNOWN"),
            })
        for consumer in consumers:
            if not isinstance(consumer, dict):
                continue
            consumer_file = str(consumer.get("file_path", ""))
            if consumer_file:
                field_reads = list(consumer.get("nested_accesses", []) if isinstance(consumer.get("nested_accesses", []), list) else [])
                if graph_contract:
                    for graph_field in graph_contract.get("field_reads", []) if isinstance(graph_contract.get("field_reads", []), list) else []:
                        if graph_field not in field_reads:
                            field_reads.append(graph_field)
                affected_consumers[consumer_file] = {
                    "file": consumer_file,
                    "route": route_name,
                    "function": consumer.get("function", ""),
                    "consumer_type": consumer.get("consumer_type", ""),
                    "field_reads": field_reads,
                }
                if graph_contract:
                    affected_consumers[consumer_file]["graph_contract"] = graph_contract
        risk_by_route.append({
            "route": route_name,
            "risk": route_row.get("risk", "LOW"),
            "status": route_row.get("status", "UNKNOWN"),
            "checked_consumers": route_row.get("checked_consumers", 0),
        })
        if route_row.get("status") == "MISMATCH":
            shape_mismatches.append({
                "route": route_name,
                "missing_fields": route_row.get("missing_fields", []),
                "nested_missing_fields": route_row.get("nested_missing_fields", []),
            })
    return {
        "changed_routes": changed_routes,
        "affected_consumers": list(affected_consumers.values()),
        "changed_response_shapes": changed_response_shapes,
        "risk_by_route": risk_by_route,
        "shape_mismatches": shape_mismatches,
    }
