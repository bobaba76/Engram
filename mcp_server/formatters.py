import json
from typing import Any


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _strip_large_internal_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_large_internal_fields(item) for item in value]
    if isinstance(value, dict):
        stripped: dict[str, Any] = {}
        for key, item in value.items():
            if key == "vector":
                continue
            stripped[key] = _strip_large_internal_fields(item)
        return stripped
    return value


def _render_target(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("qualified_name", "name", "target", "file_path"):
            rendered = str(value.get(key) or "").strip()
            if rendered:
                return rendered
        return ""
    return str(value or "")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dedupe_strings(values: list[Any], limit: int = 8) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def _derive_status(payload: dict[str, Any], compact_summary: dict[str, Any]) -> str:
    for value in (
        payload.get("status"),
        compact_summary.get("status"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    if payload.get("error"):
        return "error"
    if compact_summary.get("warnings") and not payload.get("matches") and not payload.get("compact_results"):
        return "partial"
    return "ok"


def _derive_partial(payload: dict[str, Any], compact_summary: dict[str, Any], status: str) -> bool:
    if isinstance(payload.get("partial"), bool):
        return bool(payload.get("partial"))
    if isinstance(compact_summary.get("partial"), bool):
        return bool(compact_summary.get("partial"))
    if status == "partial":
        return True
    warnings = _as_list(compact_summary.get("warnings")) + _as_list(payload.get("warnings"))
    warning_text = " ".join(str(item or "").lower() for item in warnings)
    return "capped" in warning_text or "truncated" in warning_text or "partial" in warning_text


def _derive_confidence(payload: dict[str, Any], compact_summary: dict[str, Any]) -> str:
    for value in (payload.get("confidence"), compact_summary.get("confidence")):
        text = str(value or "").strip()
        if text:
            return text
    if _as_list(payload.get("matches")) or _as_list(payload.get("compact_results")):
        return "medium"
    status = str(payload.get("status") or compact_summary.get("status") or "").strip().lower()
    if status == "ambiguous":
        return "low"
    if status in {"found", "ok"}:
        return "medium"
    return "low"


def _derive_warnings(payload: dict[str, Any], compact_summary: dict[str, Any]) -> list[str]:
    return _dedupe_strings([
        *_as_list(payload.get("warnings")),
        *_as_list(compact_summary.get("warnings")),
    ], limit=8)


def _derive_top_files(payload: dict[str, Any], compact_summary: dict[str, Any]) -> list[str]:
    candidates: list[Any] = []
    candidates.extend(_as_list(compact_summary.get("top_files")))
    candidates.extend(_as_list(compact_summary.get("app_files")))
    for item in _as_list(payload.get("compact_results"))[:8]:
        if isinstance(item, dict):
            candidates.append(item.get("file") or item.get("file_path"))
    for item in _as_list(payload.get("matches"))[:8]:
        if isinstance(item, dict):
            candidates.append(item.get("file") or item.get("file_path"))
    for item in _as_list(payload.get("snippet_results"))[:8]:
        if isinstance(item, dict):
            candidates.append(item.get("file") or item.get("file_path"))
    return _dedupe_strings(candidates, limit=8)


def _derive_top_symbols(payload: dict[str, Any], compact_summary: dict[str, Any]) -> list[str]:
    candidates: list[Any] = []
    candidates.extend(_as_list(compact_summary.get("top_symbols")))
    for item in _as_list(payload.get("matches"))[:8]:
        if isinstance(item, dict):
            candidates.append(item.get("qualified_name") or item.get("name") or item.get("symbol"))
    for item in _as_list(payload.get("compact_results"))[:8]:
        if isinstance(item, dict):
            candidates.append(item.get("target") or item.get("qualified_name") or item.get("name"))
    if payload.get("resolved_target"):
        candidates.append(payload.get("resolved_target"))
    return _dedupe_strings(candidates, limit=8)


def _derive_next_tools(payload: dict[str, Any], compact_summary: dict[str, Any]) -> list[dict[str, str]]:
    existing = _as_list(payload.get("next_tools")) or _as_list(compact_summary.get("next_tools"))
    normalized: list[dict[str, str]] = []
    for item in existing:
        if isinstance(item, dict) and str(item.get("tool") or "").strip():
            normalized.append({
                "tool": str(item.get("tool") or "").strip(),
                "why": str(item.get("why") or "").strip(),
            })
    if normalized:
        return normalized[:6]
    target = _render_target(payload.get("target") or compact_summary.get("target") or "")
    task = str(payload.get("task") or "").strip()
    suggested: list[dict[str, str]] = []
    if target and (_as_list(payload.get("matches")) or payload.get("resolved_target")):
        suggested.append({"tool": "get_source_context", "why": "Read concrete source snippets for the resolved target."})
        suggested.append({"tool": "unified_context", "why": "Inspect nearby callers, callees, and dependencies."})
    if task:
        suggested.append({"tool": "resolve_target", "why": "Pin broad search results to an exact symbol before graph-heavy follow-up."})
    if compact_summary.get("changed_file_count") or compact_summary.get("changed_symbol_count"):
        suggested.append({"tool": "suggest_tests_for_change", "why": "Pick the most relevant tests for the current edits."})
    return suggested[:4]


def _normalize_contract(payload: dict[str, Any]) -> dict[str, Any]:
    compact_summary = payload.get("compact_summary", {})
    if not isinstance(compact_summary, dict):
        compact_summary = {}
    status = _derive_status(payload, compact_summary)
    warnings = _derive_warnings(payload, compact_summary)
    confidence = _derive_confidence(payload, compact_summary)
    top_files = _derive_top_files(payload, compact_summary)
    top_symbols = _derive_top_symbols(payload, compact_summary)
    next_tools = _derive_next_tools(payload, compact_summary)
    partial = _derive_partial(payload, compact_summary, status)
    enriched_summary = dict(compact_summary)
    enriched_summary.setdefault("status", status)
    enriched_summary["warnings"] = warnings
    enriched_summary["confidence"] = confidence
    enriched_summary["top_files"] = top_files
    enriched_summary["top_symbols"] = top_symbols
    enriched_summary["next_tools"] = next_tools
    enriched_summary["partial"] = partial
    enriched = dict(payload)
    enriched["status"] = status
    enriched["warnings"] = warnings
    enriched["confidence"] = confidence
    enriched["top_files"] = top_files
    enriched["top_symbols"] = top_symbols
    enriched["next_tools"] = next_tools
    enriched["partial"] = partial
    enriched["compact_summary"] = enriched_summary
    return enriched


def _format_summary_lines(payload: dict[str, Any]) -> list[str]:
    compact_summary = payload.get("compact_summary", {})
    if not isinstance(compact_summary, dict):
        compact_summary = {}
    target = _render_target(payload.get("target") or compact_summary.get("target") or "")
    lines: list[str] = []
    task = str(payload.get("task") or "")
    compact_results = payload.get("compact_results")
    compact_findings = payload.get("compact_findings")
    compact_analyses = payload.get("compact_analyses")
    matches = payload.get("matches")
    symbol_matches = payload.get("symbol_matches")
    snippet_results = payload.get("snippet_results")
    if task and isinstance(compact_results, list):
        lines.append(f"Search task: {task}")
        backend = payload.get("embedding_backend")
        if backend:
            lines.append(f"Embedding backend: {backend}")
        lines.append(f"Result count: {len(compact_results)}")
        for item in compact_results[:5]:
            if not isinstance(item, dict):
                continue
            hit_target = item.get("target") or item.get("file") or "unknown"
            file_path = item.get("file") or ""
            confidence = item.get("confidence") or "unknown"
            why = item.get("why_relevant") or "semantic match"
            lines.append(f"Hit: {hit_target} [{confidence}] - {why}")
            if file_path:
                lines.append(f"  File: {file_path}")
        return lines
    if target and (isinstance(compact_findings, list) or isinstance(compact_analyses, list)):
        lines.append(f"Review target: {target}")
        if isinstance(compact_findings, list):
            lines.append(f"Finding count: {len(compact_findings)}")
            for item in compact_findings[:5]:
                if not isinstance(item, dict):
                    continue
                title = item.get("title") or "Untitled finding"
                severity = item.get("severity") or "unknown"
                category = item.get("category") or ""
                line_range = item.get("line_range") or []
                suffix = f" [{severity}]"
                if category:
                    suffix += f" {category}"
                lines.append(f"Finding: {title}{suffix}")
                if isinstance(line_range, list) and line_range:
                    lines.append(f"  Lines: {line_range[0]}-{line_range[-1]}")
        if isinstance(compact_analyses, list):
            lines.append(f"Analysis count: {len(compact_analyses)}")
            for item in compact_analyses[:3]:
                if not isinstance(item, dict):
                    continue
                agent_type = item.get("agent_type") or "agent"
                model_name = item.get("model_name") or "unknown-model"
                summary = str(item.get("summary") or "").strip()
                lines.append(f"Analysis: {agent_type} via {model_name}")
                if summary:
                    lines.append(f"  Summary: {summary[:180]}")
        return lines
    if target and isinstance(matches, list):
        lines.append(f"Symbol target: {target}")
        lines.append(f"Match count: {len(matches)}")
        for item in matches[:5]:
            if not isinstance(item, dict):
                continue
            file_path = item.get("file") or item.get("file_path") or ""
            symbol = item.get("qualified_name") or item.get("symbol") or target
            kind = item.get("kind") or "symbol"
            start_line = item.get("start_line")
            end_line = item.get("end_line")
            lines.append(f"Match: {symbol} [{kind}]")
            if file_path:
                lines.append(f"  File: {file_path}")
            if start_line is not None or end_line is not None:
                lines.append(f"  Lines: {start_line}-{end_line}")
        return lines
    if target and (isinstance(symbol_matches, list) or isinstance(snippet_results, list)):
        lines.append(f"Source target: {target}")
        if isinstance(symbol_matches, list):
            lines.append(f"Symbol matches: {len(symbol_matches)}")
            for item in symbol_matches[:3]:
                if not isinstance(item, dict):
                    continue
                symbol = item.get("qualified_name") or item.get("name") or target
                file_path = item.get("file_path") or ""
                kind = item.get("kind") or "symbol"
                lines.append(f"Symbol: {symbol} [{kind}]")
                if file_path:
                    lines.append(f"  File: {file_path}")
        snippet_items = compact_results if isinstance(compact_results, list) else snippet_results
        if isinstance(snippet_items, list):
            lines.append(f"Snippet matches: {len(snippet_items)}")
            for item in snippet_items[:3]:
                if not isinstance(item, dict):
                    continue
                snippet_target = item.get("target") or item.get("file") or target
                file_path = item.get("file") or item.get("file_path") or ""
                chunk_kind = item.get("chunk_kind") or "chunk"
                lines.append(f"Snippet: {snippet_target} [{chunk_kind}]")
                if file_path:
                    lines.append(f"  File: {file_path}")
        return lines
    if target:
        lines.append(f"Target: {target}")
    answer = str(payload.get("answer") or "").strip()
    if answer:
        lines.append(f"Answer: {answer[:280]}")
    confidence = payload.get("confidence") or compact_summary.get("confidence")
    if confidence:
        lines.append(f"Confidence: {confidence}")
    symbol_count = payload.get("symbol_count")
    chunk_count = payload.get("chunk_count")
    finding_count = payload.get("finding_count")
    if any(value is not None for value in (symbol_count, chunk_count, finding_count)):
        count_bits = []
        if symbol_count is not None:
            count_bits.append(f"symbols={symbol_count}")
        if chunk_count is not None:
            count_bits.append(f"chunks={chunk_count}")
        if finding_count is not None:
            count_bits.append(f"findings={finding_count}")
        if count_bits:
            lines.append("File summary: " + ", ".join(count_bits))
    if "depth" in compact_summary or "mode" in compact_summary or "relation_filter" in compact_summary:
        depth = compact_summary.get("depth")
        mode = compact_summary.get("mode")
        relation_filter = compact_summary.get("relation_filter")
        parts = []
        if depth is not None:
            parts.append(f"depth={depth}")
        if mode:
            parts.append(f"mode={mode}")
        if relation_filter:
            parts.append(f"relation={relation_filter}")
        if parts:
            lines.append("Graph: " + ", ".join(parts))
    if "node_count" in compact_summary or "edge_count" in compact_summary:
        node_count = compact_summary.get("node_count")
        edge_count = compact_summary.get("edge_count")
        direct_edge_count = compact_summary.get("direct_edge_count")
        count_bits = []
        if node_count is not None:
            count_bits.append(f"nodes={node_count}")
        if edge_count is not None:
            count_bits.append(f"edges={edge_count}")
        if direct_edge_count is not None:
            count_bits.append(f"direct_edges={direct_edge_count}")
        if count_bits:
            lines.append("Counts: " + ", ".join(count_bits))
    if "route_count" in compact_summary or "file_count" in compact_summary:
        route_count = compact_summary.get("route_count")
        file_count = compact_summary.get("file_count")
        graph_edge_count = compact_summary.get("graph_edge_count")
        count_bits = []
        if route_count is not None:
            count_bits.append(f"routes={route_count}")
        if file_count is not None:
            count_bits.append(f"files={file_count}")
        if graph_edge_count is not None:
            count_bits.append(f"graph_edges={graph_edge_count}")
        if count_bits:
            lines.append("App context: " + ", ".join(count_bits))
    frontend_graph = compact_summary.get("frontend_graph") or payload.get("frontend_graph") or compact_summary.get("graph_signal") or payload.get("graph_signal")
    if isinstance(frontend_graph, dict) and frontend_graph:
        frontend_bits = []
        frontend_file_count = frontend_graph.get("frontend_file_count")
        if frontend_file_count is not None:
            frontend_bits.append(f"frontend_files={frontend_file_count}")
        frontend_graph_edge_count = frontend_graph.get("frontend_graph_edge_count")
        if frontend_graph_edge_count is None:
            frontend_graph_edge_count = frontend_graph.get("frontend_graph_hit_count")
        if frontend_graph_edge_count is not None:
            frontend_bits.append(f"frontend_graph={frontend_graph_edge_count}")
        if frontend_graph.get("has_indirect_frontend_path"):
            frontend_bits.append("indirect_frontend_path=yes")
        if frontend_bits:
            lines.append("Frontend graph: " + ", ".join(frontend_bits))
        top_frontend_files = frontend_graph.get("top_frontend_files")
        if not isinstance(top_frontend_files, list) or not top_frontend_files:
            top_frontend_files = frontend_graph.get("frontend_graph_files")
        if isinstance(top_frontend_files, list) and top_frontend_files:
            lines.append("Frontend files: " + ", ".join(str(value) for value in top_frontend_files[:5]))
        top_relations = frontend_graph.get("top_relations")
        if isinstance(top_relations, dict) and top_relations:
            lines.append("Frontend relations: " + ", ".join(f"{key}={value}" for key, value in list(top_relations.items())[:5]))
        summary = str(frontend_graph.get("summary") or "").strip()
        if summary:
            lines.append(f"Frontend summary: {summary}")
    if any(key in compact_summary for key in ("changed_file_count", "changed_symbol_count", "test_count", "snippet_count")):
        count_bits = []
        for key, label in (
            ("changed_file_count", "changed_files"),
            ("changed_symbol_count", "changed_symbols"),
            ("test_count", "tests"),
            ("snippet_count", "snippets"),
        ):
            value = compact_summary.get(key)
            if value is not None:
                count_bits.append(f"{label}={value}")
        risk = compact_summary.get("risk")
        if risk:
            count_bits.append(f"risk={risk}")
        if count_bits:
            lines.append("Workflow: " + ", ".join(count_bits))
    parser_counts = compact_summary.get("parser_counts")
    if isinstance(parser_counts, dict) and parser_counts:
        lines.append("Parsers: " + ", ".join(f"{key or 'unknown'}={value}" for key, value in list(parser_counts.items())[:6]))
    file_kinds = compact_summary.get("file_kinds")
    if isinstance(file_kinds, dict) and file_kinds:
        lines.append("File kinds: " + ", ".join(f"{key}={value}" for key, value in list(file_kinds.items())[:6]))
    db_tables = compact_summary.get("db_tables")
    if isinstance(db_tables, list) and db_tables:
        lines.append("DB tables: " + ", ".join(str(table) for table in db_tables[:8]))
    groups = compact_summary.get("groups")
    if isinstance(groups, dict) and groups:
        group_bits = []
        for name, value in groups.items():
            if not isinstance(value, dict):
                continue
            count = value.get("count")
            if count is not None:
                group_bits.append(f"{name}={count}")
        if group_bits:
            lines.append("Dependency groups: " + ", ".join(group_bits[:6]))
    for key, label in (
        ("top_symbols", "Top symbols"),
        ("top_findings", "Top findings"),
        ("top_defined_symbols", "Defined"),
        ("top_import_targets", "Imports"),
        ("top_call_targets", "Calls"),
        ("top_reference_targets", "References"),
        ("top_inbound_sources", "Dependents"),
        ("top_routes", "Routes"),
        ("top_files", "Files"),
        ("top_processes", "Processes"),
    ):
        values = compact_summary.get(key)
        if isinstance(values, list) and values:
            lines.append(f"{label}: {', '.join(str(value) for value in values[:5])}")
    top_neighbors = compact_summary.get("top_neighbors")
    if isinstance(top_neighbors, list) and top_neighbors:
        rendered = []
        for item in top_neighbors[:5]:
            if not isinstance(item, dict):
                continue
            node = item.get("node")
            edge_count = item.get("edge_count")
            if node:
                rendered.append(f"{node} ({edge_count})")
        if rendered:
            lines.append("Top neighbors: " + ", ".join(rendered))
    relation_breakdown = compact_summary.get("relation_breakdown")
    if isinstance(relation_breakdown, dict) and relation_breakdown:
        rendered = []
        for relation, value in relation_breakdown.items():
            if isinstance(value, dict):
                rendered.append(f"{relation}={value.get('count', 0)}")
        if rendered:
            lines.append("Relations: " + ", ".join(rendered[:6]))
    warnings = compact_summary.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings[:3]:
            lines.append(f"Warning: {warning}")
    return lines


def enrich_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"result": payload}
    payload = _strip_large_internal_fields(payload)
    enriched = _normalize_contract(payload)
    summary_lines = _format_summary_lines(enriched)
    enriched["summary_text"] = "\n".join(summary_lines) if summary_lines else ""
    enriched["highlights"] = summary_lines
    return enriched


def format_payload(payload: dict[str, Any]) -> str:
    enriched = enrich_payload(payload)
    summary_text = enriched.get("summary_text", "")
    if summary_text:
        return summary_text + "\n\nJSON:\n" + json.dumps(enriched, indent=2)
    return json.dumps(enriched, indent=2)
