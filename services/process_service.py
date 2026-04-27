from __future__ import annotations

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from services.symbol_resolution_service import ambiguity_status, resolve_candidates


ENTRY_HINT_TOKENS = ("page", "route", "handler", "endpoint", "upload", "export", "screen", "view")


def _entry_priority(duckdb_store: DuckDBStore, symbol_name: str) -> tuple[int, int, str]:
    rows = duckdb_store.fetch_symbols_for_target(symbol_name, limit=1)
    if not rows:
        return (0, 0, symbol_name)
    row = rows[0]
    file_path = str(row.get("file_path", "")).lower()
    kind = str(row.get("kind", "")).lower()
    hint = int(any(token in file_path or token in kind or token in symbol_name.lower() for token in ENTRY_HINT_TOKENS))
    frontend = int(file_path.startswith("frontend/"))
    return (hint, frontend, file_path)


def _entry_candidates(duckdb_store: DuckDBStore, kuzu_store: KuzuStore, target: str) -> list[str]:
    callers = [str(edge.get("source", "")) for edge in kuzu_store.edges_for_target(target, relation="CALLS") if str(edge.get("source", ""))]
    if not callers:
        return [target]
    ranked = sorted(set(callers), key=lambda item: _entry_priority(duckdb_store, item), reverse=True)
    return ranked[:4] or [target]


def _walk_call_paths(kuzu_store: KuzuStore, start: str, max_depth: int, max_flows: int) -> list[list[str]]:
    flows: list[list[str]] = []
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    while stack and len(flows) < max_flows:
        current, path = stack.pop()
        if len(path) - 1 >= max_depth:
            flows.append(path)
            continue
        callees = kuzu_store.edges_for_source(current, relation="CALLS")
        next_nodes = [str(edge.get("target", "")) for edge in callees if str(edge.get("target", "")) and str(edge.get("target", "")) not in path]
        if not next_nodes:
            flows.append(path)
            continue
        for node in reversed(next_nodes[:8]):
            stack.append((node, [*path, node]))
    return flows


def _flow_name(path: list[str], module_name: str) -> str:
    if not path:
        return module_name or "Flow"
    start = path[0].split(".")[-1]
    end = path[-1].split(".")[-1]
    if start == end:
        return f"{module_name}: {start}" if module_name else start
    return f"{module_name}: {start} → {end}" if module_name else f"{start} → {end}"


def _module_for_symbol(duckdb_store: DuckDBStore, symbol_name: str) -> str:
    rows = duckdb_store.fetch_symbols_for_target(symbol_name, limit=1)
    if not rows:
        return ""
    file_path = str(rows[0].get("file_path", ""))
    return file_path.split("/", 1)[0] if "/" in file_path else file_path


def trace_execution_flows(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    target: str,
    file_path: str | None = None,
    kind: str | None = None,
    symbol_uid: str | None = None,
    max_depth: int = 4,
    max_flows: int = 8,
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
    entrypoints = _entry_candidates(duckdb_store, kuzu_store, resolved_target)
    flow_rows = []
    for entrypoint in entrypoints:
        for flow in _walk_call_paths(kuzu_store, entrypoint, max_depth=max_depth, max_flows=max_flows):
            if resolved_target not in flow:
                if entrypoint != resolved_target:
                    flow = [entrypoint, *flow]
            module_name = _module_for_symbol(duckdb_store, flow[0])
            flow_rows.append(
                {
                    "name": _flow_name(flow, module_name),
                    "process_type": "entrypoint_call_path" if entrypoint != resolved_target else "call_path",
                    "index": len(flow_rows) + 1,
                    "steps": len(flow),
                    "entry_symbol": entrypoint,
                    "module": module_name,
                    "step_details": [{"symbol": node, "step": step_index + 1} for step_index, node in enumerate(flow)],
                    "symbols": flow,
                }
            )
            if len(flow_rows) >= max_flows:
                break
        if len(flow_rows) >= max_flows:
            break
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
            "top_flows": [item["name"] for item in flow_rows[:5]],
            "max_steps": max((item["steps"] for item in flow_rows), default=0),
            "warnings": ["Target resolution is ambiguous; pass file_path or kind to narrow it."] if ambiguous else [],
        },
    }
