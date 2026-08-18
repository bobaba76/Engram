"""Tests for PR-aware impact community mapping and blast-radius aggregation."""
import services.pr_impact_service as pr_impact_module
from services.pr_impact_service import pr_impact


class _Duck:
    """Minimal DuckDB stand-in: serves community_members lookups."""

    def __init__(self, community_members):
        # community_members: {community_id: set(qualified_name)}
        self._members = community_members

    def execute(self, query, params=None):
        q = query.strip().lower()
        if "from community_members where community_id" in q:
            cid = params[0] if params else ""
            return _Rows([(m,) for m in sorted(self._members.get(cid, set()))])
        if "from community_members cm" in q:
            # get_symbol_community lookup
            target = params[0] if params else ""
            for cid, members in self._members.items():
                if target in members:
                    return _Rows([(cid, f"Community {cid}", 0.8, len(members))])
            return _Rows([])
        return _Rows([])


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Kuzu:
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


def _patch_detect_changes(monkeypatch, changed_symbols):
    """Replace detect_changes with a stub returning the given changed_symbols."""
    def _stub(**kwargs):
        return {
            "changed_symbols": changed_symbols,
            "changed_files": [s.get("file_path", "x.py") for s in changed_symbols],
            "warnings": [],
            "compact_summary": {"changed_symbol_count": len(changed_symbols)},
        }
    monkeypatch.setattr(pr_impact_module, "detect_changes", _stub)


def test_pr_impact_groups_changes_by_community(monkeypatch):
    changed = [
        {"qualified_name": "auth.login", "file_path": "auth.py"},
        {"qualified_name": "auth.logout", "file_path": "auth.py"},
        {"qualified_name": "billing.charge", "file_path": "billing.py"},
    ]
    _patch_detect_changes(monkeypatch, changed)
    members = {
        "c_auth": {"auth.login", "auth.logout", "auth.session", "auth.token"},
        "c_billing": {"billing.charge", "billing.refund", "billing.invoice"},
    }
    edges = [
        {"source": "auth.login", "relation": "CALLS", "target": "auth.session"},
        {"source": "auth.login", "relation": "CALLS", "target": "auth.token"},
        {"source": "billing.charge", "relation": "CALLS", "target": "billing.invoice"},
    ]
    payload = pr_impact(
        repo_root=None,
        duckdb_store=_Duck(members),
        kuzu_store=_Kuzu(edges),
    )
    pr_aware = payload["pr_aware"]
    assert pr_aware["touched_community_count"] == 2
    communities = {c["community_id"]: c for c in pr_aware["touched_communities"]}
    assert communities["c_auth"]["changed_symbol_count"] == 2
    assert communities["c_auth"]["downstream_in_community_count"] == 2  # session + token
    assert communities["c_billing"]["changed_symbol_count"] == 1
    assert communities["c_billing"]["downstream_in_community_count"] == 1  # invoice


def test_pr_impact_flags_concentrated_blast_radius(monkeypatch):
    """A community where >=30% of members are downstream of changes is flagged concentrated."""
    changed = [
        {"qualified_name": "hub.fn", "file_path": "hub.py"},
        {"qualified_name": "hub.helper", "file_path": "hub.py"},
    ]
    _patch_detect_changes(monkeypatch, changed)
    # 4-member community, 2 downstream = 50% blast radius -> concentrated.
    members = {"c1": {"hub.fn", "hub.helper", "a", "b"}}
    edges = [
        {"source": "hub.fn", "relation": "CALLS", "target": "a"},
        {"source": "hub.fn", "relation": "CALLS", "target": "b"},
    ]
    payload = pr_impact(repo_root=None, duckdb_store=_Duck(members), kuzu_store=_Kuzu(edges))
    community = payload["pr_aware"]["touched_communities"][0]
    assert community["is_concentrated"] is True
    assert community["blast_radius_ratio"] == 0.5
    assert payload["pr_aware"]["concentrated_community_count"] == 1
    assert any("concentrated" in w for w in payload["warnings"])


def test_pr_impact_warns_when_communities_not_detected(monkeypatch):
    """When no community mapping exists, return base payload with a warning."""
    changed = [{"qualified_name": "orphan.fn", "file_path": "x.py"}]
    _patch_detect_changes(monkeypatch, changed)
    payload = pr_impact(repo_root=None, duckdb_store=_Duck({}), kuzu_store=_Kuzu([]))
    assert payload["pr_aware"]["touched_community_count"] == 0
    assert any("detect_communities" in w for w in payload["warnings"])


def test_pr_impact_reports_unmapped_symbols(monkeypatch):
    """Symbols not in any community are listed as unmapped."""
    changed = [
        {"qualified_name": "mapped.fn", "file_path": "a.py"},
        {"qualified_name": "new.fn", "file_path": "b.py"},
    ]
    _patch_detect_changes(monkeypatch, changed)
    members = {"c1": {"mapped.fn", "other.fn"}}
    payload = pr_impact(repo_root=None, duckdb_store=_Duck(members), kuzu_store=_Kuzu([]))
    assert "new.fn" in payload["pr_aware"]["unmapped_symbols"]
    assert payload["pr_aware"]["unmapped_symbol_count"] == 1
