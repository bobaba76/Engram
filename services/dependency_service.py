from storage.kuzu_store import KuzuStore


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


def get_dependencies(kuzu_store: KuzuStore, target: str) -> dict[str, object]:
    inbound = kuzu_store.edges_for_target(target)
    outbound = kuzu_store.edges_for_source(target)
    defines = kuzu_store.edges_for_source(target, relation="DEFINES")
    imports = kuzu_store.edges_for_source(target, relation="IMPORTS")
    calls = kuzu_store.edges_for_source(target, relation="CALLS")
    references = kuzu_store.edges_for_source(target, relation="REFERENCES")
    return {
        "target": target,
        "inbound": inbound,
        "outbound": outbound,
        "defines": defines,
        "imports": imports,
        "calls": calls,
        "references": references,
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
            "groups": {
                "defines": {"count": len(defines), "sample": _sample_edges(defines)},
                "imports": {"count": len(imports), "sample": _sample_edges(imports)},
                "calls": {"count": len(calls), "sample": _sample_edges(calls)},
                "references": {"count": len(references), "sample": _sample_edges(references)},
                "dependents": {"count": len(inbound), "sample": _sample_edges(inbound)},
            },
        },
    }
