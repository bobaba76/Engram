"""Community detection via label propagation on the symbol graph.

Groups symbols into functional communities based on their graph connectivity
(CALLS, IMPORTS, REFERENCES, etc.). Results are stored in DuckDB and exposed
via MCP tools.

This is a lightweight alternative to Leiden/Louvain that works well on
moderate-sized code graphs without requiring external libraries.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore

logger = logging.getLogger(__name__)

COMMUNITY_RELATIONS = (
    "CALLS",
    "IMPORTS",
    "REFERENCES",
    "EXTENDS",
    "IMPLEMENTS",
    "HAS_METHOD",
    "HAS_PROPERTY",
    "USES_SERVICE",
    "ASSOCIATED_WITH",
)

MAX_ITERATIONS = 15
MIN_COMMUNITY_SIZE = 2
MAX_COMMUNITY_SIZE = 200
EDGE_LIMIT = 5000
SPLIT_MAX_DEPTH = 5
SPLIT_SEEDS = [42, 7, 123, 999, 555, 314, 271, 8128]
SPLIT_ACCEPT_SIZE = 500  # Accept communities up to this size without forced bisection


def _split_community(
    members: list[str],
    adjacency: dict[str, set[str]],
    max_size: int,
    min_size: int,
    depth: int = 0,
) -> list[list[str]]:
    """Recursively split an oversized community into smaller ones.

    Tries label propagation with multiple seeds first (works well for
    graphs with natural community structure). Falls back to bisection
    only if LP fails to produce a valid split.
    """
    if len(members) <= max_size or depth >= SPLIT_MAX_DEPTH:
        return [members]

    member_set = set(members)
    sub_adj = {n: (adjacency.get(n, set()) & member_set) for n in members}

    best_split: list[list[str]] = []
    best_min_cohesion = -1.0

    # Always try LP with multiple seeds
    for seed in SPLIT_SEEDS:
        sub_labels = _label_propagation(sub_adj, members, max_iterations=20, seed=seed)
        groups: dict[int, list[str]] = defaultdict(list)
        for n, lbl in sub_labels.items():
            groups[lbl].append(n)
        candidate = [sorted(g) for g in groups.values() if len(g) >= min_size]

        if len(candidate) <= 1:
            continue

        cohesions = [_compute_cohesion(g, sub_adj) for g in candidate]
        min_cohesion = min(cohesions) if cohesions else 0.0
        if min_cohesion > best_min_cohesion:
            best_min_cohesion = min_cohesion
            best_split = candidate

    # Fallback: bisection if LP couldn't split
    if not best_split:
        if len(members) > SPLIT_ACCEPT_SIZE:
            # Large enough to warrant forced bisection
            best_split = _bisect_community(members, sub_adj, min_size)
        # else: small enough to return as-is

    if not best_split or len(best_split) <= 1:
        return [members]

    # Reject splits that produce disconnected fragments (cohesion < 0.05)
    # Only when LP produced the split (bisection fragments are expected to be weak)
    if best_min_cohesion >= 0 and best_min_cohesion < 0.05:
        # LP split was garbage - try bisection instead for large communities
        if len(members) > SPLIT_ACCEPT_SIZE:
            best_split = _bisect_community(members, sub_adj, min_size)
            if not best_split or len(best_split) <= 1:
                return [members]
        else:
            return [members]

    # Recursively split any sub-communities that are still too large
    # Use bisection for recursive splits since LP tends to keep a dense core
    result: list[list[str]] = []
    for sub in best_split:
        if len(sub) > SPLIT_ACCEPT_SIZE:
            if depth == 0:
                # First recursion: try LP again (might peel more periphery)
                result.extend(_split_community(sub, adjacency, max_size, min_size, depth + 1))
            else:
                # Deeper recursion: force bisection to break dense cores
                result.extend(_force_bisect_recursive(sub, adjacency, SPLIT_ACCEPT_SIZE, min_size, depth + 1))
        else:
            result.append(sub)
    return result


def _force_bisect_recursive(
    members: list[str],
    adjacency: dict[str, set[str]],
    max_size: int,
    min_size: int,
    depth: int,
) -> list[list[str]]:
    """Recursively bisect an oversized community until all parts fit max_size."""
    if len(members) <= max_size or depth >= SPLIT_MAX_DEPTH:
        return [members]

    member_set = set(members)
    sub_adj = {n: (adjacency.get(n, set()) & member_set) for n in members}
    parts = _bisect_community(members, sub_adj, min_size)

    if not parts or len(parts) <= 1:
        return [members]

    result: list[list[str]] = []
    for part in parts:
        if len(part) > max_size:
            result.extend(_force_bisect_recursive(part, adjacency, max_size, min_size, depth + 1))
        else:
            result.append(part)
    return result


def _bisect_community(
    members: list[str],
    sub_adj: dict[str, set[str]],
    min_size: int,
) -> list[list[str]]:
    """Split a community in two using BFS-based partitioning.

    Picks two high-degree nodes that are far apart (seeds), then assigns
    each node to whichever seed it's closer to via BFS. This respects
    graph structure much better than degree-rank cutting.
    """
    if len(members) < min_size * 2:
        return [members]

    # Compute internal degrees
    degrees = {n: len(sub_adj.get(n, set())) for n in members}

    # Pick seed 1: highest degree node
    seed1 = max(members, key=lambda n: degrees[n])

    # Pick seed 2: highest degree node that's farthest from seed1 via BFS
    dist1 = _bfs_distances(seed1, sub_adj)
    candidates = [n for n in members if n != seed1 and degrees[n] > 0]
    if not candidates:
        # All other nodes have degree 0 - just split in half
        sorted_members = sorted(members)
        mid = len(sorted_members) // 2
        return [sorted_members[:mid], sorted_members[mid:]]
    seed2 = max(
        candidates,
        key=lambda n: (dist1.get(n, 999), degrees[n]),
    )

    # BFS from both seeds
    dist1 = _bfs_distances(seed1, sub_adj)
    dist2 = _bfs_distances(seed2, sub_adj)

    # Assign nodes to nearest seed (ties go to seed1 for determinism)
    left: list[str] = []
    right: list[str] = []
    for n in members:
        d1 = dist1.get(n, 999)
        d2 = dist2.get(n, 999)
        if d1 <= d2:
            left.append(n)
        else:
            right.append(n)

    # Enforce balance: if one side has >70%, use periphery-peeling instead
    # This happens in dense graphs where BFS distances are all 1-2 hops
    n = len(members)
    if len(left) > n * 0.7 or len(right) > n * 0.7 or len(left) < min_size or len(right) < min_size:
        # Periphery peeling: separate high-degree core from low-degree periphery
        # This preserves the dense core's cohesion while carving off the periphery
        sorted_by_degree = sorted(members, key=lambda n: degrees[n], reverse=True)
        # Keep the top ~60% as core, rest as periphery
        cut = int(n * 0.6)
        left = sorted_by_degree[:cut]
        right = sorted_by_degree[cut:]

    return [sorted(left), sorted(right)]


def _bfs_distances(start: str, adj: dict[str, set[str]], max_dist: int = 10) -> dict[str, int]:
    """BFS from start node, returning distances to all reachable nodes."""
    distances: dict[str, int] = {start: 0}
    frontier = [start]
    for dist in range(1, max_dist + 1):
        next_frontier: list[str] = []
        for node in frontier:
            for neighbor in adj.get(node, set()):
                if neighbor not in distances:
                    distances[neighbor] = dist
                    next_frontier.append(neighbor)
        if not next_frontier:
            break
        frontier = next_frontier
    return distances


def _build_adjacency(kuzu_store: KuzuStore) -> dict[str, set[str]]:
    """Build an undirected adjacency map from symbol graph edges.

    Fetches edges per community relation with a total edge cap to
    prevent hangs on large graphs.
    """
    adjacency: dict[str, set[str]] = defaultdict(set)
    total_edges = 0
    edge_cap = EDGE_LIMIT * len(COMMUNITY_RELATIONS)
    for relation in COMMUNITY_RELATIONS:
        try:
            edges = kuzu_store.edges_for_relation(relation)
        except Exception:
            logger.debug("community: failed to fetch edges for %s", relation, exc_info=True)
            continue
        for edge in edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source and target and source != target:
                adjacency[source].add(target)
                adjacency[target].add(source)
                total_edges += 1
                if total_edges >= edge_cap:
                    logger.warning("community: edge cap reached at %d edges", total_edges)
                    return dict(adjacency)
    logger.debug("community: built adjacency with %d nodes, %d edges", len(adjacency), total_edges)
    return dict(adjacency)


def _label_propagation(
    adjacency: dict[str, set[str]],
    nodes: list[str],
    *,
    max_iterations: int = MAX_ITERATIONS,
    seed: int = 42,
) -> dict[str, int]:
    """Run asynchronous label propagation clustering.

    Each node starts with a unique label. On each iteration, nodes adopt
    the most frequent label among their neighbours (ties broken deterministically).
    Converges when labels stabilise or max_iterations is reached.
    """
    import random

    rng = random.Random(seed)
    labels: dict[str, int] = {node: idx for idx, node in enumerate(nodes)}
    node_order = list(nodes)
    for iteration in range(max_iterations):
        rng.shuffle(node_order)
        changed = False
        for node in node_order:
            neighbours = adjacency.get(node, set())
            if not neighbours:
                continue
            label_counts: dict[int, int] = defaultdict(int)
            for neighbour in neighbours:
                label_counts[labels.get(neighbour, 0)] += 1
            if not label_counts:
                continue
            max_count = max(label_counts.values())
            candidates = sorted(
                label for label, count in label_counts.items() if count == max_count
            )
            best_label = candidates[0]
            if labels.get(node) != best_label:
                labels[node] = best_label
                changed = True
        if not changed:
            logger.debug("community: converged after %d iterations", iteration + 1)
            break
    return labels


def _louvain(
    adjacency: dict[str, set[str]],
    nodes: list[str],
    *,
    max_iterations: int = 20,
    seed: int = 42,
) -> dict[str, int]:
    """Run a simplified single-level Louvain modularity optimization.

    Assigns nodes to communities by greedily maximizing modularity gain.
    Each node starts in its own community, then iteratively moves to the
    neighbor community that gives the best modularity improvement.
    """
    import random

    rng = random.Random(seed)

    degree: dict[str, int] = {n: len(adjacency.get(n, set())) for n in nodes}
    total_edges = sum(degree.values()) / 2
    if total_edges == 0:
        return {node: idx for idx, node in enumerate(nodes)}

    comm: dict[str, int] = {node: idx for idx, node in enumerate(nodes)}
    comm_degree: dict[int, float] = {idx: float(degree[node]) for node, idx in comm.items()}

    m2 = total_edges * 2

    node_order = list(nodes)
    for iteration in range(max_iterations):
        rng.shuffle(node_order)
        changed = False
        for node in node_order:
            neighbours = adjacency.get(node, set())
            if not neighbours:
                continue

            current_comm = comm[node]
            k_i = degree[node]

            comm_edges: dict[int, float] = defaultdict(float)
            for nb in neighbours:
                comm_edges[comm[nb]] += 1.0

            comm_degree[current_comm] -= k_i

            best_comm = current_comm
            best_gain = 0.0
            for target_comm, edge_count in comm_edges.items():
                if target_comm == current_comm:
                    continue
                gain = edge_count - k_i * comm_degree[target_comm] / m2
                if gain > best_gain:
                    best_gain = gain
                    best_comm = target_comm

            stay_gain = comm_edges.get(current_comm, 0.0) - k_i * comm_degree[current_comm] / m2
            if stay_gain > best_gain:
                best_comm = current_comm

            comm[node] = best_comm
            comm_degree[best_comm] += k_i

            if best_comm != current_comm:
                changed = True

        if not changed:
            logger.debug("community: louvain converged after %d iterations", iteration + 1)
            break
    return comm


def _batch_symbol_info(
    duckdb_store: DuckDBStore,
    qualified_names: list[str],
) -> dict[str, tuple[str, str, str, str]]:
    """Batch-fetch file_path, kind, name, and signature for a list of qualified names.

    Returns a dict mapping qualified_name -> (file_path, kind, name, signature).
    """
    if not qualified_names:
        return {}
    result: dict[str, tuple[str, str, str, str]] = {}
    batch_size = 200
    for i in range(0, len(qualified_names), batch_size):
        batch = qualified_names[i:i + batch_size]
        placeholders = ", ".join("?" for _ in batch)
        try:
            rows = duckdb_store.execute(
                f"SELECT qualified_name, file_path, kind, name, signature FROM symbols WHERE qualified_name IN ({placeholders})",
                batch,
            ).fetchall()
            for row in rows:
                result[str(row[0])] = (
                    str(row[1] or ""),
                    str(row[2] or ""),
                    str(row[3] or ""),
                    str(row[4] or ""),
                )
        except Exception:
            logger.debug("community: batch symbol query failed", exc_info=True)
    return result


def _name_community(
    members: list[str],
    symbol_info: dict[str, tuple[str, str, str, str]],
) -> tuple[str, list[str]]:
    """Generate a functional name for a community from its member symbols.

    Uses a heuristic approach:
    1. Extract common keywords from symbol names (e.g. "forecast", "auth", "upload")
    2. Combine top keyword with dominant kind (e.g. "forecasting-engine", "auth-handlers")
    3. Fall back to file path prefix if no clear keyword emerges
    """
    file_paths: set[str] = set()
    kinds: dict[str, int] = defaultdict(int)
    symbol_names: list[str] = []

    for qualified_name in members[:100]:
        info = symbol_info.get(qualified_name)
        if info:
            file_path, kind, name, _sig = info
            if file_path:
                file_paths.add(file_path)
            if kind:
                kinds[str(kind)] += 1
            if name:
                symbol_names.append(name)

    # Extract meaningful keywords from symbol names
    STOP_WORDS = {
        "get", "set", "create", "update", "delete", "handle", "process",
        "init", "new", "old", "data", "info", "item", "items", "list",
        "row", "rows", "col", "cols", "test", "mock", "fake", "true",
        "false", "none", "null", "self", "cls", "this", "that",
        "response", "request", "error", "result", "value", "key",
        "type", "str", "int", "float", "bool", "dict", "list",
        "base", "abstract", "generic", "helper", "utils", "common",
        "index", "start", "end", "count", "size", "len", "name",
    }

    word_freq: dict[str, int] = defaultdict(int)
    for sym_name in symbol_names:
        # Split camelCase, snake_case, PascalCase into words
        words = (
            sym_name.replace("_", " ")
            .replace("-", " ")
            .replace(".", " ")
        )
        # Split on camelCase boundaries
        words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", words)
        for w in words:
            w_lower = w.lower()
            if len(w_lower) >= 4 and w_lower not in STOP_WORDS:
                word_freq[w_lower] += 1

    top_kinds = sorted(kinds, key=lambda k: kinds[k], reverse=True)[:3]

    # Build functional name from top keywords + kind distribution
    if word_freq:
        top_words = sorted(word_freq, key=word_freq.get, reverse=True)[:3]
        dominant_kind = top_kinds[0] if top_kinds else ""

        # Singularize helper
        def _sing(word: str) -> str:
            if word.endswith("ies"):
                return word[:-3] + "y"
            if word.endswith("s") and not word.endswith("ss"):
                return word[:-1]
            return word

        primary = _sing(top_words[0])

        # Pick a suffix based on what the community actually does
        # Look at keyword patterns to infer the functional role
        all_words_lower = {w for w in top_words}
        kw = " ".join(top_words).lower()

        # Determine suffix from kind + keyword analysis
        if dominant_kind == "component":
            suffix = "components"
        elif dominant_kind == "interface":
            if "type" in all_words_lower or "types" in all_words_lower:
                suffix = "types"
            else:
                suffix = "contracts"
        elif dominant_kind == "class":
            if "model" in all_words_lower or "record" in all_words_lower or "entity" in all_words_lower:
                suffix = "models"
            elif "processor" in all_words_lower or "engine" in all_words_lower:
                suffix = "engine"
            else:
                suffix = "core"
        elif dominant_kind == "method":
            if "process" in kw or "processor" in kw:
                suffix = "processors"
            elif "export" in kw:
                suffix = "exports"
            elif "upload" in kw:
                suffix = "uploads"
            elif "auth" in kw or "token" in kw or "password" in kw or "login" in kw:
                suffix = "auth"
            elif "price" in kw or "pricing" in kw or "channel" in kw or "margin" in kw:
                suffix = "pricing"
            elif "forecast" in kw:
                suffix = "forecasting"
            elif "report" in kw:
                suffix = "reports"
            elif "test" in kw:
                suffix = "tests"
            elif "route" in kw or "endpoint" in kw or "router" in kw:
                suffix = "routes"
            else:
                suffix = "logic"
        elif dominant_kind == "function":
            if "export" in kw:
                suffix = "exports"
            elif "upload" in kw:
                suffix = "uploads"
            elif "auth" in kw or "token" in kw or "password" in kw or "login" in kw:
                suffix = "auth"
            elif "price" in kw or "pricing" in kw or "channel" in kw or "margin" in kw:
                suffix = "pricing"
            elif "forecast" in kw:
                suffix = "forecasting"
            elif "report" in kw:
                suffix = "reports"
            elif "render" in kw or "style" in kw or "theme" in kw or "color" in kw or "layout" in kw:
                suffix = "ui"
            elif "slide" in kw or "pptx" in kw or "deliverable" in kw:
                suffix = "generation"
            elif "diff" in kw or "compare" in kw:
                suffix = "diff"
            elif "test" in kw:
                suffix = "tests"
            elif "route" in kw or "endpoint" in kw or "router" in kw:
                suffix = "routes"
            elif "query" in kw or "fetch" in kw or "search" in kw:
                suffix = "queries"
            elif "calc" in kw or "compute" in kw or "round" in kw or "convert" in kw:
                suffix = "utils"
            else:
                suffix = "helpers"
        else:
            suffix = ""

        if suffix:
            # Avoid redundant names like "report-reports" or "upload-uploads"
            primary_lower = primary.lower()
            suffix_lower = suffix.lower()
            if primary_lower == suffix_lower or primary_lower == suffix_lower.rstrip("s"):
                name = suffix
            elif suffix_lower == primary_lower + "s" or suffix_lower == primary_lower + "es":
                name = suffix
            else:
                name = f"{primary}-{suffix}"
        else:
            name = primary

        return name, top_kinds

    # Fall back to file path analysis
    if file_paths:
        sorted_paths = sorted(file_paths)
        first = sorted_paths[0].replace("\\", "/").split("/")
        prefix = []
        for part in first:
            if all(
                len(p.replace("\\", "/").split("/")) > len(prefix) and p.replace("\\", "/").split("/")[len(prefix)] == part
                for p in sorted_paths[:10]
            ):
                prefix.append(part)
            else:
                break
        if prefix:
            name = "/".join(prefix[-2:])
        else:
            name = sorted_paths[0].replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    elif kinds:
        name = f"{max(kinds, key=kinds.get)}s"
    else:
        name = f"cluster_{abs(hash(tuple(sorted(members[:3])))) % 10000}"

    return name, top_kinds


def _compute_cohesion(
    members: list[str],
    adjacency: dict[str, set[str]],
) -> float:
    """Compute cohesion score: fraction of edges that stay within community."""
    member_set = set(members)
    internal = 0
    external = 0
    for node in members:
        neighbours = adjacency.get(node, set())
        for neighbour in neighbours:
            if neighbour in member_set:
                internal += 1
            else:
                external += 1
    total = internal + external
    if total == 0:
        return 0.0
    return round(internal / total, 3)


def detect_communities(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    *,
    min_size: int = MIN_COMMUNITY_SIZE,
    max_size: int = MAX_COMMUNITY_SIZE,
    algorithm: str = "label_propagation",
) -> dict[str, object]:
    """Detect functional communities in the symbol graph and store results.

    Args:
        algorithm: "label_propagation" (default) or "louvain" for modularity optimization.

    Returns a summary of detected communities.
    """
    start = time.time()

    # Phase 1: Build adjacency from graph
    adjacency = _build_adjacency(kuzu_store)
    nodes = sorted(adjacency.keys())
    graph_time = round(time.time() - start, 3)

    if len(nodes) < min_size:
        return {
            "status": "ok",
            "communities": [],
            "community_count": 0,
            "symbol_count": len(nodes),
            "elapsed_seconds": round(time.time() - start, 3),
            "warnings": ["Graph too small for meaningful community detection."],
        }

    # Phase 2: Clustering
    if algorithm == "louvain":
        labels = _louvain(adjacency, nodes)
    else:
        labels = _label_propagation(adjacency, nodes)
    cluster_time = round(time.time() - start, 3)

    # Group nodes by label
    communities_raw: dict[int, list[str]] = defaultdict(list)
    for node, label in labels.items():
        communities_raw[label].append(node)

    # Filter by size and recursively split oversized communities
    communities: list[list[str]] = []
    for members in communities_raw.values():
        if len(members) < min_size:
            continue
        if len(members) > max_size:
            communities.extend(_split_community(members, adjacency, max_size, min_size))
        else:
            communities.append(sorted(members))

    # Phase 3: Batch-fetch all symbol metadata for naming (single query)
    all_members = [sym for members in communities for sym in members]
    symbol_info = _batch_symbol_info(duckdb_store, all_members)
    enrich_time = round(time.time() - start, 3)

    # Phase 4: Build community records (all in-memory, no per-symbol queries)
    community_records: list[dict[str, object]] = []
    for idx, members in enumerate(sorted(communities, key=len, reverse=True)):
        community_id = f"community_{idx:03d}"
        name, top_kinds = _name_community(members, symbol_info)
        cohesion = _compute_cohesion(members, adjacency)
        file_paths_set: set[str] = set()
        for qualified_name in members:
            info = symbol_info.get(qualified_name)
            if info and info[0]:
                file_paths_set.add(info[0])
        file_paths = sorted(file_paths_set)
        community_records.append({
            "community_id": community_id,
            "name": name,
            "symbol_count": len(members),
            "file_count": len(file_paths),
            "cohesion": cohesion,
            "top_kinds": top_kinds,
            "members": members,
            "file_paths": file_paths[:30],
        })

    # Phase 5: Store results in DuckDB (best-effort, may skip if read-only)
    stored = _store_communities(duckdb_store, community_records)
    elapsed = round(time.time() - start, 3)

    # Build response with capped member lists to keep payload small
    response_communities = []
    for r in community_records:
        response_communities.append({
            "community_id": r["community_id"],
            "name": r["name"],
            "symbol_count": r["symbol_count"],
            "file_count": r["file_count"],
            "cohesion": r["cohesion"],
            "top_kinds": r["top_kinds"],
            "members": r["members"][:50],
            "file_paths": r["file_paths"],
        })

    return {
        "status": "ok",
        "stored": stored,
        "communities": response_communities,
        "community_count": len(community_records),
        "symbol_count": len(nodes),
        "elapsed_seconds": elapsed,
        "timing": {
            "graph_build": graph_time,
            "clustering": cluster_time,
            "enrichment": enrich_time,
            "total": elapsed,
        },
        "compact_summary": {
            "community_count": len(community_records),
            "total_symbols": len(nodes),
            "top_communities": [
                {"name": r["name"], "symbols": r["symbol_count"], "cohesion": r["cohesion"]}
                for r in community_records[:8]
            ],
            "elapsed_seconds": elapsed,
        },
    }


def _store_communities(duckdb_store: DuckDBStore, communities: list[dict[str, object]]) -> bool:
    """Persist community detection results into DuckDB.

    Silently skips storage if the DB is read-only or tables don't exist.
    Returns True if stored, False otherwise.
    """
    try:
        conn = duckdb_store.connection
        conn.execute("DELETE FROM communities")
        conn.execute("DELETE FROM community_members")
        for community in communities:
            conn.execute(
                """
                INSERT INTO communities (
                    community_id, name, symbol_count, file_count, cohesion,
                    top_kinds_json, file_paths_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    community["community_id"],
                    community["name"],
                    community["symbol_count"],
                    community["file_count"],
                    community["cohesion"],
                    json.dumps(community["top_kinds"]),
                    json.dumps(community["file_paths"]),
                ],
            )
            members = community.get("members", [])
            if members:
                batch = [(community["community_id"], str(s)) for s in members]
                conn.executemany(
                    "INSERT INTO community_members (community_id, symbol) VALUES (?, ?)",
                    batch,
                )
    except Exception:
        logger.debug("community: failed to store results (DB may be read-only)", exc_info=True)
        return False
    else:
        return True


def list_communities(
    duckdb_store: DuckDBStore,
    *,
    limit: int = 20,
) -> dict[str, object]:
    """List detected communities from the most recent detection run."""
    rows = duckdb_store.execute(
        """
        SELECT community_id, name, symbol_count, file_count, cohesion, top_kinds_json
        FROM communities
        ORDER BY symbol_count DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    communities = []
    for row in rows:
        communities.append({
            "community_id": str(row[0]),
            "name": str(row[1]),
            "symbol_count": int(row[2] or 0),
            "file_count": int(row[3] or 0),
            "cohesion": float(row[4] or 0.0),
            "top_kinds": json.loads(str(row[5] or "[]")),
        })
    return {
        "status": "ok",
        "communities": communities,
        "community_count": len(communities),
        "compact_summary": {
            "community_count": len(communities),
            "top_communities": [
                {"name": c["name"], "symbols": c["symbol_count"], "cohesion": c["cohesion"]}
                for c in communities[:8]
            ],
        },
    }


def get_community_detail(
    duckdb_store: DuckDBStore,
    community_id: str,
) -> dict[str, object]:
    """Get detailed information about a specific community."""
    rows = duckdb_store.execute(
        """
        SELECT community_id, name, symbol_count, file_count, cohesion, top_kinds_json, file_paths_json
        FROM communities
        WHERE community_id = ?
        LIMIT 1
        """,
        [community_id],
    ).fetchall()
    if not rows:
        return {
            "status": "not_found",
            "community_id": community_id,
            "error": f"Community {community_id} not found. Run detect_communities first.",
        }
    row = rows[0]
    member_rows = duckdb_store.execute(
        "SELECT symbol FROM community_members WHERE community_id = ? ORDER BY symbol",
        [community_id],
    ).fetchall()
    members = [str(r[0]) for r in member_rows]
    return {
        "status": "ok",
        "community_id": str(row[0]),
        "name": str(row[1]),
        "symbol_count": int(row[2] or 0),
        "file_count": int(row[3] or 0),
        "cohesion": float(row[4] or 0.0),
        "top_kinds": json.loads(str(row[5] or "[]")),
        "file_paths": json.loads(str(row[6] or "[]")),
        "members": members,
    }


def get_symbol_community(
    duckdb_store: DuckDBStore,
    target: str,
) -> dict[str, object]:
    """Find which community a symbol belongs to."""
    rows = duckdb_store.execute(
        """
        SELECT cm.community_id, c.name, c.cohesion, c.symbol_count
        FROM community_members cm
        JOIN communities c ON cm.community_id = c.community_id
        WHERE cm.symbol = ?
        LIMIT 1
        """,
        [target],
    ).fetchall()
    if not rows:
        return {
            "status": "not_found",
            "target": target,
            "error": f"Symbol {target} is not in any community. Run detect_communities first.",
        }
    return {
        "status": "ok",
        "target": target,
        "community_id": str(rows[0][0]),
        "community_name": str(rows[0][1]),
        "cohesion": float(rows[0][2] or 0.0),
        "community_size": int(rows[0][3] or 0),
    }
