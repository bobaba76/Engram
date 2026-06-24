"""Tests for community detection service."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from services.community_detection_service import (
    _build_adjacency,
    _compute_cohesion,
    _label_propagation,
    detect_communities,
    get_community_detail,
    get_symbol_community,
    list_communities,
)


def _mock_kuzu_store(edges_by_relation: dict[str, list[dict[str, str]]]) -> MagicMock:
    store = MagicMock()
    store.edges_for_relation = MagicMock(side_effect=lambda rel: edges_by_relation.get(rel, []))
    return store


def _mock_duckdb_store(
    communities_rows: list[tuple] | None = None,
    member_rows: list[tuple] | None = None,
    symbol_rows: list[tuple] | None = None,
) -> MagicMock:
    store = MagicMock()
    store.connection = MagicMock()
    store.execute = MagicMock()

    def execute_side_effect(query, params=None):
        q = query.strip().lower()
        if q.startswith("select qualified_name, file_path, kind, name, signature from symbols"):
            return MagicMock(fetchall=MagicMock(return_value=symbol_rows or []))
        if q.startswith("select file_path, kind from symbols"):
            return MagicMock(fetchall=MagicMock(return_value=symbol_rows or []))
        if q.startswith("select file_path from symbols"):
            return MagicMock(fetchall=MagicMock(return_value=symbol_rows or []))
        if "from communities" in q and "where community_id" in q:
            return MagicMock(fetchall=MagicMock(return_value=communities_rows or []))
        if "from community_members" in q:
            return MagicMock(fetchall=MagicMock(return_value=member_rows or []))
        if "from communities" in q:
            return MagicMock(fetchall=MagicMock(return_value=communities_rows or []))
        return MagicMock(fetchall=MagicMock(return_value=[]))

    store.execute = MagicMock(side_effect=execute_side_effect)
    return store


class TestLabelPropagation:
    def test_two_clusters(self):
        adjacency = {
            "a": {"b", "c"},
            "b": {"a", "c"},
            "c": {"a", "b"},
            "d": {"e", "f"},
            "e": {"d", "f"},
            "f": {"d", "e"},
        }
        nodes = sorted(adjacency.keys())
        labels = _label_propagation(adjacency, nodes)
        assert labels["a"] == labels["b"] == labels["c"]
        assert labels["d"] == labels["e"] == labels["f"]
        assert labels["a"] != labels["d"]

    def test_single_node_no_neighbours(self):
        adjacency = {"x": set()}
        labels = _label_propagation(adjacency, ["x"])
        # Single node keeps its initial label
        assert labels["x"] == 0

    def test_empty_graph(self):
        labels = _label_propagation({}, [])
        assert labels == {}


class TestBuildAdjacency:
    def test_builds_undirected_graph(self):
        edges = {
            "CALLS": [
                {"source": "mod.foo", "relation": "CALLS", "target": "mod.bar"},
            ],
            "IMPORTS": [
                {"source": "mod.baz", "relation": "IMPORTS", "target": "mod.bar"},
            ],
        }
        kuzu = _mock_kuzu_store(edges)
        adj = _build_adjacency(kuzu)
        assert "mod.bar" in adj["mod.foo"]
        assert "mod.foo" in adj["mod.bar"]
        assert "mod.bar" in adj["mod.baz"]
        assert "mod.baz" in adj["mod.bar"]

    def test_self_edges_excluded(self):
        edges = {
            "CALLS": [
                {"source": "mod.foo", "relation": "CALLS", "target": "mod.foo"},
            ],
        }
        kuzu = _mock_kuzu_store(edges)
        adj = _build_adjacency(kuzu)
        assert "mod.foo" not in adj.get("mod.foo", set())


class TestComputeCohesion:
    def test_fully_connected_community(self):
        adj = {"a": {"b"}, "b": {"a"}}
        cohesion = _compute_cohesion(["a", "b"], adj)
        assert cohesion == 1.0

    def test_half_external(self):
        adj = {"a": {"b", "c"}, "b": {"a", "c"}}
        cohesion = _compute_cohesion(["a", "b"], adj)
        # 2 internal, 2 external
        assert cohesion == 0.5

    def test_isolated(self):
        cohesion = _compute_cohesion(["x"], {})
        assert cohesion == 0.0


class TestDetectCommunities:
    def test_small_graph_returns_communities(self):
        edges = {
            "CALLS": [
                {"source": "mod.a", "relation": "CALLS", "target": "mod.b"},
                {"source": "mod.b", "relation": "CALLS", "target": "mod.c"},
                {"source": "mod.d", "relation": "CALLS", "target": "mod.e"},
                {"source": "mod.e", "relation": "CALLS", "target": "mod.f"},
            ],
        }
        kuzu = _mock_kuzu_store(edges)
        duckdb = MagicMock()
        duckdb.connection = MagicMock()
        duckdb.execute = MagicMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

        result = detect_communities(duckdb, kuzu)
        assert result["status"] == "ok"
        assert result["community_count"] >= 1
        assert "compact_summary" in result

    def test_too_small_graph_returns_warning(self):
        edges = {"CALLS": []}
        kuzu = _mock_kuzu_store(edges)
        duckdb = MagicMock()
        duckdb.connection = MagicMock()
        duckdb.execute = MagicMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

        result = detect_communities(duckdb, kuzu)
        assert result["status"] == "ok"
        assert result["community_count"] == 0
        assert any("too small" in w.lower() for w in result.get("warnings", []))


class TestListCommunities:
    def test_returns_stored_communities(self):
        rows = [
            ("community_000", "auth", 10, 3, 0.85, json.dumps(["function", "class"])),
            ("community_001", "models", 8, 2, 0.72, json.dumps(["class"])),
        ]
        duckdb = _mock_duckdb_store(communities_rows=rows)
        result = list_communities(duckdb, limit=20)
        assert result["status"] == "ok"
        assert result["community_count"] == 2
        assert result["communities"][0]["name"] == "auth"
        assert result["communities"][0]["cohesion"] == 0.85


class TestGetCommunityDetail:
    def test_found(self):
        comm_rows = [(
            "community_000", "auth", 10, 3, 0.85,
            json.dumps(["function"]), json.dumps(["src/auth.py"]),
        )]
        member_rows = [("mod.login",), ("mod.logout",)]
        symbol_rows = [("src/auth.py", "function")]
        duckdb = _mock_duckdb_store(communities_rows=comm_rows, member_rows=member_rows, symbol_rows=symbol_rows)
        result = get_community_detail(duckdb, "community_000")
        assert result["status"] == "ok"
        assert result["name"] == "auth"
        assert "mod.login" in result["members"]

    def test_not_found(self):
        duckdb = _mock_duckdb_store(communities_rows=[])
        result = get_community_detail(duckdb, "community_999")
        assert result["status"] == "not_found"


class TestGetSymbolCommunity:
    def test_found(self):
        # get_symbol_community uses a JOIN on community_members + communities
        join_rows = [("community_000", "auth", 0.85, 10)]
        duckdb = MagicMock()
        duckdb.execute = MagicMock(
            side_effect=lambda q, p=None: MagicMock(
                fetchall=MagicMock(return_value=join_rows if "join" in q.strip().lower() else [])
            )
        )
        result = get_symbol_community(duckdb, "mod.login")
        assert result["status"] == "ok"
        assert result["community_name"] == "auth"

    def test_not_found(self):
        duckdb = MagicMock()
        duckdb.execute = MagicMock(
            side_effect=lambda q, p=None: MagicMock(fetchall=MagicMock(return_value=[]))
        )
        result = get_symbol_community(duckdb, "mod.unknown")
        assert result["status"] == "not_found"
