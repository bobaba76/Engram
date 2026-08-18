from __future__ import annotations

import re
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

_ENTRY_POINT_KINDS = {"module", "exports", "entry_point", "test_file", "component"}

# Regex patterns for detecting route handlers and Pydantic models in chunk content.
# These cover FastAPI, Flask, Django, and Express-style decorators.
_ROUTE_DECORATOR_RE = re.compile(
    r"@(?:app|router|bp|blueprint)\.(?:get|post|put|delete|patch|head|options|route|api_route)\b",
    re.IGNORECASE,
)
_FLASK_ROUTE_RE = re.compile(
    r"@(?:app|bp|blueprint)\.route\b",
    re.IGNORECASE,
)
_DJANGO_URL_RE = re.compile(
    r"path\s*\(\s*[\"'](?:[\w/\-:]+)[\"']\s*,\s*(\w+)\s*[,)]",
    re.IGNORECASE,
)
_PYDANTIC_MODEL_RE = re.compile(
    r"class\s+(\w+)\s*\(.*?BaseModel\b",
    re.IGNORECASE,
)

# Regex patterns for detecting JSX prop usage in React/TSX files.
# Matches patterns like:  onClick={handleClick}  onChange={setVideoSrc}
#   onUpload={handleFileUpload}  render={renderRow}  component={MyComponent}
# Also matches bare identifier references inside JSX expression containers
#   that are not function calls (e.g. {someValue} or {setXxx}).
_JSX_PROP_VALUE_RE = re.compile(
    r"=\s*\{\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*\}",
)
# React hooks and common React component patterns that should be treated as
# entry points (they are called by React itself, not by explicit CALLS edges).
_REACT_ENTRY_POINT_NAMES = {
    "render", "componentdidmount", "componentdidupdate", "componentwillunmount",
    "shouldcomponentupdate", "getderivedstatefromprops", "getsnapshotbeforeupdate",
    "getderivedstatefromerror", "componentdidcatch",
}
_REACT_HOOK_NAMES = {
    "usestate", "useeffect", "usereducer", "usecontext", "usecallback",
    "usememo", "useref", "useimperativehandle", "uselayouteffect",
    "usedebugvalue", "useid", "usesyncexternalstore", "usetransition",
    "usedeferredvalue", "useinsertioneffect",
}


def _is_entry_point(qualified_name: str, kind: str = "") -> bool:
    name_lower = qualified_name.lower()
    kind_lower = str(kind or "").lower()
    if kind_lower in _ENTRY_POINT_KINDS:
        return True
    tail = name_lower.rsplit(".", 1)[-1]
    if any(pattern in tail for pattern in _ENTRY_POINT_PATTERNS):
        return True
    # React lifecycle methods and hooks are entry points (called by React runtime)
    if tail in _REACT_ENTRY_POINT_NAMES or tail in _REACT_HOOK_NAMES:
        return True
    return False


def _scan_chunks_for_entry_points(duckdb_store: "DuckDBStore") -> tuple[set[str], set[str]]:
    """Scan chunk content for route decorators and Pydantic models.

    Returns a tuple of (route_handler_qualified_names, pydantic_model_qualified_names).
    """
    route_handlers: set[str] = set()
    pydantic_models: set[str] = set()

    try:
        rows = duckdb_store.execute(
            "SELECT file_path, symbol_name, start_line, content FROM chunks "
            "WHERE content LIKE '%@app.%' OR content LIKE '%@router.%' "
            "OR content LIKE '%@bp.%' OR content LIKE '%@blueprint.%' "
            "OR content LIKE '%BaseModel%'"
        ).fetchall()
    except Exception:
        return route_handlers, pydantic_models

    # Build a lookup from (file_path, symbol_name) to qualified_name via symbols table
    sym_rows = duckdb_store.execute(
        "SELECT qualified_name, name, file_path, start_line FROM symbols"
    ).fetchall()
    # Map: (file_path_lower, name_lower) -> list of (qualified_name, start_line)
    sym_lookup: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for qn, name, fp, line in sym_rows:
        key = (str(fp or "").lower(), str(name or "").lower())
        sym_lookup.setdefault(key, []).append((str(qn or ""), int(line or 0)))

    for file_path, symbol_name, start_line, content in rows:
        if not content:
            continue
        fp_lower = str(file_path or "").lower()
        sym_lower = str(symbol_name or "").lower()

        # Check for route decorators in the content
        if _ROUTE_DECORATOR_RE.search(content) or _FLASK_ROUTE_RE.search(content):
            # The symbol_name in the chunk is the function being decorated
            candidates = sym_lookup.get((fp_lower, sym_lower), [])
            for qn, _ in candidates:
                route_handlers.add(qn)

        # Check for Pydantic model definitions
        for match in _PYDANTIC_MODEL_RE.finditer(content):
            model_name = match.group(1)
            candidates = sym_lookup.get((fp_lower, model_name.lower()), [])
            for qn, _ in candidates:
                pydantic_models.add(qn)

    return route_handlers, pydantic_models


def _scan_chunks_for_jsx_prop_usage(duckdb_store: "DuckDBStore") -> set[str]:
    """Scan JSX/TSX chunk content for symbols passed as props or used in JSX.

    React components pass functions as props (e.g. ``onClick={handleClick}``,
    ``onChange={setVideoSrc}``) and reference state setters directly in JSX.
    These usages don't create CALLS/REFERENCES graph edges, so the dead code
    detector would falsely flag them as dead. This function scans chunk content
    in ``.jsx``/``.tsx`` files for identifier references inside JSX expression
    containers and returns the set of qualified_names that are referenced.
    """
    referenced: set[str] = set()
    try:
        rows = duckdb_store.execute(
            "SELECT file_path, symbol_name, content FROM chunks "
            "WHERE file_path LIKE '%.jsx' OR file_path LIKE '%.tsx' "
            "OR file_path LIKE '%.jsx.ts' OR file_path LIKE '%.ts'"
        ).fetchall()
    except Exception:
        return referenced

    # Build a lookup from (file_path_lower, name_lower) -> list of qualified_names
    sym_rows = duckdb_store.execute(
        "SELECT qualified_name, name, file_path FROM symbols"
    ).fetchall()
    # Also build a global name -> qualified_names index for cross-file prop usage
    global_sym_lookup: dict[str, list[str]] = {}
    sym_lookup: dict[tuple[str, str], list[str]] = {}
    for qn, name, fp in sym_rows:
        qn_str = str(qn or "")
        name_lower = str(name or "").lower()
        fp_lower = str(fp or "").lower()
        if qn_str and name_lower:
            sym_lookup.setdefault((fp_lower, name_lower), []).append(qn_str)
            global_sym_lookup.setdefault(name_lower, []).append(qn_str)

    for file_path, symbol_name, content in rows:
        if not content:
            continue
        fp_lower = str(file_path or "").lower()

        # Find all identifiers used as JSX prop values: prop={identifier}
        for match in _JSX_PROP_VALUE_RE.finditer(content):
            ident = match.group(1)
            if not ident:
                continue
            ident_lower = ident.lower()
            # Try same-file match first (most common case)
            candidates = sym_lookup.get((fp_lower, ident_lower), [])
            if candidates:
                referenced.update(candidates)
            else:
                # Fall back to global match (e.g. imported symbols)
                global_candidates = global_sym_lookup.get(ident_lower, [])
                if global_candidates:
                    referenced.update(global_candidates)

        # Also detect component render functions and React lifecycle methods
        # by checking if the symbol name matches known React entry points
        sym_lower = str(symbol_name or "").lower()
        if sym_lower in _REACT_ENTRY_POINT_NAMES or sym_lower in _REACT_HOOK_NAMES:
            candidates = sym_lookup.get((fp_lower, sym_lower), [])
            referenced.update(candidates)

    return referenced


# Pattern for detecting function calls in chunk content: identifier followed by (
# Used as a fallback when graph CALLS edges are missing (e.g. indirect calls,
# string-based dispatch, or parser limitations with f-strings/dynamic calls).
_CALL_PATTERN_RE = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")


def _scan_chunks_for_call_references(duckdb_store: "DuckDBStore") -> set[str]:
    """Scan all chunk content for function call patterns as a fallback.

    The graph may miss CALLS edges for indirect calls, f-string interpolations,
    or parser limitations. This function scans chunk content for
    ``identifier(`` patterns and marks matching symbols as referenced.
    Only matches symbols that are already in the symbols table, so it won't
    produce false positives from string literals or comments that happen to
    look like calls.
    """
    referenced: set[str] = set()
    try:
        # Build a global name -> qualified_names index
        sym_rows = duckdb_store.execute(
            "SELECT qualified_name, name FROM symbols"
        ).fetchall()
        name_to_qns: dict[str, list[str]] = {}
        for qn, name in sym_rows:
            qn_str = str(qn or "")
            name_lower = str(name or "").lower()
            if qn_str and name_lower:
                name_to_qns.setdefault(name_lower, []).append(qn_str)

        # Scan all chunk content for call patterns
        chunk_rows = duckdb_store.execute(
            "SELECT content FROM chunks"
        ).fetchall()
        for (content,) in chunk_rows:
            if not content:
                continue
            for match in _CALL_PATTERN_RE.finditer(content):
                ident_lower = match.group(1).lower()
                candidates = name_to_qns.get(ident_lower)
                if candidates:
                    referenced.update(candidates)
    except Exception:
        pass
    return referenced


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
    # Scan chunks for route decorators and Pydantic models to exclude them
    route_handlers, pydantic_models = _scan_chunks_for_entry_points(duckdb_store)
    # Scan JSX/TSX chunks for symbols passed as props (React-specific false positives)
    jsx_referenced = _scan_chunks_for_jsx_prop_usage(duckdb_store)
    referenced.update(jsx_referenced)
    # Fallback: scan chunk content for call patterns to catch missing graph edges
    call_referenced = _scan_chunks_for_call_references(duckdb_store)
    referenced.update(call_referenced)
    dead_symbols: list[dict[str, object]] = []
    for qn, sym in all_qualified.items():
        if qn in referenced:
            continue
        kind = str(sym.get("kind", "") or "")
        if _is_entry_point(qn, kind):
            continue
        if qn in route_handlers:
            continue
        if qn in pydantic_models:
            continue
        file_path = str(sym.get("file_path", "") or "")
        # Skip test files — they're entry points by nature
        if "/test" in file_path.lower() or "/tests/" in file_path.lower() or ".test." in file_path.lower() or ".spec." in file_path.lower():
            continue
        name = str(sym.get("name", "") or "")
        # React/JS destructuring patterns (e.g. `[activeTab, setActiveTab]` from
        # useState) are synthetic binding symbols — the pattern is used via its
        # bare member names in JSX, which the graph can't resolve back to the
        # tuple, so they read as "dead". Not actionable; skip them.
        if name.startswith("[") or name.startswith("{"):
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
