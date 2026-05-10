from __future__ import annotations

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from services.symbol_resolution_service import ambiguity_status, resolve_candidates


ENTRY_HINT_TOKENS = ("page", "route", "handler", "endpoint", "upload", "export", "screen", "view")
GENERIC_TERMINAL_NAMES = {
    "all",
    "any",
    "bool",
    "dict",
    "float",
    "int",
    "items",
    "len",
    "list",
    "lower",
    "max",
    "min",
    "next",
    "now",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "upper",
    "values",
}


def _entry_priority(duckdb_store: DuckDBStore, symbol_name: str, requested_file_path: str = "") -> tuple[int, int, int, int, int, int, str]:
    rows = duckdb_store.fetch_symbols_for_target(symbol_name, limit=1)
    if not rows:
        return (0, 0, 0, 0, 0, 0, symbol_name)
    row = rows[0]
    file_path = str(row.get("file_path", "")).replace("\\", "/").lower()
    requested_file = str(requested_file_path or "").replace("\\", "/").lower()
    kind = str(row.get("kind", "")).lower()
    symbol_lower = symbol_name.lower()
    is_test = int("/tests/" in file_path or file_path.startswith("tests/") or symbol_lower.startswith("test_"))
    is_report_helper = int("report" in file_path or "report" in symbol_lower or "pricelist" in symbol_lower)
    route_handler = int(("/routers/" in file_path or "/routes/" in file_path or "/api/" in file_path) and not is_report_helper)
    requested_file_match = int(bool(requested_file) and file_path == requested_file and not is_test and not is_report_helper)
    hint = int(any(token in file_path or token in kind or token in symbol_lower for token in ENTRY_HINT_TOKENS))
    frontend = int(file_path.startswith("frontend/"))
    return (route_handler, requested_file_match, -is_report_helper, hint, frontend, -is_test, file_path)


def _entry_candidates(duckdb_store: DuckDBStore, kuzu_store: KuzuStore, target: str, requested_file_path: str = "") -> list[str]:
    callers = [str(edge.get("source", "")) for edge in kuzu_store.edges_for_target(target, relation="CALLS") if str(edge.get("source", ""))]
    if not callers:
        return [target]
    ranked = sorted(set(callers), key=lambda item: _entry_priority(duckdb_store, item, requested_file_path=requested_file_path), reverse=True)
    return ranked[:4] or [target]


def _symbol_row(duckdb_store: DuckDBStore, symbol_name: str) -> dict[str, object]:
    rows = duckdb_store.fetch_symbols_for_target(symbol_name, limit=1)
    return rows[0] if rows else {}


def _call_priority(duckdb_store: DuckDBStore, node: str) -> tuple[int, int, int, int, str]:
    row = _symbol_row(duckdb_store, node)
    file_path = str(row.get("file_path", "") or "").replace("\\", "/").lower()
    kind = str(row.get("kind", "") or "").lower()
    tail = node.rsplit(".", 1)[-1]
    generic = int(tail in GENERIC_TERMINAL_NAMES)
    project_symbol = int(bool(file_path))
    app_area = int(any(part in file_path for part in ("/services/", "/repositories/", "/routers/", "/processors/", "/api/", "backend/", "frontend/")))
    callable_kind = int(any(token in kind for token in ("function", "method", "component", "hook")))
    return (project_symbol, app_area, callable_kind, -generic, node)


def _rank_next_nodes(duckdb_store: DuckDBStore, nodes: list[str]) -> list[str]:
    return sorted(set(nodes), key=lambda node: _call_priority(duckdb_store, node), reverse=True)


def _flow_priority(duckdb_store: DuckDBStore, path: list[str]) -> tuple[int, int, int, int, str]:
    terminal = path[-1] if path else ""
    terminal_priority = _call_priority(duckdb_store, terminal)
    generic_terminal = int(terminal.rsplit(".", 1)[-1] in GENERIC_TERMINAL_NAMES)
    project_steps = sum(1 for node in path if _symbol_row(duckdb_store, node))
    return (terminal_priority[0], terminal_priority[1], project_steps, -generic_terminal, " -> ".join(path))


def _is_generic_terminal(path: list[str]) -> bool:
    terminal = path[-1] if path else ""
    return terminal.rsplit(".", 1)[-1] in GENERIC_TERMINAL_NAMES


def _symbol_boundary_role(duckdb_store: DuckDBStore, symbol_name: str) -> str:
    row = _symbol_row(duckdb_store, symbol_name)
    file_path = str(row.get("file_path", "") or "").replace("\\", "/").lower()
    kind = str(row.get("kind", "") or "").lower()
    name = str(row.get("name", "") or symbol_name.rsplit(".", 1)[-1]).lower()
    qualified = str(row.get("qualified_name", "") or symbol_name).lower()
    combined = " ".join([file_path, kind, name, qualified])
    if any(token in combined for token in ("repository", "/repositories/", "dbcontext", "entityframework", "dataaccess", "/data/")):
        return "data_access"
    if any(token in combined for token in ("httpclient", "grpc", "restclient", "externalclient", "/clients/")):
        return "external_io"
    if any(token in combined for token in ("controller", "/controllers/", "/endpoints/", "/minimalapi")):
        return "route_entrypoint"
    if any(token in combined for token in ("service", "/services/")):
        return "service"
    return ""


def _select_flows(duckdb_store: DuckDBStore, flows: list[list[str]], max_flows: int) -> list[list[str]]:
    ranked = sorted(flows, key=lambda path: _flow_priority(duckdb_store, path), reverse=True)
    focused = [path for path in ranked if not _is_generic_terminal(path)]
    return (focused or ranked)[:max_flows]


def _flow_edges(kuzu_store: KuzuStore, current: str) -> list[dict[str, object]]:
    edges: list[dict[str, object]] = []
    for relation in ("CALLS", "USES_SERVICE", "INJECTS"):
        edges.extend(kuzu_store.edges_for_source(current, relation=relation))
    return edges


def _walk_call_paths(duckdb_store: DuckDBStore, kuzu_store: KuzuStore, start: str, max_depth: int, max_flows: int) -> list[list[str]]:
    flows: list[list[str]] = []
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    candidate_limit = max(max_flows * 4, max_flows)
    while stack and len(flows) < candidate_limit:
        current, path = stack.pop()
        if len(path) - 1 >= max_depth:
            flows.append(path)
            continue
        callees = _flow_edges(kuzu_store, current)
        next_nodes = [str(edge.get("target", "")) for edge in callees if str(edge.get("target", "")) and str(edge.get("target", "")) not in path]
        if not next_nodes:
            flows.append(path)
            continue
        ranked_nodes = _rank_next_nodes(duckdb_store, next_nodes)
        for node in reversed(ranked_nodes[:8]):
            stack.append((node, [*path, node]))
    return _select_flows(duckdb_store, flows, max_flows)


def _flow_name(path: list[str], module_name: str) -> str:
    if not path:
        return module_name or "Flow"
    start = path[0].split(".")[-1]
    end = path[-1].split(".")[-1]
    if start == end:
        return f"{module_name}: {start}" if module_name else start
    return f"{module_name}: {start} -> {end}" if module_name else f"{start} -> {end}"


def _flow_risk(path: list[str], changed_steps: list[str]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if changed_steps:
        reasons.append(f"{len(changed_steps)} changed step(s) in flow")
    if changed_steps and len(path) >= 5:
        reasons.append(f"changed step participates in {len(path)}-step flow")
    if len(path) >= 6:
        reasons.append(f"deep flow with {len(path)} steps")
    if changed_steps and len(path) >= 5:
        return "HIGH", reasons
    if changed_steps or len(path) >= 4:
        return "MEDIUM", reasons
    return "LOW", reasons


def _flow_risk_with_boundaries(duckdb_store: DuckDBStore, path: list[str], changed_steps: list[str]) -> tuple[str, list[str]]:
    risk, reasons = _flow_risk(path, changed_steps)
    boundary_roles = [_symbol_boundary_role(duckdb_store, node) for node in path]
    if "data_access" in boundary_roles:
        reasons.append("flow reaches repository/data-access boundary")
        if changed_steps and risk == "LOW":
            risk = "MEDIUM"
    if "external_io" in boundary_roles:
        reasons.append("flow reaches external I/O client boundary")
        if changed_steps and risk == "LOW":
            risk = "MEDIUM"
    return risk, reasons


def _module_for_symbol(duckdb_store: DuckDBStore, symbol_name: str) -> str:
    rows = duckdb_store.fetch_symbols_for_target(symbol_name, limit=1)
    if not rows:
        return ""
    file_path = str(rows[0].get("file_path", ""))
    return file_path.split("/", 1)[0] if "/" in file_path else file_path


def _symbol_file(duckdb_store: DuckDBStore, symbol_name: str) -> str:
    rows = duckdb_store.fetch_symbols_for_target(symbol_name, limit=1)
    if not rows:
        return ""
    return str(rows[0].get("file_path", "") or "")


def _unique(values: list[object], limit: int = 8) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def _flow_files(duckdb_store: DuckDBStore, flow: list[str]) -> list[str]:
    return _unique([_symbol_file(duckdb_store, symbol_name) for symbol_name in flow], limit=12)


def _compact_flow_summaries(flow_rows: list[dict[str, object]], limit: int = 5) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in flow_rows:
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("entry_symbol", "") or ""),
            str(row.get("target_symbol", "") or ""),
            str(row.get("terminal_symbol", "") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        summaries.append(
            {
                "name": str(row.get("name", "") or ""),
                "risk": str(row.get("risk", "LOW") or "LOW"),
                "steps": int(row.get("steps", 0) or 0),
                "entry_symbol": str(row.get("entry_symbol", "") or ""),
                "target_symbol": str(row.get("target_symbol", "") or ""),
                "terminal_symbol": str(row.get("terminal_symbol", "") or ""),
                "terminal_type": str(row.get("terminal_type", "") or ""),
                "files": row.get("files", []) if isinstance(row.get("files", []), list) else [],
                "changed_symbols": row.get("changed_symbols", []) if isinstance(row.get("changed_symbols", []), list) else [],
            }
        )
        if len(summaries) >= limit:
            break
    return summaries


def trace_execution_flows(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    target: str,
    file_path: str | None = None,
    kind: str | None = None,
    symbol_uid: str | None = None,
    max_depth: int = 4,
    max_flows: int = 8,
    changed_symbols: list[str] | None = None,
) -> dict[str, object]:
    candidates = resolve_candidates(duckdb_store, target=target, file_path=file_path, kind=kind, symbol_uid_value=symbol_uid, limit=5)
    if not candidates:
        return {
            "target": target,
            "status": "not_found",
            "flows": [],
            "compact_summary": {
                "target": target,
                "status": "not_found",
                "flow_count": 0,
            },
        }
    primary = candidates[0]
    symbol = primary.get("symbol", {}) if isinstance(primary, dict) else {}
    resolved_target = str(symbol.get("qualified_name") or symbol.get("name") or target)
    ambiguous = ambiguity_status(candidates)
    entrypoints = _entry_candidates(duckdb_store, kuzu_store, resolved_target, requested_file_path=file_path or "")
    changed_symbol_set = {str(symbol or "") for symbol in (changed_symbols or []) if str(symbol or "")}
    flow_rows = []
    for entrypoint in entrypoints:
        for flow in _walk_call_paths(duckdb_store, kuzu_store, entrypoint, max_depth=max_depth, max_flows=max_flows):
            if resolved_target not in flow:
                continue
            module_name = _module_for_symbol(duckdb_store, flow[0])
            changed_steps = [node for node in flow if node in changed_symbol_set or node.rsplit(".", 1)[-1] in changed_symbol_set]
            risk, risk_reasons = _flow_risk_with_boundaries(duckdb_store, flow, changed_steps)
            boundary_roles = [_symbol_boundary_role(duckdb_store, node) for node in flow]
            flow_rows.append(
                {
                    "name": _flow_name(flow, module_name),
                    "process_type": "entrypoint_call_path" if entrypoint != resolved_target else "call_path",
                    "index": len(flow_rows) + 1,
                    "steps": len(flow),
                    "entry_symbol": entrypoint,
                    "target_symbol": resolved_target,
                    "terminal_symbol": flow[-1] if flow else "",
                    "module": module_name,
                    "files": _flow_files(duckdb_store, flow),
                    "entry_type": _symbol_boundary_role(duckdb_store, entrypoint),
                    "terminal_type": _symbol_boundary_role(duckdb_store, flow[-1] if flow else ""),
                    "boundary_roles": [role for role in boundary_roles if role],
                    "step_details": [
                        {
                            "symbol": node,
                            "file": _symbol_file(duckdb_store, node),
                            "step": step_index + 1,
                            "changed": node in changed_steps or node.rsplit(".", 1)[-1] in changed_steps,
                            "role": _symbol_boundary_role(duckdb_store, node),
                        }
                        for step_index, node in enumerate(flow)
                    ],
                    "symbols": flow,
                    "changed_symbols": changed_steps,
                    "risk": risk,
                    "risk_reasons": risk_reasons,
                }
            )
            if len(flow_rows) >= max_flows:
                break
        if len(flow_rows) >= max_flows:
            break
    top_files = _unique([
        _symbol_file(duckdb_store, symbol_name)
        for row in flow_rows
        for symbol_name in row.get("symbols", [])
        if isinstance(row, dict)
    ])
    top_symbols = _unique([
        symbol_name
        for row in flow_rows
        for symbol_name in row.get("symbols", [])
        if isinstance(row, dict)
    ])
    terminal_types = _unique([
        row.get("terminal_type", "")
        for row in flow_rows
        if isinstance(row, dict)
    ])
    return {
        "target": target,
        "status": "ambiguous" if ambiguous else "found",
        "resolved_target": resolved_target,
        "entrypoints": entrypoints,
        "candidate_matches": [
            {
                "qualified_name": item.get("symbol", {}).get("qualified_name", ""),
                "file_path": item.get("symbol", {}).get("file_path", ""),
                "kind": item.get("symbol", {}).get("kind", ""),
                "uid": item.get("symbol", {}).get("uid", ""),
                "score": item.get("score", 0.0),
                "confidence": item.get("confidence", "low"),
            }
            for item in candidates
        ],
        "flows": flow_rows,
        "compact_summary": {
            "target": resolved_target,
            "status": "ambiguous" if ambiguous else "found",
            "flow_count": len(flow_rows),
            "entrypoints": entrypoints,
            "top_flows": _compact_flow_summaries(flow_rows, limit=5),
            "top_files": top_files,
            "top_symbols": top_symbols,
            "route_context": [
                file_path
                for file_path in top_files
                if "/routers/" in file_path or "/routes/" in file_path or "/api/" in file_path
            ][:5],
            "terminal_types": terminal_types,
            "max_steps": max((item["steps"] for item in flow_rows), default=0),
            "highest_risk": "HIGH" if any(item.get("risk") == "HIGH" for item in flow_rows) else "MEDIUM" if any(item.get("risk") == "MEDIUM" for item in flow_rows) else "LOW",
            "warnings": ["Target resolution is ambiguous; pass file_path or kind to narrow it."] if ambiguous else [],
        },
    }
