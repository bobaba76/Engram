from services.god_nodes_service import god_nodes


class _Duck:
    """Minimal DuckDB stand-in: serves symbol names + file aggregates."""

    def __init__(self, symbols):
        self._symbols = symbols

    def execute(self, query, params=None):
        q = query.strip().lower()
        if q.startswith("select qualified_name"):
            return _Rows([(s["qualified_name"],) for s in self._symbols])
        if "group by file_path" in q:
            counts: dict[str, int] = {}
            for s in self._symbols:
                counts[s["file_path"]] = counts.get(s["file_path"], 0) + 1
            rows = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
            limit = params[0] if params else len(rows)
            return _Rows([(fp, cnt) for fp, cnt in rows[:limit]])
        return _Rows([])


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Kuzu:
    """In-memory graph that supports both per-edge and bulk aggregation queries."""

    def __init__(self, edges):
        self.edges = edges
        # Collect the set of relations present in the test edges.
        self._relations = {e["relation"] for e in edges}

    def available_relations(self):
        return frozenset(self._relations)

    def _safe_execute(self, query, params=None):
        # Parse the Cypher aggregation query and compute results from the
        # in-memory edge list.
        q = query.strip()
        # MATCH (s1:Symbol)-[:REL]->(s2:Symbol) RETURN s1.qualified_name, COUNT(*)
        # or  MATCH (f:File)-[:DEFINES]->(s:Symbol) RETURN s.qualified_name, COUNT(*)
        import re

        m = re.match(
            r"MATCH \(\w+:\w+\)-\[:(\w+)\]->\(\w+:\w+\) RETURN (\w+)\.qualified_name, COUNT\(\*\)",
            q,
        )
        if m:
            rel = m.group(1)
            return_var = m.group(2)
            # Determine direction: if the RETURN variable is the FROM node
            # (s1/source), it's outbound degree; if it's the TO node (s2/target),
            # it's inbound degree. We check by seeing which variable name
            # appears in the RETURN clause vs the pattern.
            if return_var in ("s1", "source", "f"):
                # Outbound: group by source
                counts: dict[str, int] = {}
                for e in self.edges:
                    if e["relation"] == rel:
                        counts[e["source"]] = counts.get(e["source"], 0) + 1
                return _AggRows([(k, v) for k, v in counts.items()])
            else:
                # Inbound: group by target
                counts = {}
                for e in self.edges:
                    if e["relation"] == rel:
                        counts[e["target"]] = counts.get(e["target"], 0) + 1
                return _AggRows([(k, v) for k, v in counts.items()])
        return _AggRows([])

    def edges_for_target(self, target, relation=None):
        return [
            e for e in self.edges
            if e["target"] == target and (relation is None or e["relation"] == relation)
        ]

    def edges_for_source(self, source, relation=None):
        return [
            e for e in self.edges
            if e["source"] == source and (relation is None or e["relation"] == relation)
        ]


class _AggRows:
    """Mimics kuzu query result for aggregation queries."""

    def __init__(self, rows):
        self._rows = rows

    def get_all(self):
        return self._rows


def test_god_nodes_ranks_by_total_degree():
    symbols = [
        {"qualified_name": "hub.fn", "file_path": "src/hub.py"},
        {"qualified_name": "leaf.a", "file_path": "src/a.py"},
        {"qualified_name": "leaf.b", "file_path": "src/b.py"},
    ]
    edges = [
        # hub.fn has 5 inbound + 2 outbound = 7 total
        *({"source": f"caller.{i}", "relation": "CALLS", "target": "hub.fn"} for i in range(5)),
        {"source": "hub.fn", "relation": "CALLS", "target": "leaf.a"},
        {"source": "hub.fn", "relation": "CALLS", "target": "leaf.b"},
    ]
    payload = god_nodes(_Duck(symbols), _Kuzu(edges), limit=10, min_degree=5)
    assert payload["symbols"][0]["node"] == "hub.fn"
    assert payload["symbols"][0]["total_degree"] == 7
    assert payload["symbols"][0]["is_god_node"] is True
    assert payload["god_node_count"] == 1


def test_god_nodes_respects_limit():
    symbols = [{"qualified_name": f"n.{i}", "file_path": "x.py"} for i in range(50)]
    edges = [
        {"source": f"n.{i}", "relation": "CALLS", "target": f"n.{(i + 1) % 50}"}
        for i in range(50)
    ]
    payload = god_nodes(_Duck(symbols), _Kuzu(edges), limit=5)
    assert len(payload["symbols"]) == 5


def test_god_nodes_skips_zero_degree_symbols():
    symbols = [
        {"qualified_name": "orphan.fn", "file_path": "x.py"},
        {"qualified_name": "connected.fn", "file_path": "y.py"},
    ]
    edges = [{"source": "connected.fn", "relation": "CALLS", "target": "other"}]
    payload = god_nodes(_Duck(symbols), _Kuzu(edges), limit=10)
    nodes = [item["node"] for item in payload["symbols"]]
    assert "orphan.fn" not in nodes
    assert "connected.fn" in nodes


def test_god_nodes_include_files_ranks_files_by_symbol_count():
    symbols = [
        {"qualified_name": "big.a", "file_path": "big.py"},
        {"qualified_name": "big.b", "file_path": "big.py"},
        {"qualified_name": "big.c", "file_path": "big.py"},
        {"qualified_name": "small.a", "file_path": "small.py"},
    ]
    payload = god_nodes(_Duck(symbols), _Kuzu([]), limit=10, include_files=True, min_degree=2)
    assert payload["file_hubs"]
    assert payload["file_hubs"][0]["node"] == "big.py"
    assert payload["file_hubs"][0]["total_degree"] == 3


def test_god_nodes_emits_warning_when_god_nodes_present():
    symbols = [{"qualified_name": "hub", "file_path": "x.py"}]
    edges = [{"source": f"c{i}", "relation": "CALLS", "target": "hub"} for i in range(50)]
    payload = god_nodes(_Duck(symbols), _Kuzu(edges), limit=10, min_degree=40)
    assert any("god-node" in w for w in payload["warnings"])
