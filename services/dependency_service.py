from storage.kuzu_store import KuzuStore

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


def get_dependencies(kuzu_store: KuzuStore, target: str) -> dict[str, object]:
    inbound = kuzu_store.edges_for_target(target)
    outbound = kuzu_store.edges_for_source(target)
    defines = kuzu_store.edges_for_source(target, relation="DEFINES")
    imports = kuzu_store.edges_for_source(target, relation="IMPORTS")
    calls = kuzu_store.edges_for_source(target, relation="CALLS")
    references = kuzu_store.edges_for_source(target, relation="REFERENCES")
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
