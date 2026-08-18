"""PR-aware graph impact: map a PR/diff to communities + blast radius.

Wraps ``detect_changes`` with two additional layers:

1. **Community mapping** — for each changed symbol, look up which
   functional community it belongs to (requires ``detect_communities`` to
   have been run). Groups changes by community so a reviewer can see
   "this PR touches 3 communities" at a glance.

2. **Blast radius per community** — for each touched community, count how
   many of its members are downstream of the changed symbols. A high
   blast-radius fraction within a single community is a much stronger
   review signal than the same count spread across many communities,
   because it means the change is concentrated in one functional area.

The service is deliberately a thin composition layer: it reuses
``detect_changes`` for the diff/changed-symbol work and
``get_symbol_community`` for the community lookup, then adds the
aggregation. Falls back gracefully when communities have not been
detected yet (returns the change payload with a warning and empty
community mapping).
"""
from __future__ import annotations

from pathlib import Path

from services.community_detection_service import get_symbol_community
from services.detect_changes_service import detect_changes
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore


def _community_lookup_safe(duckdb_store: DuckDBStore, qualified_name: str) -> dict[str, object] | None:
    try:
        result = get_symbol_community(duckdb_store, qualified_name)
    except Exception:
        return None
    if not isinstance(result, dict) or result.get("status") != "ok":
        return None
    return result


def _downstream_neighbors(kuzu_store: KuzuStore, qualified_name: str) -> set[str]:
    """Return the set of symbols the given symbol reaches via outbound edges."""
    neighbors: set[str] = set()
    for edge in kuzu_store.edges_for_source(qualified_name):
        nb = str(edge.get("target", "") or "")
        if nb and nb != qualified_name:
            neighbors.add(nb)
    return neighbors


def _community_members(duckdb_store: DuckDBStore, community_id: str) -> set[str]:
    rows = duckdb_store.execute(
        "SELECT symbol FROM community_members WHERE community_id = ?",
        [community_id],
    ).fetchall()
    return {str(row[0] or "") for row in rows if row and row[0]}


def pr_impact(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    scope: str = "unstaged",
    base_ref: str | None = None,
    diff_text_override: str | None = None,
    git_warning: str | None = None,
) -> dict[str, object]:
    base = detect_changes(
        repo_root=repo_root,
        duckdb_store=duckdb_store,
        kuzu_store=kuzu_store,
        scope=scope,
        base_ref=base_ref,
        diff_text_override=diff_text_override,
        git_warning=git_warning,
    )
    changed_symbols = base.get("changed_symbols", []) or []
    warnings = list(base.get("warnings", []) or [])
    community_map: dict[str, dict[str, object]] = {}
    unmapped_symbols: list[str] = []
    # Cache community members per community_id to avoid redundant DuckDB
    # queries when multiple changed symbols belong to the same community.
    members_cache: dict[str, set[str]] = {}
    for sym in changed_symbols:
        qn = str(sym.get("qualified_name", "") or sym.get("name", "") or "").strip()
        if not qn:
            continue
        community = _community_lookup_safe(duckdb_store, qn)
        if community is None:
            unmapped_symbols.append(qn)
            continue
        cid = str(community.get("community_id", "") or "")
        if not cid:
            continue
        entry = community_map.setdefault(cid, {
            "community_id": cid,
            "community_name": community.get("community_name", ""),
            "cohesion": community.get("cohesion", 0.0),
            "community_size": int(community.get("community_size", 0) or 0),
            "changed_symbols": [],
            "downstream_in_community": set(),
        })
        entry["changed_symbols"].append(qn)
        # Compute blast radius: downstream neighbors of this changed symbol
        # that also belong to the same community.
        downstream = _downstream_neighbors(kuzu_store, qn)
        if cid not in members_cache:
            members_cache[cid] = _community_members(duckdb_store, cid)
        members = members_cache[cid]
        entry["downstream_in_community"].update(downstream & members)
    # Finalize per-community payloads (convert sets to sorted lists + ratios).
    touched_communities: list[dict[str, object]] = []
    for cid, entry in community_map.items():
        members = members_cache.get(cid) or _community_members(duckdb_store, cid)
        community_size = max(int(entry["community_size"]) or len(members), 1)
        downstream = sorted(entry["downstream_in_community"])
        changed = sorted(set(entry["changed_symbols"]))
        blast_ratio = round(len(downstream) / community_size, 4) if community_size else 0.0
        touched_communities.append({
            "community_id": cid,
            "community_name": entry["community_name"],
            "cohesion": entry["cohesion"],
            "community_size": community_size,
            "changed_symbol_count": len(changed),
            "changed_symbols": changed[:25],
            "downstream_in_community_count": len(downstream),
            "downstream_in_community": downstream[:25],
            "blast_radius_ratio": blast_ratio,
            "is_concentrated": blast_ratio >= 0.3 and len(changed) >= 2,
        })
    touched_communities.sort(
        key=lambda item: (item["blast_radius_ratio"], item["changed_symbol_count"]),
        reverse=True,
    )
    if not community_map and changed_symbols:
        warnings.append(
            "No community mapping available for changed symbols. "
            "Run detect_communities first to enable PR-aware blast-radius analysis."
        )
    if unmapped_symbols:
        warnings.append(
            f"{len(unmapped_symbols)} changed symbol(s) not found in any community "
            "(may be new symbols added in this PR)."
        )
    concentrated = [c for c in touched_communities if c["is_concentrated"]]
    if concentrated:
        warnings.append(
            f"{len(concentrated)} community(ies) have concentrated blast radius "
            "(>=30% of members downstream of changed symbols). Prioritize review there."
        )
    return {
        **base,
        "pr_aware": {
            "touched_community_count": len(touched_communities),
            "touched_communities": touched_communities,
            "unmapped_symbols": unmapped_symbols[:25],
            "unmapped_symbol_count": len(unmapped_symbols),
            "concentrated_community_count": len(concentrated),
        },
        "warnings": warnings,
        "compact_summary": {
            **(base.get("compact_summary", {}) or {}),
            "touched_community_count": len(touched_communities),
            "concentrated_community_count": len(concentrated),
            "top_touched_communities": [
                {
                    "community_id": c["community_id"],
                    "community_name": c["community_name"],
                    "changed_symbol_count": c["changed_symbol_count"],
                    "blast_radius_ratio": c["blast_radius_ratio"],
                }
                for c in touched_communities[:5]
            ],
            "warnings": warnings,
        },
    }
