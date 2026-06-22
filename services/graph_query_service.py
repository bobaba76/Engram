from __future__ import annotations

import re

from storage.kuzu_store import KuzuStore


DEFAULT_QUERY_LIMIT = 100

_BLOCKED_PATTERNS = [
    re.compile(r"\bDROP\b", re.IGNORECASE),
    re.compile(r"\bDETACH\s+DELETE\b", re.IGNORECASE),
    re.compile(r"\bCREATE\b\s+\(", re.IGNORECASE),
    re.compile(r"\bMERGE\b", re.IGNORECASE),
    re.compile(r"\bSET\b", re.IGNORECASE),
    re.compile(r"\bREMOVE\b", re.IGNORECASE),
    re.compile(r"\bDELETE\b", re.IGNORECASE),
    re.compile(r"\bCOPY\b", re.IGNORECASE),
    re.compile(r"\bIMPORT\b", re.IGNORECASE),
    re.compile(r"\bEXPORT\b", re.IGNORECASE),
    re.compile(r"--", re.IGNORECASE),
    re.compile(r"/\*"),
]


def execute_graph_query(kuzu_store: KuzuStore, query: str, limit: int = DEFAULT_QUERY_LIMIT) -> dict[str, object]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("query is required")
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(normalized_query):
            raise ValueError(f"query contains blocked operation: {pattern.pattern}")
    lowered = normalized_query.lower()
    result = kuzu_store.execute_query(normalized_query)
    sample_rows = result.get("rows", [])[:10]
    warnings: list[str] = []
    if " limit " not in lowered:
        warnings.append(
            f"Query has no LIMIT clause. Consider adding one explicitly, for example LIMIT {max(limit, 1)}."
        )
    return {
        **result,
        "compact_summary": {
            "target": normalized_query,
            "row_count": result.get("row_count", 0),
            "columns": result.get("columns", []),
            "sample_rows": sample_rows,
            "warnings": warnings,
        },
    }
