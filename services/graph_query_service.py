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

# Graph schema documentation. This is the authoritative reference for what
# node labels, properties, and relationship types exist in the KuzuDB graph.
# It is returned when the user queries "schema" and is embedded in the tool
# description so agents can construct valid Cypher queries without trial-and-error.
GRAPH_SCHEMA = {
    "node_tables": [
        {
            "label": "File",
            "properties": {"path": "STRING (primary key)"},
            "description": "A source file in the indexed repository.",
        },
        {
            "label": "Symbol",
            "properties": {
                "qualified_name": "STRING (primary key)",
                "file_path": "STRING",
                "kind": "STRING (function, class, method, variable, etc.)",
                "start_line": "INT64",
                "end_line": "INT64",
            },
            "description": "A code symbol (function, class, method, variable, etc.) defined in a file.",
        },
    ],
    "relationship_tables": [
        {"label": "DEFINES", "from": "File", "to": "Symbol", "description": "A file defines a symbol.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "CALLS", "from": "Symbol", "to": "Symbol", "description": "A symbol calls another symbol (function/method call).", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "IMPORTS", "from": "Symbol", "to": "Symbol", "description": "A symbol imports another symbol or module.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "REFERENCES", "from": "Symbol", "to": "Symbol", "description": "A symbol references another (type reference, variable use).", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "DECLARES", "from": "Symbol", "to": "Symbol", "description": "A symbol declares another (e.g. class declares method).", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "ASSOCIATED_WITH", "from": "Symbol", "to": "Symbol", "description": "General association between symbols.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "ACCESSES", "from": "Symbol", "to": "Symbol", "description": "A symbol accesses a property or field of another.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "INCLUDES", "from": "Symbol", "to": "Symbol", "description": "C/C++ include relationship.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "DECLARES_IN_HEADER", "from": "Symbol", "to": "Symbol", "description": "C/C++ header declaration.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "DEFINES_IMPLEMENTATION", "from": "Symbol", "to": "Symbol", "description": "C/C++ implementation definition.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "INJECTS", "from": "Symbol", "to": "Symbol", "description": "Dependency injection relationship.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "USES_SERVICE", "from": "Symbol", "to": "Symbol", "description": "A symbol uses a service.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "FETCHES", "from": "Symbol", "to": "Symbol", "description": "A symbol fetches data from a source.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "READS_FIELD", "from": "Symbol", "to": "Symbol", "description": "A symbol reads a field.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "HAS_METHOD", "from": "Symbol", "to": "Symbol", "description": "A class/type has a method.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "HAS_PROPERTY", "from": "Symbol", "to": "Symbol", "description": "A class/type has a property.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "EXTENDS", "from": "Symbol", "to": "Symbol", "description": "A symbol extends/inherits from another (class inheritance).", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "IMPLEMENTS", "from": "Symbol", "to": "Symbol", "description": "A symbol implements an interface.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "METHOD_OVERRIDES", "from": "Symbol", "to": "Symbol", "description": "A method overrides a parent class method.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
        {"label": "METHOD_IMPLEMENTS", "from": "Symbol", "to": "Symbol", "description": "A method implements an interface method.", "properties": {"confidence": "STRING (EXTRACTED | INFERRED | AMBIGUOUS) — provenance of the edge"}},
    ],
    "edge_confidence": {
        "values": ["EXTRACTED", "INFERRED", "AMBIGUOUS"],
        "description": "Every relationship carries a confidence property indicating whether it was parsed directly from source (EXTRACTED) or derived by a heuristic (INFERRED). AMBIGUOUS is reserved for edges whose source cannot be cleanly classified. Query with `r.confidence` to filter, e.g. MATCH (s1)-[r:CALLS]->(s2) WHERE r.confidence = 'EXTRACTED' RETURN ...",
    },
    "example_queries": [
        "MATCH (f:File)-[:DEFINES]->(s:Symbol) WHERE f.path = 'src/main.py' RETURN s.qualified_name, s.kind",
        "MATCH (s1:Symbol)-[:CALLS]->(s2:Symbol) WHERE s1.qualified_name = 'myFunc' RETURN s2.qualified_name",
        "MATCH (s:Symbol)-[:IMPORTS]->(t:Symbol) RETURN s.file_path, t.qualified_name LIMIT 20",
        "MATCH (c:Symbol)-[:EXTENDS]->(p:Symbol) WHERE c.kind = 'class' RETURN c.qualified_name, p.qualified_name",
    ],
}

_SCHEMA_QUERY_RE = re.compile(r"^\s*(schema|help\s+schema|show\s+schema)\s*$", re.IGNORECASE)


def _schema_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "schema": GRAPH_SCHEMA,
        "summary_text": (
            f"Graph schema: {len(GRAPH_SCHEMA['node_tables'])} node tables "
            f"({', '.join(n['label'] for n in GRAPH_SCHEMA['node_tables'])}), "
            f"{len(GRAPH_SCHEMA['relationship_tables'])} relationship tables. "
            "Use the example_queries to construct valid Cypher queries."
        ),
        "highlights": [
            f"Node tables: {', '.join(n['label'] for n in GRAPH_SCHEMA['node_tables'])}",
            f"Relationships: {', '.join(r['label'] for r in GRAPH_SCHEMA['relationship_tables'][:8])}...",
        ],
        "compact_summary": {
            "target": "schema",
            "node_labels": [n["label"] for n in GRAPH_SCHEMA["node_tables"]],
            "relationship_labels": [r["label"] for r in GRAPH_SCHEMA["relationship_tables"]],
            "example_queries": GRAPH_SCHEMA["example_queries"][:3],
        },
    }


def execute_graph_query(kuzu_store: KuzuStore, query: str, limit: int = DEFAULT_QUERY_LIMIT) -> dict[str, object]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("query is required")
    # Special case: return schema documentation instead of executing a query
    if _SCHEMA_QUERY_RE.match(normalized_query):
        payload = _schema_payload()
        payload["confidence"] = "high"
        payload["compact_summary"]["confidence"] = "high"
        return payload
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(normalized_query):
            raise ValueError(f"query contains blocked operation: {pattern.pattern}")
    lowered = normalized_query.lower()
    result = kuzu_store.execute_query(normalized_query)
    sample_rows = result.get("rows", [])[:10]
    row_count = int(result.get("row_count", 0) or 0)
    warnings: list[str] = []
    # Only warn about missing LIMIT when the result set is large enough to matter
    if " limit " not in lowered and row_count > 50:
        warnings.append(
            f"Query has no LIMIT clause. Consider adding one explicitly, for example LIMIT {max(limit, 1)}."
        )
    # Confidence calibration: graph queries are deterministic, so confidence
    # is based on whether the query returned results.
    if row_count > 0:
        confidence = "high"
    elif result.get("columns"):
        confidence = "medium"
    else:
        confidence = "low"
    return {
        **result,
        "confidence": confidence,
        "compact_summary": {
            "target": normalized_query,
            "row_count": result.get("row_count", 0),
            "columns": result.get("columns", []),
            "sample_rows": sample_rows,
            "warnings": warnings,
            "confidence": confidence,
        },
    }
