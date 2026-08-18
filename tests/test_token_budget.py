"""Tests for token-budget discipline in verbose graph tools."""
from services.graph_service import get_callers_and_callees, get_file_dependencies


class _Kuzu:
    def __init__(self, edges):
        self.edges = edges

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

    def neighborhood(self, target, depth=1):
        nodes = {target}
        edges = []
        for e in self.edges:
            if e["source"] == target or e["target"] == target:
                edges.append(e)
                nodes.add(e["source"])
                nodes.add(e["target"])
        return {"nodes": sorted(nodes), "edges": edges}


class _Duck:
    def __init__(self, symbols):
        self._symbols = symbols

    def fetch_symbols_for_file(self, file_path):
        return [s for s in self._symbols if s["file_path"] == file_path]

    def execute(self, query, params=None):
        # _symbol_to_file_map uses IN (?, ?) — return rows matching the
        # qualified_name param values.
        if params and isinstance(params, list):
            return _Rows([tuple([s["qualified_name"], s["file_path"]]) for s in self._symbols if s["qualified_name"] in params])
        return _Rows([])


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


def test_callers_and_callees_caps_per_relation_edge_lists():
    """When a relation has >edge_cap edges, the full list is truncated and a flag is set."""
    edges = [
        {"source": f"caller.{i}", "relation": "CALLS", "target": "hub.fn"} for i in range(40)
    ] + [
        {"source": "hub.fn", "relation": "CALLS", "target": "callee.x"}
    ]
    payload = get_callers_and_callees(_Kuzu(edges), "hub.fn", edge_cap=10)
    calls_ref = payload["categorized_references"]["CALLS"]
    assert calls_ref["incoming_count"] == 40
    assert len(calls_ref["incoming"]) == 10  # capped
    assert calls_ref["incoming_truncated"] is True


def test_callers_and_callees_compact_mode_drops_full_lists():
    """compact=true drops categorized_references and related_symbols_by_relation."""
    edges = [
        {"source": "a", "relation": "CALLS", "target": "b"},
        {"source": "b", "relation": "CALLS", "target": "c"},
    ]
    payload = get_callers_and_callees(_Kuzu(edges), "b", compact=True)
    assert "categorized_references" not in payload
    assert "related_symbols_by_relation" not in payload
    # compact_summary still has the counts and top samples.
    assert payload["compact_summary"]["caller_count"] == 1
    assert payload["compact_summary"]["callee_count"] == 1


def test_callers_and_callees_default_keeps_full_payload_for_small_targets():
    """Small targets should still return the full categorized_references by default."""
    edges = [{"source": "a", "relation": "CALLS", "target": "b"}]
    payload = get_callers_and_callees(_Kuzu(edges), "b")
    assert "categorized_references" in payload
    assert "related_symbols_by_relation" in payload


def test_get_file_dependencies_caps_edges_per_file_sample():
    symbols = [
        {"qualified_name": "mod.fn", "file_path": "src/mod.py", "kind": "function"},
    ] + [
        {"qualified_name": f"dep.caller{i}", "file_path": f"src/dep{i}.py", "kind": "function"}
        for i in range(5)
    ]
    edges = [
        {"source": f"dep.caller{i}", "relation": "CALLS", "target": "mod.fn"}
        for i in range(5)
    ]
    payload = get_file_dependencies(_Duck(symbols), _Kuzu(edges), "src/mod.py", edges_per_file=2)
    # Each inbound file should have at most 2 edges in its sample.
    for entry in payload["inbound_files"]:
        assert len(entry["edges"]) <= 2
        assert entry["edge_count"] == 1  # one edge per file in this fixture


def test_callers_and_callees_related_symbols_correct_when_edges_capped():
    """all_related_symbol_count must reflect FULL edge count, not capped sample.

    Regression test: when a relation has >edge_cap edges, the capped
    incoming/outgoing lists omit some edges. The related_symbols_by_relation
    map and all_related_symbol_count must still reflect the full set.
    """
    edges = [
        {"source": f"caller.{i}", "relation": "CALLS", "target": "hub.fn"}
        for i in range(40)
    ] + [
        {"source": "hub.fn", "relation": "CALLS", "target": f"callee.{i}"}
        for i in range(30)
    ]
    payload = get_callers_and_callees(_Kuzu(edges), "hub.fn", edge_cap=10)
    # 40 callers + 30 callees = 70 related symbols (all unique).
    assert payload["compact_summary"]["all_related_symbol_count"] == 70
    assert len(payload["related_symbols_by_relation"]["CALLS"]) == 70
    # But the capped incoming list only has 10 entries.
    assert len(payload["categorized_references"]["CALLS"]["incoming"]) == 10
    assert len(payload["categorized_references"]["CALLS"]["outgoing"]) == 10
