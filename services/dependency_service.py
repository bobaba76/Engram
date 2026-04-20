from storage.kuzu_store import KuzuStore


def get_dependencies(kuzu_store: KuzuStore, target: str) -> dict[str, object]:
    inbound = kuzu_store.edges_for_target(target)
    outbound = kuzu_store.edges_for_source(target)
    imports = kuzu_store.edges_for_source(target, relation="IMPORTS")
    calls = kuzu_store.edges_for_source(target, relation="CALLS")
    references = kuzu_store.edges_for_source(target, relation="REFERENCES")
    return {
        "target": target,
        "inbound": inbound,
        "outbound": outbound,
        "imports": imports,
        "calls": calls,
        "references": references,
        "compact_summary": {
            "target": target,
            "inbound_count": len(inbound),
            "outbound_count": len(outbound),
            "import_count": len(imports),
            "call_count": len(calls),
            "reference_count": len(references),
            "top_inbound": inbound[:5],
            "top_outbound": outbound[:5],
        },
    }
