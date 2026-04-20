from storage.kuzu_store import KuzuStore



def get_callers_and_callees(kuzu_store: KuzuStore, target: str) -> dict[str, object]:
    callers = kuzu_store.edges_for_target(target, relation="CALLS")
    callees = kuzu_store.edges_for_source(target, relation="CALLS")
    return {
        "target": target,
        "callers": callers,
        "callees": callees,
        "compact_summary": {
            "target": target,
            "caller_count": len(callers),
            "callee_count": len(callees),
            "top_callers": callers[:5],
            "top_callees": callees[:5],
        },
    }



def get_graph_neighborhood(kuzu_store: KuzuStore, target: str, depth: int = 1) -> dict[str, object]:
    neighborhood = kuzu_store.neighborhood(target=target, depth=depth)
    return {
        **neighborhood,
        "compact_summary": {
            "target": target,
            "depth": depth,
            "node_count": len(neighborhood.get("nodes", [])),
            "edge_count": len(neighborhood.get("edges", [])),
            "top_edges": neighborhood.get("edges", [])[:8],
        },
    }
