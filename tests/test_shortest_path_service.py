from services.shortest_path_service import shortest_path


class _Duck:
    """Minimal DuckDB stand-in: maps target strings to symbol rows."""

    def __init__(self, symbols):
        self._symbols = symbols

    def fetch_symbols_for_target(self, target, limit=1):
        needle = (target or "").lower()
        return [
            s for s in self._symbols
            if needle in s["qualified_name"].lower() or needle in s.get("name", "").lower()
        ][:limit]

    def fetch_symbol_by_uid(self, uid):
        return next((s for s in self._symbols if s.get("uid") == uid), None)


class _Kuzu:
    """In-memory graph for BFS testing."""

    def __init__(self, edges):
        self.edges = edges

    def edges_for_source(self, source, relation=None):
        return [
            e for e in self.edges
            if e["source"] == source and (relation is None or e["relation"] == relation)
        ]

    def edges_for_target(self, target, relation=None):
        return [
            e for e in self.edges
            if e["target"] == target and (relation is None or e["relation"] == relation)
        ]

    def available_relations(self):
        return frozenset(e["relation"] for e in self.edges)

    def _safe_execute(self, query, parameters=None):
        # Mock does not support Cypher; BFS fallback handles pathfinding.
        return None


def _make_stores():
    symbols = [
        {"name": "embedder", "qualified_name": "app.embedder", "file_path": "indexing/embedder.py", "kind": "function"},
        {"name": "symbol_extractor", "qualified_name": "app.symbol_extractor", "file_path": "indexing/symbol_extractor.py", "kind": "function"},
        {"name": "pipeline", "qualified_name": "app.pipeline", "file_path": "app/pipeline.py", "kind": "function"},
    ]
    edges = [
        {"source": "app.embedder", "relation": "CALLS", "target": "app.pipeline"},
        {"source": "app.pipeline", "relation": "CALLS", "target": "app.symbol_extractor"},
    ]
    return _Duck(symbols), _Kuzu(edges)


def test_shortest_path_returns_direct_two_hop_chain():
    duck, kuzu = _make_stores()
    payload = shortest_path(duck, kuzu, source="app.embedder", target="app.symbol_extractor")
    assert payload["status"] == "found"
    assert payload["hop_count"] == 2
    assert payload["path"] == [
        {"source": "app.embedder", "relation": "CALLS", "target": "app.pipeline"},
        {"source": "app.pipeline", "relation": "CALLS", "target": "app.symbol_extractor"},
    ]
    assert payload["compact_summary"]["hop_count"] == 2


def test_shortest_path_works_in_either_direction():
    duck, kuzu = _make_stores()
    payload = shortest_path(duck, kuzu, source="app.symbol_extractor", target="app.embedder")
    assert payload["status"] == "found"
    assert payload["hop_count"] == 2
    # Reversed traversal should still name the original source/target on each hop.
    assert payload["path"][0]["relation"] == "CALLS"


def test_shortest_path_reports_no_path_when_disconnected():
    duck, kuzu = _make_stores()
    # Add an unrelated isolated node.
    duck._symbols.append({"name": "orphan", "qualified_name": "orphan.node", "file_path": "x.py", "kind": "function"})
    payload = shortest_path(duck, kuzu, source="app.embedder", target="orphan.node", max_hops=4)
    assert payload["status"] == "no_path"
    assert payload["hop_count"] == 0
    assert payload["path"] == []


def test_shortest_path_same_node_warning():
    duck, kuzu = _make_stores()
    payload = shortest_path(duck, kuzu, source="app.embedder", target="app.embedder")
    assert payload["status"] == "same_node"
    assert any("same node" in w for w in payload["warnings"])


def test_shortest_path_source_not_found():
    duck, kuzu = _make_stores()
    payload = shortest_path(duck, kuzu, source="does.not.exist", target="app.embedder")
    assert payload["status"] == "source_not_found"


def test_shortest_path_respects_max_hops():
    duck, kuzu = _make_stores()
    # 2-hop path exists; capping at 1 hop should report no_path.
    payload = shortest_path(duck, kuzu, source="app.embedder", target="app.symbol_extractor", max_hops=1)
    assert payload["status"] == "no_path"


def test_shortest_path_capped_on_dense_graph():
    """When BFS hits the node-visited cap, status should be 'capped' with a warning.

    Builds a graph where each node has unique neighbors (no sharing), so the
    total unique reachable node count grows linearly with edges. With >1000
    unique reachable nodes and a disconnected target, BFS should exhaust the
    visited cap and return 'capped' rather than exploring forever.
    """
    # n0 -> n1..n200 (200 neighbors, all unique)
    # n1..n200 each -> 5 unique nodes (n201..n1200), 1000 unique nodes at depth 2
    # Total: 1 + 200 + 1000 = 1201 reachable nodes, exceeding the 1000 cap
    symbols = [{"name": f"n{i}", "qualified_name": f"n{i}", "file_path": "x.py", "kind": "function"} for i in range(1300)]
    edges = []
    # n0 -> n1..n200
    for j in range(1, 201):
        edges.append({"source": "n0", "relation": "CALLS", "target": f"n{j}"})
    # n1..n200 each -> 5 unique nodes
    idx = 201
    for i in range(1, 201):
        for _ in range(5):
            edges.append({"source": f"n{i}", "relation": "CALLS", "target": f"n{idx}"})
            idx += 1
    # n1299 is completely disconnected — target it
    duck = _Duck(symbols)
    kuzu = _Kuzu(edges)
    payload = shortest_path(duck, kuzu, source="n0", target="n1299", max_hops=5)
    # BFS should hit the 1000-node visited cap and return 'capped'
    assert payload["status"] == "capped"
    assert any("terminated early" in w for w in payload["warnings"])
