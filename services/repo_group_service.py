"""Multi-repo group management and cross-repo contract matching.

Allows grouping multiple indexed repositories into a logical unit for
cross-repo analysis: contract extraction, cross-link detection, and
unified execution flow search across repos.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore

logger = logging.getLogger(__name__)


def create_group(
    duckdb_store: DuckDBStore,
    group_name: str,
    group_path: str = "",
) -> dict[str, object]:
    """Create a new repo group."""
    group_name = group_name.strip()
    if not group_name:
        return {"status": "error", "error": "group_name is required"}
    try:
        existing = duckdb_store.execute(
            "SELECT group_name FROM repo_groups WHERE group_name = ?", [group_name]
        ).fetchall()
        if existing:
            return {"status": "exists", "group_name": group_name, "warning": "Group already exists."}
        duckdb_store.execute(
            "INSERT INTO repo_groups (group_name, group_path, repos_json) VALUES (?, ?, ?)",
            [group_name, group_path, "[]"],
        )
    except Exception as exc:
        logger.debug("repo_group: create_group failed", exc_info=True)
        return {"status": "error", "error": str(exc)}
    return {
        "status": "ok",
        "group_name": group_name,
        "group_path": group_path,
        "repos": [],
        "summary_text": f"Created repo group '{group_name}'.",
    }


def add_repo_to_group(
    duckdb_store: DuckDBStore,
    group_name: str,
    repo_name: str,
    repo_path: str,
    hierarchy_path: str = "",
) -> dict[str, object]:
    """Add a repository to a group."""
    group_name = group_name.strip()
    repo_name = repo_name.strip()
    if not group_name or not repo_name:
        return {"status": "error", "error": "group_name and repo_name are required"}
    existing = duckdb_store.execute(
        "SELECT group_name FROM repo_groups WHERE group_name = ?", [group_name]
    ).fetchall()
    if not existing:
        return {"status": "error", "error": f"Group '{group_name}' does not exist. Create it first."}
    member_existing = duckdb_store.execute(
        "SELECT repo_name FROM repo_group_members WHERE group_name = ? AND repo_name = ?",
        [group_name, repo_name],
    ).fetchall()
    if member_existing:
        return {"status": "exists", "group_name": group_name, "repo_name": repo_name, "warning": "Repo already in group."}
    duckdb_store.execute(
        "INSERT INTO repo_group_members (group_name, repo_name, repo_path, hierarchy_path) VALUES (?, ?, ?, ?)",
        [group_name, repo_name, repo_path, hierarchy_path],
    )
    _refresh_group_repos_json(duckdb_store, group_name)
    return {
        "status": "ok",
        "group_name": group_name,
        "repo_name": repo_name,
        "repo_path": repo_path,
        "hierarchy_path": hierarchy_path,
        "summary_text": f"Added repo '{repo_name}' to group '{group_name}'.",
    }


def remove_repo_from_group(
    duckdb_store: DuckDBStore,
    group_name: str,
    hierarchy_path: str,
) -> dict[str, object]:
    """Remove a repository from a group by its hierarchy path."""
    group_name = group_name.strip()
    rows = duckdb_store.execute(
        "SELECT repo_name, repo_path FROM repo_group_members WHERE group_name = ? AND hierarchy_path = ?",
        [group_name, hierarchy_path],
    ).fetchall()
    if not rows:
        return {"status": "not_found", "error": f"No repo at path '{hierarchy_path}' in group '{group_name}'."}
    duckdb_store.execute(
        "DELETE FROM repo_group_members WHERE group_name = ? AND hierarchy_path = ?",
        [group_name, hierarchy_path],
    )
    _refresh_group_repos_json(duckdb_store, group_name)
    return {
        "status": "ok",
        "group_name": group_name,
        "removed_repo": str(rows[0][0]),
        "summary_text": f"Removed '{rows[0][0]}' from group '{group_name}'.",
    }


def list_groups(duckdb_store: DuckDBStore) -> dict[str, object]:
    """List all repo groups."""
    rows = duckdb_store.execute(
        "SELECT group_name, group_path, repos_json FROM repo_groups ORDER BY group_name"
    ).fetchall()
    groups = []
    for row in rows:
        name = str(row[0])
        member_rows = duckdb_store.execute(
            "SELECT repo_name, repo_path, hierarchy_path FROM repo_group_members WHERE group_name = ? ORDER BY hierarchy_path",
            [name],
        ).fetchall()
        members = [
            {"repo_name": str(r[0]), "repo_path": str(r[1]), "hierarchy_path": str(r[2])}
            for r in member_rows
        ]
        groups.append({
            "group_name": name,
            "group_path": str(row[1] or ""),
            "repo_count": len(members),
            "repos": members,
        })
    return {
        "status": "ok",
        "groups": groups,
        "group_count": len(groups),
        "compact_summary": {
            "group_count": len(groups),
            "top_groups": [{"name": g["group_name"], "repos": g["repo_count"]} for g in groups[:8]],
        },
    }


def get_group_detail(duckdb_store: DuckDBStore, group_name: str) -> dict[str, object]:
    """Get detailed information about a specific group."""
    group_name = group_name.strip()
    rows = duckdb_store.execute(
        "SELECT group_name, group_path FROM repo_groups WHERE group_name = ? LIMIT 1",
        [group_name],
    ).fetchall()
    if not rows:
        return {"status": "not_found", "error": f"Group '{group_name}' not found."}
    member_rows = duckdb_store.execute(
        "SELECT repo_name, repo_path, hierarchy_path FROM repo_group_members WHERE group_name = ? ORDER BY hierarchy_path",
        [group_name],
    ).fetchall()
    members = [
        {"repo_name": str(r[0]), "repo_path": str(r[1]), "hierarchy_path": str(r[2])}
        for r in member_rows
    ]
    return {
        "status": "ok",
        "group_name": str(rows[0][0]),
        "group_path": str(rows[0][1] or ""),
        "repo_count": len(members),
        "repos": members,
    }


def sync_group_contracts(
    duckdb_store: DuckDBStore,
    group_name: str,
) -> dict[str, object]:
    """Extract route/API contracts from each repo and find cross-repo matches.

    Looks for shared route paths, shared symbol names, and potential
    cross-repo dependencies across all repos in a group.
    """
    group_name = group_name.strip()
    detail = get_group_detail(duckdb_store, group_name)
    if detail.get("status") != "ok":
        return detail
    repos = detail.get("repos", [])
    if not isinstance(repos, list) or len(repos) < 2:
        return {
            "status": "ok",
            "group_name": group_name,
            "contracts": [],
            "cross_links": [],
            "warnings": ["Need at least 2 repos in the group for cross-repo analysis."],
        }

    # Extract route contracts from each repo's DuckDB
    repo_contracts: dict[str, list[dict[str, object]]] = {}
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        repo_name = str(repo.get("repo_name", ""))
        repo_path = str(repo.get("repo_path", ""))
        if not repo_path:
            continue
        repo_duckdb_path = Path(repo_path) / "data" / "duckdb" / "index.duckdb"
        if not repo_duckdb_path.exists():
            continue
        try:
            import duckdb as _duckdb
            conn = _duckdb.connect(str(repo_duckdb_path), read_only=True)
            rows = conn.execute(
                """
                SELECT DISTINCT
                    s.qualified_name,
                    s.file_path,
                    s.kind
                FROM symbols s
                WHERE s.kind IN ('function', 'method', 'class')
                  AND (s.qualified_name LIKE '%route%' OR s.qualified_name LIKE '%api%'
                       OR s.qualified_name LIKE '%handler%' OR s.qualified_name LIKE '%controller%')
                ORDER BY s.qualified_name
                LIMIT 100
                """
            ).fetchall()
            conn.close()
            repo_contracts[repo_name] = [
                {"symbol": str(r[0]), "file_path": str(r[1]), "kind": str(r[2])}
                for r in rows
            ]
        except Exception:
            logger.debug("sync_group_contracts: failed to read %s", repo_name, exc_info=True)
            repo_contracts[repo_name] = []

    # Find cross-repo links: shared symbol names and potential contracts
    cross_links: list[dict[str, object]] = []
    repo_names = list(repo_contracts.keys())
    for i, repo_a in enumerate(repo_names):
        for repo_b in repo_names[i + 1:]:
            symbols_a = {c["symbol"].split(".")[-1].lower(): c for c in repo_contracts[repo_a]}
            symbols_b = {c["symbol"].split(".")[-1].lower(): c for c in repo_contracts[repo_b]}
            shared = set(symbols_a.keys()) & set(symbols_b.keys())
            for name in sorted(shared):
                cross_links.append({
                    "type": "shared_symbol",
                    "repo_a": repo_a,
                    "repo_b": repo_b,
                    "symbol_name": name,
                    "repo_a_symbol": symbols_a[name]["symbol"],
                    "repo_b_symbol": symbols_b[name]["symbol"],
                    "repo_a_file": symbols_a[name]["file_path"],
                    "repo_b_file": symbols_b[name]["file_path"],
                })

    return {
        "status": "ok",
        "group_name": group_name,
        "repo_count": len(repos),
        "contracts": {
            repo_name: {"contract_count": len(contracts), "top_contracts": contracts[:10]}
            for repo_name, contracts in repo_contracts.items()
        },
        "cross_links": cross_links[:50],
        "cross_link_count": len(cross_links),
        "compact_summary": {
            "group_name": group_name,
            "repo_count": len(repos),
            "contract_repos": len(repo_contracts),
            "cross_link_count": len(cross_links),
            "top_cross_links": [
                {"repos": f"{cl['repo_a']} <-> {cl['repo_b']}", "symbol": cl["symbol_name"]}
                for cl in cross_links[:8]
            ],
        },
    }


def query_group_flows(
    duckdb_store: DuckDBStore,
    group_name: str,
    query: str,
    limit: int = 20,
) -> dict[str, object]:
    """Search for execution flows and symbols across all repos in a group."""
    group_name = group_name.strip()
    query = query.strip().lower()
    if not query:
        return {"status": "error", "error": "query is required"}
    detail = get_group_detail(duckdb_store, group_name)
    if detail.get("status") != "ok":
        return detail
    repos = detail.get("repos", [])
    results: list[dict[str, object]] = []
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        repo_name = str(repo.get("repo_name", ""))
        repo_path = str(repo.get("repo_path", ""))
        if not repo_path:
            continue
        repo_duckdb_path = Path(repo_path) / "data" / "duckdb" / "index.duckdb"
        if not repo_duckdb_path.exists():
            continue
        try:
            import duckdb as _duckdb
            conn = _duckdb.connect(str(repo_duckdb_path), read_only=True)
            rows = conn.execute(
                """
                SELECT qualified_name, file_path, kind
                FROM symbols
                WHERE LOWER(qualified_name) LIKE ? OR LOWER(file_path) LIKE ?
                ORDER BY qualified_name
                LIMIT ?
                """,
                [f"%{query}%", f"%{query}%", limit],
            ).fetchall()
            conn.close()
            for row in rows:
                results.append({
                    "repo": repo_name,
                    "symbol": str(row[0]),
                    "file_path": str(row[1]),
                    "kind": str(row[2]),
                })
        except Exception:
            logger.debug("query_group_flows: failed to read %s", repo_name, exc_info=True)

    results.sort(key=lambda r: str(r.get("symbol", "")))
    return {
        "status": "ok",
        "group_name": group_name,
        "query": query,
        "results": results[:limit],
        "result_count": len(results),
        "repos_searched": len(repos),
        "compact_summary": {
            "group_name": group_name,
            "query": query,
            "result_count": len(results),
            "top_results": [
                {"repo": r["repo"], "symbol": r["symbol"], "file": r["file_path"]}
                for r in results[:8]
            ],
        },
    }


def group_status(
    duckdb_store: DuckDBStore,
    group_name: str,
) -> dict[str, object]:
    """Check staleness of repos in a group."""
    group_name = group_name.strip()
    detail = get_group_detail(duckdb_store, group_name)
    if detail.get("status") != "ok":
        return detail
    repos = detail.get("repos", [])
    repo_statuses: list[dict[str, object]] = []
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        repo_name = str(repo.get("repo_name", ""))
        repo_path = str(repo.get("repo_path", ""))
        manifest_path = Path(repo_path) / "data" / "manifests" / "current_manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                status = str(manifest.get("status", "unknown"))
                indexed_at = manifest.get("indexed_at")
            except Exception:
                status = "unreadable"
                indexed_at = None
        else:
            status = "not_indexed"
            indexed_at = None
        repo_statuses.append({
            "repo_name": repo_name,
            "repo_path": repo_path,
            "status": status,
            "indexed_at": indexed_at,
        })
    stale = [r for r in repo_statuses if r["status"] not in ("ready", "completed")]
    return {
        "status": "ok",
        "group_name": group_name,
        "repo_count": len(repos),
        "stale_count": len(stale),
        "repos": repo_statuses,
        "compact_summary": {
            "group_name": group_name,
            "repo_count": len(repos),
            "stale_count": len(stale),
            "all_fresh": len(stale) == 0,
        },
    }


def _refresh_group_repos_json(duckdb_store: DuckDBStore, group_name: str) -> None:
    """Update the denormalized repos_json column after membership changes."""
    rows = duckdb_store.execute(
        "SELECT repo_name, repo_path, hierarchy_path FROM repo_group_members WHERE group_name = ? ORDER BY hierarchy_path",
        [group_name],
    ).fetchall()
    repos = [
        {"repo_name": str(r[0]), "repo_path": str(r[1]), "hierarchy_path": str(r[2])}
        for r in rows
    ]
    duckdb_store.execute(
        "UPDATE repo_groups SET repos_json = ? WHERE group_name = ?",
        [json.dumps(repos), group_name],
    )


def build_unified_graph(
    duckdb_store: DuckDBStore,
    group_name: str,
    relations: tuple[str, ...] = ("CALLS", "IMPORTS", "REFERENCES", "EXTENDS", "IMPLEMENTS", "USES_SERVICE"),
    edge_limit: int = 5000,
) -> dict[str, object]:
    """Build a unified in-memory graph from all repos in a group.

    Merges symbol nodes and edges from each repo's Kuzu graph, prefixing
    symbol names with the repo name to avoid collisions. Cross-repo edges
    are inferred from shared symbol names.

    Returns the unified adjacency map, node list, and cross-repo links.
    """
    group_name = group_name.strip()
    detail = get_group_detail(duckdb_store, group_name)
    if detail.get("status") != "ok":
        return detail  # type: ignore[return-value]
    repos = detail.get("repos", [])
    if not isinstance(repos, list) or not repos:
        return {
            "status": "ok",
            "group_name": group_name,
            "nodes": [],
            "edges": [],
            "cross_repo_edges": [],
            "node_count": 0,
            "edge_count": 0,
            "compact_summary": {"group_name": group_name, "node_count": 0, "edge_count": 0},
        }

    from storage.kuzu_store import KuzuStore
    from config.settings import load_settings

    unified_nodes: dict[str, dict[str, object]] = {}
    unified_edges: list[dict[str, object]] = []
    # Map: (repo_name, original_symbol) -> prefixed_symbol
    symbol_map: dict[tuple[str, str], str] = {}
    # Map: short_name -> list of (repo_name, prefixed_symbol)
    short_name_index: dict[str, list[tuple[str, str]]] = {}

    for repo in repos:
        if not isinstance(repo, dict):
            continue
        repo_name = str(repo.get("repo_name", ""))
        repo_path = str(repo.get("repo_path", ""))
        if not repo_path:
            continue
        try:
            repo_settings = load_settings(Path(repo_path))
            kuzu = KuzuStore(repo_settings.kuzu_path, read_only=True)
        except Exception:
            logger.debug("build_unified_graph: failed to open kuzu for %s", repo_name, exc_info=True)
            continue

        for relation in relations:
            try:
                edges = kuzu.edges_for_relation(relation)
            except Exception:
                continue
            for edge in edges[:edge_limit]:
                src = str(edge.get("source", ""))
                tgt = str(edge.get("target", ""))
                if not src or not tgt:
                    continue
                prefixed_src = f"{repo_name}:{src}"
                prefixed_tgt = f"{repo_name}:{tgt}"
                symbol_map[(repo_name, src)] = prefixed_src
                symbol_map[(repo_name, tgt)] = prefixed_tgt

                if prefixed_src not in unified_nodes:
                    unified_nodes[prefixed_src] = {"repo": repo_name, "symbol": src}
                    short = src.split(".")[-1].lower()
                    short_name_index.setdefault(short, []).append((repo_name, prefixed_src))
                if prefixed_tgt not in unified_nodes:
                    unified_nodes[prefixed_tgt] = {"repo": repo_name, "symbol": tgt}
                    short = tgt.split(".")[-1].lower()
                    short_name_index.setdefault(short, []).append((repo_name, prefixed_tgt))

                unified_edges.append({
                    "source": prefixed_src,
                    "target": prefixed_tgt,
                    "relation": relation,
                    "repo": repo_name,
                })
        try:
            kuzu.close()
        except Exception:
            pass

    # Infer cross-repo edges: symbols with the same short name in different repos
    cross_repo_edges: list[dict[str, object]] = []
    for short_name, entries in short_name_index.items():
        if len(entries) < 2:
            continue
        repos_for_name = {e[0] for e in entries}
        if len(repos_for_name) < 2:
            continue
        for i, (repo_a, sym_a) in enumerate(entries):
            for repo_b, sym_b in entries[i + 1:]:
                if repo_a != repo_b:
                    cross_repo_edges.append({
                        "source": sym_a,
                        "target": sym_b,
                        "relation": "CROSS_REPO_MATCH",
                        "matched_name": short_name,
                        "repo_a": repo_a,
                        "repo_b": repo_b,
                    })

    return {
        "status": "ok",
        "group_name": group_name,
        "repo_count": len(repos),
        "nodes": list(unified_nodes.values())[:500],
        "node_count": len(unified_nodes),
        "edges": unified_edges[:500],
        "edge_count": len(unified_edges),
        "cross_repo_edges": cross_repo_edges[:100],
        "cross_repo_edge_count": len(cross_repo_edges),
        "compact_summary": {
            "group_name": group_name,
            "repo_count": len(repos),
            "node_count": len(unified_nodes),
            "edge_count": len(unified_edges),
            "cross_repo_links": len(cross_repo_edges),
        },
        "summary_text": f"Unified graph: {len(unified_nodes)} nodes, {len(unified_edges)} edges, {len(cross_repo_edges)} cross-repo links across {len(repos)} repos.",
    }
