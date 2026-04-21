import json
from typing import Any


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _format_summary_lines(payload: dict[str, Any]) -> list[str]:
    compact_summary = payload.get("compact_summary", {})
    if not isinstance(compact_summary, dict):
        compact_summary = {}
    target = str(payload.get("target") or compact_summary.get("target") or "")
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
        if isinstance(compact_results, list):
            lines.append(f"Snippet matches: {len(compact_results)}")
            for item in compact_results[:3]:
                if not isinstance(item, dict):
                    continue
                snippet_target = item.get("target") or item.get("file") or target
                file_path = item.get("file") or ""
                chunk_kind = item.get("chunk_kind") or "chunk"
                lines.append(f"Snippet: {snippet_target} [{chunk_kind}]")
                if file_path:
                    lines.append(f"  File: {file_path}")
        return lines
    if target:
        lines.append(f"Target: {target}")
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
    summary_lines = _format_summary_lines(payload)
    enriched = dict(payload)
    enriched["summary_text"] = "\n".join(summary_lines) if summary_lines else ""
    enriched["highlights"] = summary_lines
    return enriched


def format_payload(payload: dict[str, Any]) -> str:
    enriched = enrich_payload(payload)
    summary_text = enriched.get("summary_text", "")
    if summary_text:
        return summary_text + "\n\nJSON:\n" + json.dumps(enriched, indent=2)
    return json.dumps(enriched, indent=2)
