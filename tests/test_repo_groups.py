"""Tests for repo group service."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from services.repo_group_service import (
    add_repo_to_group,
    create_group,
    get_group_detail,
    group_status,
    list_groups,
    query_group_flows,
    remove_repo_from_group,
    sync_group_contracts,
)


def _mock_duckdb(
    group_rows: list[tuple] | None = None,
    member_rows: list[tuple] | None = None,
) -> MagicMock:
    store = MagicMock()
    store.connection = MagicMock()

    def execute_side_effect(query, params=None):
        q = query.strip().lower()
        if q.startswith("insert"):
            return MagicMock()
        if q.startswith("delete"):
            return MagicMock()
        if q.startswith("update"):
            return MagicMock()
        if "from repo_groups" in q and "where group_name" in q:
            return MagicMock(fetchall=MagicMock(return_value=group_rows or []))
        if "from repo_group_members" in q and "where group_name" in q:
            return MagicMock(fetchall=MagicMock(return_value=member_rows or []))
        if "from repo_groups" in q:
            return MagicMock(fetchall=MagicMock(return_value=group_rows or []))
        if "from repo_group_members" in q:
            return MagicMock(fetchall=MagicMock(return_value=member_rows or []))
        return MagicMock(fetchall=MagicMock(return_value=[]))

    store.execute = MagicMock(side_effect=execute_side_effect)
    return store


class TestCreateGroup:
    def test_creates_new_group(self):
        duckdb = _mock_duckdb(group_rows=[])
        result = create_group(duckdb, "my_group", "/path/to/group")
        assert result["status"] == "ok"
        assert result["group_name"] == "my_group"

    def test_empty_name_errors(self):
        duckdb = _mock_duckdb()
        result = create_group(duckdb, "", "")
        assert result["status"] == "error"

    def test_existing_group_returns_exists(self):
        duckdb = _mock_duckdb(group_rows=[("my_group",)])
        result = create_group(duckdb, "my_group")
        assert result["status"] == "exists"


class TestAddRepoToGroup:
    def test_adds_repo(self):
        duckdb = _mock_duckdb(group_rows=[("my_group",)], member_rows=[])
        result = add_repo_to_group(duckdb, "my_group", "repo_a", "/path/to/repo_a", "svc/repo_a")
        assert result["status"] == "ok"
        assert result["repo_name"] == "repo_a"

    def test_group_not_found(self):
        duckdb = _mock_duckdb(group_rows=[])
        result = add_repo_to_group(duckdb, "missing", "repo_a", "/path", "")
        assert result["status"] == "error"

    def test_already_member(self):
        duckdb = _mock_duckdb(group_rows=[("my_group",)], member_rows=[("repo_a",)])
        result = add_repo_to_group(duckdb, "my_group", "repo_a", "/path", "")
        assert result["status"] == "exists"


class TestRemoveRepoFromGroup:
    def test_removes_existing(self):
        duckdb = _mock_duckdb(member_rows=[("repo_a", "/path", "svc/repo_a")])
        result = remove_repo_from_group(duckdb, "my_group", "svc/repo_a")
        assert result["status"] == "ok"
        assert result["removed_repo"] == "repo_a"

    def test_not_found(self):
        duckdb = _mock_duckdb(member_rows=[])
        result = remove_repo_from_group(duckdb, "my_group", "missing/path")
        assert result["status"] == "not_found"


class TestListGroups:
    def test_lists_multiple_groups(self):
        group_rows = [("group_a", "/path/a", "[]"), ("group_b", "/path/b", "[]")]
        member_rows = [("repo_x", "/path/x", "svc/x")]
        duckdb = _mock_duckdb(group_rows=group_rows, member_rows=member_rows)
        result = list_groups(duckdb)
        assert result["status"] == "ok"
        assert result["group_count"] == 2

    def test_empty_list(self):
        duckdb = _mock_duckdb(group_rows=[])
        result = list_groups(duckdb)
        assert result["status"] == "ok"
        assert result["group_count"] == 0


class TestGetGroupDetail:
    def test_found(self):
        group_rows = [("my_group", "/path")]
        member_rows = [("repo_a", "/path/a", "svc/a"), ("repo_b", "/path/b", "svc/b")]
        duckdb = _mock_duckdb(group_rows=group_rows, member_rows=member_rows)
        result = get_group_detail(duckdb, "my_group")
        assert result["status"] == "ok"
        assert result["repo_count"] == 2

    def test_not_found(self):
        duckdb = _mock_duckdb(group_rows=[])
        result = get_group_detail(duckdb, "missing")
        assert result["status"] == "not_found"


class TestGroupStatus:
    def test_returns_status_for_repos(self):
        group_rows = [("my_group", "/path")]
        member_rows = [("repo_a", "/path/a", "svc/a")]
        duckdb = _mock_duckdb(group_rows=group_rows, member_rows=member_rows)
        result = group_status(duckdb, "my_group")
        assert result["status"] == "ok"
        assert result["repo_count"] == 1
        assert "repos" in result

    def test_group_not_found(self):
        duckdb = _mock_duckdb(group_rows=[])
        result = group_status(duckdb, "missing")
        assert result["status"] == "not_found"


class TestQueryGroupFlows:
    def test_empty_query_errors(self):
        duckdb = _mock_duckdb(group_rows=[("g", "")])
        result = query_group_flows(duckdb, "g", "")
        assert result["status"] == "error"

    def test_group_not_found(self):
        duckdb = _mock_duckdb(group_rows=[])
        result = query_group_flows(duckdb, "missing", "auth")
        assert result["status"] == "not_found"


class TestSyncGroupContracts:
    def test_group_not_found(self):
        duckdb = _mock_duckdb(group_rows=[])
        result = sync_group_contracts(duckdb, "missing")
        assert result["status"] == "not_found"

    def test_single_repo_warning(self):
        group_rows = [("g", "/path")]
        member_rows = [("repo_a", "/path/a", "svc/a")]
        duckdb = _mock_duckdb(group_rows=group_rows, member_rows=member_rows)
        result = sync_group_contracts(duckdb, "g")
        assert result["status"] == "ok"
        assert any("at least 2" in w.lower() for w in result.get("warnings", []))
