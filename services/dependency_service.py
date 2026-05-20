from storage.kuzu_store import KuzuStore
from services.risk_profiles import path_risk_hints

RAW_EDGE_LIMIT = 80


def _distinct_nodes(edges: list[dict[str, object]], key: str, limit: int = 8) -> list[str]:
    seen: list[str] = []
    for edge in edges:
        value = str(edge.get(key, ""))
        if not value or value in seen:
            continue
        seen.append(value)
        if len(seen) >= limit:
            break
    return seen


def _sample_edges(edges: list[dict[str, object]], limit: int = 5) -> list[dict[str, object]]:
    return edges[:limit]


def _relation_counts(edges: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        relation = str(edge.get("relation", "") or "UNKNOWN")
        counts[relation] = counts.get(relation, 0) + 1
    return counts


def _top_sources_by_relation(edges: list[dict[str, object]], limit: int = 12) -> list[dict[str, object]]:
    counts: dict[tuple[str, str], int] = {}
    for edge in edges:
        source = str(edge.get("source", "") or "")
        relation = str(edge.get("relation", "") or "")
        if not source:
            continue
        key = (source, relation)
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0][1], item[0][0]))
    return [{"source": source, "relation": relation, "edge_count": count} for (source, relation), count in ranked[:limit]]


def _looks_like_native_header(target: str) -> bool:
    normalized = str(target or "").replace("\\", "/").lower()
    return normalized.endswith((".h", ".hh", ".hpp", ".hxx", ".inc"))


def _unique_strings(values: list[object], limit: int = 20) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def _files_from_symbol_edges(edges: list[dict[str, object]], key: str = "source_file", limit: int = 40) -> list[str]:
    return _unique_strings([edge.get(key, "") for edge in edges], limit=limit)


def _include_edges_for_target(kuzu_store: KuzuStore, target: str, limit: int = 200) -> list[dict[str, object]]:
    edges: list[dict[str, object]] = []
    if _looks_like_native_header(target) and hasattr(kuzu_store, "symbol_edges_for_target_file"):
        edges.extend(kuzu_store.symbol_edges_for_target_file(target, relation="INCLUDES", limit=limit))
    if hasattr(kuzu_store, "symbol_edges_for_target_symbol"):
        edges.extend(kuzu_store.symbol_edges_for_target_symbol(target, relation="INCLUDES", limit=limit))
    if not edges:
        raw_edges = kuzu_store.edges_for_target(target, relation="INCLUDES")
        edges.extend({**edge, "source_file": "", "target_file": target if _looks_like_native_header(target) else ""} for edge in raw_edges)
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        key = (str(edge.get("source", "")), str(edge.get("relation", "")), str(edge.get("target", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped[:limit]


def _indirect_include_edges(kuzu_store: KuzuStore, direct_edges: list[dict[str, object]], limit: int = 200) -> list[dict[str, object]]:
    indirect: list[dict[str, object]] = []
    seen_symbols = {str(edge.get("source", "")) for edge in direct_edges if edge.get("source")}
    frontier = list(seen_symbols)
    while frontier and len(indirect) < limit:
        symbol = frontier.pop(0)
        if not symbol:
            continue
        if hasattr(kuzu_store, "symbol_edges_for_target_symbol"):
            incoming = kuzu_store.symbol_edges_for_target_symbol(symbol, relation="INCLUDES", limit=limit)
        else:
            incoming = kuzu_store.edges_for_target(symbol, relation="INCLUDES")
        for edge in incoming:
            source = str(edge.get("source", ""))
            if not source or source in seen_symbols:
                continue
            seen_symbols.add(source)
            frontier.append(source)
            indirect.append(edge)
            if len(indirect) >= limit:
                break
    return indirect[:limit]


def _native_header_blast_radius(kuzu_store: KuzuStore, target: str) -> dict[str, object]:
    direct_edges = _include_edges_for_target(kuzu_store, target)
    indirect_edges = _indirect_include_edges(kuzu_store, direct_edges)
    direct_files = _files_from_symbol_edges(direct_edges)
    indirect_files = [file_path for file_path in _files_from_symbol_edges(indirect_edges) if file_path not in set(direct_files)]
    hints = path_risk_hints(target) if _looks_like_native_header(target) else []
    risk = "HIGH" if any(hint in hints for hint in ("global embedded C contract header", "device/vendor register header", "public/native header surface", "embedded/native assembly startup or include path")) or len(direct_files) >= 5 else "MEDIUM" if direct_files else "LOW"
    return {
        "target": target,
        "risk": risk,
        "risk_factors": hints[:8],
        "direct_include_count": len(direct_edges),
        "direct_including_files": direct_files[:20],
        "indirect_include_count": len(indirect_edges),
        "indirect_including_files": indirect_files[:20],
        "top_including_symbols": _unique_strings([edge.get("source", "") for edge in direct_edges], limit=12),
        "summary": f"{target} is directly included by {len(direct_files)} file(s) and indirectly reached by {len(indirect_files)} additional file(s).",
        "truncated": len(direct_edges) >= 200 or len(indirect_edges) >= 200,
    }


def get_dependencies(kuzu_store: KuzuStore, target: str) -> dict[str, object]:
    inbound = kuzu_store.edges_for_target(target)
    outbound = kuzu_store.edges_for_source(target)
    defines = kuzu_store.edges_for_source(target, relation="DEFINES")
    imports = kuzu_store.edges_for_source(target, relation="IMPORTS")
    calls = kuzu_store.edges_for_source(target, relation="CALLS")
    references = kuzu_store.edges_for_source(target, relation="REFERENCES")
    native_header_blast_radius = _native_header_blast_radius(kuzu_store, target)
    return {
        "target": target,
        "inbound": inbound[:RAW_EDGE_LIMIT],
        "outbound": outbound[:RAW_EDGE_LIMIT],
        "inbound_total_count": len(inbound),
        "outbound_total_count": len(outbound),
        "truncated": len(inbound) > RAW_EDGE_LIMIT or len(outbound) > RAW_EDGE_LIMIT,
        "defines": defines,
        "imports": imports,
        "calls": calls,
        "references": references,
        "blast_radius": {
            "dependent_count": len(inbound),
            "outbound_dependency_count": len(outbound),
            "inbound_relations": _relation_counts(inbound),
            "outbound_relations": _relation_counts(outbound),
            "top_dependents": _top_sources_by_relation(inbound),
            "summary": f"{target} has {len(inbound)} inbound dependency edge(s) and {len(outbound)} outbound dependency edge(s).",
        },
        "native_header_blast_radius": native_header_blast_radius,
        "compact_summary": {
            "target": target,
            "inbound_count": len(inbound),
            "outbound_count": len(outbound),
            "define_count": len(defines),
            "import_count": len(imports),
            "call_count": len(calls),
            "reference_count": len(references),
            "top_inbound": _sample_edges(inbound),
            "top_outbound": _sample_edges(outbound),
            "top_defined_symbols": _distinct_nodes(defines, "target"),
            "top_import_targets": _distinct_nodes(imports, "target"),
            "top_call_targets": _distinct_nodes(calls, "target"),
            "top_reference_targets": _distinct_nodes(references, "target"),
            "top_inbound_sources": _distinct_nodes(inbound, "source"),
            "inbound_relations": _relation_counts(inbound),
            "outbound_relations": _relation_counts(outbound),
            "top_dependents_by_count": _top_sources_by_relation(inbound, limit=8),
            "native_header_blast_radius": {
                "risk": native_header_blast_radius.get("risk", "LOW"),
                "direct_include_count": native_header_blast_radius.get("direct_include_count", 0),
                "direct_including_files": native_header_blast_radius.get("direct_including_files", [])[:8],
                "indirect_include_count": native_header_blast_radius.get("indirect_include_count", 0),
                "risk_factors": native_header_blast_radius.get("risk_factors", [])[:5],
            },
            "truncated": len(inbound) > RAW_EDGE_LIMIT or len(outbound) > RAW_EDGE_LIMIT,
            "groups": {
                "defines": {"count": len(defines), "sample": _sample_edges(defines)},
                "imports": {"count": len(imports), "sample": _sample_edges(imports)},
                "calls": {"count": len(calls), "sample": _sample_edges(calls)},
                "references": {"count": len(references), "sample": _sample_edges(references)},
                "dependents": {"count": len(inbound), "sample": _sample_edges(inbound)},
            },
        },
    }
