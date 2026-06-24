from __future__ import annotations

from typing import TYPE_CHECKING

from services.graph_service import _symbol_to_file_map

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


_CYCLE_RELATIONS = ("IMPORTS", "INCLUDES", "CALLS", "REFERENCES", "EXTENDS", "IMPLEMENTS")

_ENTRY_POINT_PATTERNS = (
    "main", "exports", "__init__", "index", "app", "server", "run", "start",
    "setup", "create_app", "handler", "lambda_handler", "cli",
)

_ENTRY_POINT_KINDS = {"module", "exports", "entry_point", "test_file"}


def _is_entry_point(qualified_name: str, kind: str = "") -> bool:
    name_lower = qualified_name.lower()
    kind_lower = str(kind or "").lower()
    if kind_lower in _ENTRY_POINT_KINDS:
        return True
    tail = name_lower.rsplit(".", 1)[-1]
    return any(pattern in tail for pattern in _ENTRY_POINT_PATTERNS)


def detect_circular_dependencies(
    kuzu_store: KuzuStore,
    duckdb_store: DuckDBStore,
    relation: str = "IMPORTS",
    max_cycles: int = 20,
    max_depth: int = 10,
) -> dict[str, object]:
    """Detect circular dependencies in the graph via DFS.

    Walks the graph following the specified relation (default: IMPORTS) and
    finds cycles using a depth-first search with a visited-path stack.
    """
    relation_upper = str(relation or "IMPORTS").upper()
    edges = kuzu_store.edges_for_relation(relation_upper)
    if not edges:
        return {
            "relation": relation_upper,
            "status": "ok",
            "cycle_count": 0,
            "cycles": [],
            "compact_summary": {
                "relation": relation_upper,
                "cycle_count": 0,
            },
        }

    # Build adjacency list
    adj: dict[str, list[str]] = {}
    for edge in edges:
        src = str(edge.get("source", "") or "")
        tgt = str(edge.get("target", "") or "")
        if src and tgt:
            adj.setdefault(src, []).append(tgt)

    # DFS cycle detection
    cycles: list[list[str]] = []
    visited: set[str] = set()
    path: list[str] = []
    path_set: set[str] = set()

    def _dfs(node: str) -> None:
        if len(cycles) >= max_cycles:
            return
        if node in path_set:
            # Found a cycle — extract it
            cycle_start = path.index(node)
            cycle = path[cycle_start:] + [node]
            cycles.append(cycle)
            return
        if node in visited:
            return
        path.append(node)
        path_set.add(node)
        for neighbor in adj.get(node, []):
            _dfs(neighbor)
            if len(cycles) >= max_cycles:
                break
        path.pop()
        path_set.discard(node)
        visited.add(node)

    for start_node in sorted(adj.keys()):
        if len(cycles) >= max_cycles:
            break
        if start_node not in visited:
            _dfs(start_node)

    # Map symbols to files
    all_symbols: set[str] = set()
    for cycle in cycles:
        all_symbols.update(cycle)
    sym_to_file = _symbol_to_file_map(duckdb_store, all_symbols)

    # Enrich cycles with file info
    enriched_cycles: list[dict[str, object]] = []
    for cycle in cycles:
        enriched_cycles.append({
            "path": cycle,
            "length": len(cycle) - 1,
            "files": sorted(set(
                sym_to_file.get(sym, "")
                for sym in cycle
                if sym_to_file.get(sym, "")
            )),
            "symbols": cycle,
        })

    # Find files involved in the most cycles
    file_cycle_count: dict[str, int] = {}
    for cycle_data in enriched_cycles:
        for fp in cycle_data["files"]:
            file_cycle_count[fp] = file_cycle_count.get(fp, 0) + 1

    hotspots = sorted(file_cycle_count.items(), key=lambda x: x[1], reverse=True)

    return {
        "relation": relation_upper,
        "status": "ok",
        "cycle_count": len(cycles),
        "cycles": enriched_cycles,
        "hotspot_files": [{"file_path": fp, "cycle_count": count} for fp, count in hotspots[:20]],
        "compact_summary": {
            "relation": relation_upper,
            "cycle_count": len(cycles),
            "max_cycle_length": max((c["length"] for c in enriched_cycles), default=0),
            "hotspot_files": [fp for fp, _ in hotspots[:8]],
        },
    }


def detect_dead_code(
    kuzu_store: KuzuStore,
    duckdb_store: DuckDBStore,
    relation: str = "",
    limit: int = 50,
    file_pattern: str = "",
) -> dict[str, object]:
    """Detect potentially dead code — symbols with zero inbound dependency edges.

    A symbol is considered "dead" if no other symbol CALLS, REFERENCES, IMPORTS,
    or otherwise depends on it (excluding entry points like main, exports, routes).

    If *file_pattern* is given (e.g. ``"*.py"``, ``"backend/**"``), only symbols
    whose file path matches the pattern are included in the results.
    """
    # Fetch only needed columns from symbols table (avoid loading full metadata)
    import time as _time
    import fnmatch
    _start = _time.time()
    pattern = str(file_pattern or "").strip().lower()
    rows = duckdb_store.execute(
        "SELECT qualified_name, name, kind, file_path, start_line FROM symbols"
    ).fetchall()
    if not rows:
        return {
            "status": "ok",
            "dead_symbol_count": 0,
            "total_symbols": 0,
            "dead_symbols": [],
            "compact_summary": {
                "status": "ok",
                "dead_symbol_count": 0,
                "total_symbols": 0,
            },
        }

    # Build a set of all qualified names
    all_qualified: dict[str, dict[str, object]] = {}
    for row in rows:
        qn = str(row[0] or "").strip()
        if not qn:
            continue
        file_path = str(row[3] or "")
        if pattern:
            normalized = file_path.replace("\\", "/").lower()
            if not (fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(normalized, f"*/{pattern}")):
                continue
        all_qualified[qn] = {
            "qualified_name": qn,
            "name": str(row[1] or ""),
            "kind": str(row[2] or ""),
            "file_path": file_path,
            "start_line": row[4],
        }

    # Collect all symbols that ARE referenced (have inbound edges)
    referenced: set[str] = set()
    relations_to_check = [relation.upper()] if relation else [
        "CALLS", "REFERENCES", "IMPORTS", "INCLUDES", "EXTENDS", "IMPLEMENTS",
        "USES_SERVICE", "INJECTS", "ASSOCIATED_WITH", "HAS_METHOD", "HAS_PROPERTY",
        "METHOD_OVERRIDES", "METHOD_IMPLEMENTS",
    ]

    _EDGE_LIMIT_PER_RELATION = 10000
    for rel in relations_to_check:
        edges = kuzu_store.edges_for_relation(rel)
        for i, edge in enumerate(edges):
            if i >= _EDGE_LIMIT_PER_RELATION:
                break
            tgt = str(edge.get("target", "") or "")
            if tgt:
                referenced.add(tgt)
        if _time.time() - _start > 30:
            break

    # Dead symbols: in all_qualified but not in referenced, and not an entry point
    dead_symbols: list[dict[str, object]] = []
    for qn, sym in all_qualified.items():
        if qn in referenced:
            continue
        kind = str(sym.get("kind", "") or "")
        if _is_entry_point(qn, kind):
            continue
        file_path = str(sym.get("file_path", "") or "")
        # Skip test files — they're entry points by nature
        if "/test" in file_path.lower() or "/tests/" in file_path.lower() or ".test." in file_path.lower() or ".spec." in file_path.lower():
            continue
        dead_symbols.append({
            "qualified_name": qn,
            "name": str(sym.get("name", "") or ""),
            "kind": kind,
            "file_path": file_path,
            "start_line": sym.get("start_line"),
        })

    # Sort by file path for readability
    dead_symbols.sort(key=lambda s: (s.get("file_path", ""), s.get("qualified_name", "")))

    # Group by file
    by_file: dict[str, list[str]] = {}
    for sym in dead_symbols:
        fp = sym.get("file_path", "")
        by_file.setdefault(fp, []).append(sym["qualified_name"])

    file_summary = sorted(
        [{"file_path": fp, "dead_count": len(syms), "symbols": syms[:5]} for fp, syms in by_file.items()],
        key=lambda x: x["dead_count"],
        reverse=True,
    )

    total = len(all_qualified)
    dead_count = len(dead_symbols)
    dead_pct = (dead_count / total * 100) if total > 0 else 0.0

    return {
        "status": "ok",
        "total_symbols": total,
        "dead_symbol_count": dead_count,
        "dead_percentage": round(dead_pct, 1),
        "dead_symbols": dead_symbols[:limit],
        "dead_by_file": file_summary[:30],
        "compact_summary": {
            "status": "ok",
            "total_symbols": total,
            "dead_symbol_count": dead_count,
            "dead_percentage": round(dead_pct, 1),
            "dead_file_count": len(by_file),
            "top_dead_files": [item["file_path"] for item in file_summary[:8]],
        },
    }
