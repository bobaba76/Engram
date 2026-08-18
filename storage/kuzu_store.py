from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import local as ThreadLocal
from typing import Any

import kuzu

logger = logging.getLogger(__name__)
 
def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")
 
def _is_already_exists_error(exc: RuntimeError) -> bool:
    message = str(exc).lower()
    return "already exists" in message or "catalog exception" in message
 
def _safe_get_all(result) -> list[tuple[Any, ...]]:
    try:
        return result.get_all()
    except RuntimeError:
        logger.debug("kuzu: _safe_get_all failed", exc_info=True)
        return []

SYMBOL_RELATIONS = (
    "IMPORTS",
    "INCLUDES",
    "CALLS",
    "REFERENCES",
    "DECLARES",
    "DECLARES_IN_HEADER",
    "DEFINES_IMPLEMENTATION",
    "INJECTS",
    "USES_SERVICE",
    "ASSOCIATED_WITH",
    "ACCESSES",
    "HAS_METHOD",
    "HAS_PROPERTY",
    "FETCHES",
    "READS_FIELD",
    "EXTENDS",
    "IMPLEMENTS",
    "METHOD_OVERRIDES",
    "METHOD_IMPLEMENTS",
)

# Default confidence tag for edges that do not declare one (e.g. edges
# written by older indexers before the confidence column existed, or edges
# in relation tables that predate the schema migration). Reads always
# surface a confidence value — never None — so consumers can branch on it
# without null-checking.
DEFAULT_EDGE_CONFIDENCE = "EXTRACTED"

def _result_columns(result) -> list[str]:
    try:
        return [str(name) for name in result.get_column_names()]
    except Exception:
        logger.debug("kuzu: _result_columns failed", exc_info=True)
        return []

class KuzuStore:
    def __init__(self, data_path: Path, read_only: bool = False) -> None:
        self.data_path = data_path
        self.read_only = read_only
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread_local = ThreadLocal()
        self.database = kuzu.Database(str(self.data_path), read_only=read_only)
        if not self.read_only:
            self._initialize_schema()

    @property
    def connection(self):
        """Return a thread-local kuzu.Connection.

        KuzuDB connections are not thread-safe.  When ``run_with_timeout``
        runs a query in a ThreadPoolExecutor, the background thread must
        not share the same connection as the main thread.  Creating a
        separate connection per thread on the shared Database avoids
        the deadlock.
        """
        conn = getattr(self._thread_local, "conn", None)
        if conn is None:
            conn = kuzu.Connection(self.database)
            self._thread_local.conn = conn
        return conn

    def close(self) -> None:
        self._thread_local = ThreadLocal()
        self.database = None

    def _safe_execute(self, query: str, parameters: dict[str, Any] | None = None):
        """Execute a query on the thread-local KuzuDB connection.

        Each thread gets its own ``kuzu.Connection`` on the shared
        ``kuzu.Database``, preventing concurrent-access deadlocks when
        ``run_with_timeout`` runs queries in a ThreadPoolExecutor.
        """
        return self.connection.execute(query, parameters or {})

    _available_relations_cache: dict[str, frozenset[str]] = {}

    def available_relations(self) -> frozenset[str]:
        """Return the set of relation table names that exist in this Kuzu database.

        Cached per database path to avoid repeated schema introspection.
        """
        cache_key = str(self.data_path) if hasattr(self, "data_path") else "default"
        cached = KuzuStore._available_relations_cache.get(cache_key)
        if cached is not None:
            return cached
        available: set[str] = set()
        try:
            result = self._safe_execute("CALL show_tables() RETURN *")
            rows = _safe_get_all(result)
            for row in rows:
                if row and len(row) >= 2:
                    table_name = str(row[1]).upper()
                    available.add(table_name)
        except RuntimeError:
            # Fallback: probe each known relation
            for rel in SYMBOL_RELATIONS:
                try:
                    self._safe_execute(f"MATCH (s1:Symbol)-[:{rel}]->(s2:Symbol) RETURN COUNT(*) LIMIT 1")
                    available.add(rel)
                except RuntimeError:
                    pass
        result_set = frozenset(available)
        KuzuStore._available_relations_cache[cache_key] = result_set
        return result_set

    def _existing_symbol_relations(self) -> tuple[str, ...]:
        """Return only SYMBOL_RELATIONS that exist as tables in this database."""
        available = self.available_relations()
        return tuple(rel for rel in SYMBOL_RELATIONS if rel in available)

    def _initialize_schema(self) -> None:
        try:
            self._safe_execute("CREATE NODE TABLE File(path STRING, PRIMARY KEY(path))")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self._safe_execute(
                "CREATE NODE TABLE Symbol(qualified_name STRING, file_path STRING, kind STRING, start_line INT64, end_line INT64, PRIMARY KEY(qualified_name))"
            )
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise

        # KuzuDB's PRIMARY KEY automatically creates an internal index on
        # the PK column, so MATCH on {qualified_name: ...} / {path: ...}
        # should use it. KuzuDB 0.11 does not support explicit CREATE INDEX
        # for secondary indexes (only HNSW/FTS via CALL). If the planner
        # fails to use the PK index for UNWIND + MATCH, the per-batch
        # progress logging in bulk_add_edges will reveal it.

        # Relationship tables carry a `confidence` property (EXTRACTED vs
        # INFERRED) so consumers can tell parsed edges from heuristic ones.
        # Old indexes that predate this column are handled transparently:
        # `_relation_confidence_supported` probes the schema and reads fall
        # back to the 3-column query, defaulting missing tags to EXTRACTED.
        # For indexes created before the confidence column existed, the REL
        # TABLE already exists without the column, so CREATE fails with
        # "already exists" — we then ALTER TABLE to add the missing column.
        self._ensure_rel_table_with_confidence("DEFINES")
        for relation in ("IMPORTS", "CALLS", "REFERENCES", "DECLARES", "ASSOCIATED_WITH", "ACCESSES"):
            self._ensure_rel_table_with_confidence(relation)
        for relation in ("INCLUDES", "DECLARES_IN_HEADER", "DEFINES_IMPLEMENTATION", "INJECTS", "USES_SERVICE", "FETCHES", "READS_FIELD", "HAS_METHOD", "HAS_PROPERTY", "EXTENDS", "IMPLEMENTS", "METHOD_OVERRIDES", "METHOD_IMPLEMENTS"):
            self._ensure_rel_table_with_confidence(relation)
        # Invalidate the confidence-column probe cache — schema may have
        # changed via ALTER TABLE above, so re-probe on next access.
        KuzuStore._confidence_column_cache.pop(str(self.data_path), None)
    def _ensure_rel_table_with_confidence(self, relation: str) -> None:
        """Create REL TABLE with confidence column, or ALTER to add it.
        Tries CREATE first. If the table already exists, probes for the
        confidence column and runs ALTER TABLE ADD if missing. This
        handles indexes created before the confidence column existed.
        """
        from_clause = "FROM File TO Symbol" if relation == "DEFINES" else "FROM Symbol TO Symbol"

        try:

            self._safe_execute(f"CREATE REL TABLE {relation}({from_clause}, confidence STRING)")
            return

        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise

        # Table already exists — check if confidence column is present.
        # Use a targeted probe instead of the cached _relation_confidence_supported
        # because the cache may hold a stale False from a prior probe.
        if relation == "DEFINES":
            probe = "MATCH (f:File)-[r:DEFINES]->(s:Symbol) RETURN r.confidence LIMIT 1"
        else:
            probe = f"MATCH (s1:Symbol)-[r:{relation}]->(s2:Symbol) RETURN r.confidence LIMIT 1"

        try:

            self._safe_execute(probe)
            # Column already present — nothing to do.
            return
        except RuntimeError:
            pass
        # Column missing — ALTER TABLE to add it. Existing edges get NULL,
        # which _rows_to_edges defaults to EXTRACTED on read.
        try:
            self._safe_execute(f"ALTER TABLE {relation} ADD confidence STRING")
            logger.info("kuzu: added confidence column to %s via ALTER TABLE", relation)

        except RuntimeError as exc:

            # If ALTER also fails (e.g. column somehow already there), log
            # and continue — reads will fall back to the 3-column query.
            logger.warning("kuzu: could not add confidence column to %s: %s", relation, exc)

    def reset(self) -> None:
        for query in (
            "MATCH (f:File) DETACH DELETE f",
            "MATCH (s:Symbol) DETACH DELETE s",
        ):
            try:
                self._safe_execute(query)
            except RuntimeError:
                logger.debug("kuzu: reset_index_data failed for query: %s", query, exc_info=True)

    def delete_index_data_for_files(self, file_paths: list[str]) -> None:
        if not file_paths:
            return
        for file_path in file_paths:
            try:
                self._safe_execute(
                    "MATCH (f:File {path: $file_path}) DETACH DELETE f",
                    {"file_path": file_path},
                )
            except RuntimeError:
                logger.debug("kuzu: delete file node failed for %s", file_path, exc_info=True)
            try:
                self._safe_execute(
                    "MATCH (s:Symbol {file_path: $file_path}) DETACH DELETE s",
                    {"file_path": file_path},
                )
            except RuntimeError:
                logger.debug("kuzu: delete symbol node failed for %s", file_path, exc_info=True)
 
    def ensure_file(self, path: str) -> None:
        result = self._safe_execute(
            "MATCH (f:File {path: $path}) RETURN f.path LIMIT 1",
            {"path": path},
        )
        if result.get_num_tuples() == 0:
            self._safe_execute("CREATE (f:File {path: $path})", {"path": path})
 
    def ensure_symbol(self, qualified_name: str, file_path: str, kind: str, start_line: int, end_line: int) -> None:
        result = self._safe_execute(
            "MATCH (s:Symbol {qualified_name: $qualified_name}) RETURN s.qualified_name LIMIT 1",
            {"qualified_name": qualified_name},
        )
        if result.get_num_tuples() == 0:
            self._safe_execute(
                """
                CREATE (s:Symbol {
                    qualified_name: $qualified_name,
                    file_path: $file_path,
                    kind: $kind,
                    start_line: $start_line,
                    end_line: $end_line
                })
                """,
                {
                    "qualified_name": qualified_name,
                    "file_path": file_path,
                    "kind": kind,
                    "start_line": start_line,
                    "end_line": end_line,
                },
            )

    def add_edge(self, source: str, relation: str, target: str, confidence: str = DEFAULT_EDGE_CONFIDENCE) -> None:
        normalized_confidence = confidence if confidence in {"EXTRACTED", "INFERRED", "AMBIGUOUS"} else DEFAULT_EDGE_CONFIDENCE
        if relation == "DEFINES":
            query = "MATCH (f:File {path: $source}), (s:Symbol {qualified_name: $target}) CREATE (f)-[:DEFINES {confidence: $confidence}]->(s)"
        else:
            query = f"MATCH (source:Symbol {{qualified_name: $source}}), (target:Symbol {{qualified_name: $target}}) CREATE (source)-[:{relation} {{confidence: $confidence}}]->(target)"
        try:
            self._safe_execute(query, {"source": source, "target": target, "confidence": normalized_confidence})
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "already exists" in msg or "duplicate" in msg:
                logger.debug("kuzu: duplicate edge skipped %s -[%s]-> %s", source, relation, target)
            elif "confidence" in msg and ("property" in msg or "column" in msg or "unknown" in msg):
                # Old index whose REL TABLE predates the confidence column.
                # Fall back to the property-less CREATE so indexing still
                # succeeds; reads will surface DEFAULT_EDGE_CONFIDENCE.
                self._add_edge_legacy(source, relation, target)
            else:
                logger.warning("kuzu: add_edge failed for %s -[%s]-> %s", source, relation, target, exc_info=True)
    def _add_edge_legacy(self, source: str, relation: str, target: str) -> None:

        if relation == "DEFINES":
            query = "MATCH (f:File {path: $source}), (s:Symbol {qualified_name: $target}) CREATE (f)-[:DEFINES]->(s)"
        else:
            query = f"MATCH (source:Symbol {{qualified_name: $source}}), (target:Symbol {{qualified_name: $target}}) CREATE (source)-[:{relation}]->(target)"
        try:
            self._safe_execute(query, {"source": source, "target": target})
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "already exists" in msg or "duplicate" in msg:
                logger.debug("kuzu: duplicate edge skipped %s -[%s]-> %s", source, relation, target)
            else:
                logger.warning("kuzu: add_edge failed for %s -[%s]-> %s", source, relation, target, exc_info=True)

    # ------------------------------------------------------------------
    # Bulk write path (indexer hot loop).
    #
    # The per-edge / per-node path costs ~2.1 ms per kuzu query on this
    # machine, so full-index graph builds that issue 100k+ individual
    # queries spend minutes in Python <-> C++ round trips. These bulk
    # methods replace the hot loop with UNWIND statements: ~0.2 ms per
    # edge (~11x) and ~9k nodes/s, measured against kuzu 0.4+. Callers
    # MUST pre-dedupe edges: kuzu does NOT enforce the rel-table PK for
    # UNWIND CREATE (duplicate rows multiply instead of failing).
    # ------------------------------------------------------------------
    def bulk_ensure_nodes(self, files: list[str], symbols: list[dict[str, Any]] | None = None) -> None:
        """Insert File and Symbol nodes in bulk (MERGE = idempotent).
        Existing nodes are left untouched, so this is safe for both full
        rebuilds (empty graph after reset) and incremental runs (only the
        impacted files' nodes are missing). ``symbols`` entries need keys:
        qualified_name, file_path, kind, start_line, end_line.
        """
        chunk_size = 10000
        for i in range(0, len(files), chunk_size):
            rows = [{"path": path} for path in files[i:i + chunk_size]]
            self._safe_execute("UNWIND $rows AS r MERGE (f:File {path: r.path})", {"rows": rows})
        if not symbols:
            return
        for i in range(0, len(symbols), chunk_size):
            rows = symbols[i:i + chunk_size]
            self._safe_execute(
                """UNWIND $rows AS r
                   MERGE (s:Symbol {qualified_name: r.qualified_name})
                   ON CREATE SET
                       s.file_path = r.file_path,
                       s.kind = r.kind,
                       s.start_line = r.start_line,
                       s.end_line = r.end_line""",
                {"rows": rows},
            )
    def bulk_add_edges(self, relation: str, edges: list[tuple[str, str, str]]) -> int:
        """Insert edges for one relation with bulk UNWIND statements.
        ``edges``: (source, target, confidence) tuples, already deduplicated
                by (source, target) with first-confidence-wins semantics. Duplicates
                are NOT tolerated — kuzu multiplies them under UNWIND CREATE.
                Callers must also ensure edge endpoints are freshly created for this
                run: kuzu does not enforce the rel PK under UNWIND, so re-inserting
                an edge that already exists would duplicate it, not skip it.
                (Coordinator guarantees this: full runs reset the graph; incremental
                runs DETACH DELETE changed + impacted files' nodes before the build.)
        Missing rel tables are created (with the confidence column), which
        also fixes relations that were never pre-created in the schema
        (e.g. OWNS, HAS_COMPONENT) and used to be silently dropped by the
        per-edge path.
        Returns the number of edge rows attempted.
        """
        if not edges:
            return 0
        relation = relation.upper()
        self._ensure_rel_table_with_confidence(relation)
        if relation == "DEFINES":
            query = (
                "UNWIND $rows AS r "
                "MATCH (f:File {path: r.source}), (s:Symbol {qualified_name: r.target}) "
                "CREATE (f)-[:DEFINES {confidence: r.confidence}]->(s)"
            )
        else:
            query = (
                f"UNWIND $rows AS r "
                f"MATCH (a:Symbol {{qualified_name: r.source}}), "
                f"(b:Symbol {{qualified_name: r.target}}) "
                f"CREATE (a)-[:{relation} {{confidence: r.confidence}}]->(b)"
            )
        count = 0
        batch_size = 1000
        total_batches = (len(edges) + batch_size - 1) // batch_size
        flush_start = time.monotonic()
        for i in range(0, len(edges), batch_size):
            batch_num = i // batch_size + 1
            rows = [
                {"source": source, "target": target, "confidence": confidence}
                for source, target, confidence in edges[i:i + batch_size]
            ]
            batch_start = time.monotonic()
            self._safe_execute(query, {"rows": rows})
            batch_secs = time.monotonic() - batch_start
            count += len(rows)
            if batch_num <= 5 or batch_num % 50 == 0 or batch_num == total_batches:
                elapsed = time.monotonic() - flush_start
                logger.info(
                    "kuzu: bulk_add_edges %s batch %d/%d (%d/%d edges, %.1fs batch, %.1fs elapsed)",
                    relation, batch_num, total_batches, count, len(edges), batch_secs, elapsed,
                )
        return count
    _confidence_column_cache: dict[str, frozenset[str]] = {}
    def _relation_confidence_supported(self, relation: str) -> bool:
        """Return True if the REL TABLE for *relation* has a confidence column.
        Probed once per database path and cached. Old indexes that predate
        the confidence column return False, and reads fall back to the
        3-column query (defaulting missing tags to EXTRACTED).
        """
        cache_key = str(self.data_path) if hasattr(self, "data_path") else "default"
        cached = KuzuStore._confidence_column_cache.get(cache_key)
        if cached is None:
            supported: set[str] = set()
            for rel in ("DEFINES", *SYMBOL_RELATIONS):
                if rel not in self.available_relations():
                    continue
                if rel == "DEFINES":
                    probe = "MATCH (f:File)-[r:DEFINES]->(s:Symbol) RETURN r.confidence LIMIT 1"
                else:
                    probe = f"MATCH (s1:Symbol)-[r:{rel}]->(s2:Symbol) RETURN r.confidence LIMIT 1"
                try:
                    self._safe_execute(probe)
                    supported.add(rel)
                except RuntimeError:
                    logger.debug("kuzu: confidence column not present on %s", rel)
            cached = frozenset(supported)
            KuzuStore._confidence_column_cache[cache_key] = cached
        return relation in cached

    def _relation_queries(self, relation: str, limit: int | None = None) -> tuple[str, str]:
        limit_clause = f" LIMIT {int(limit)}" if limit is not None and int(limit) > 0 else ""

        confidence_select = ", r.confidence" if self._relation_confidence_supported(relation) else ""

        if relation == "DEFINES":
            return (

                f"MATCH (f:File)-[r:DEFINES]->(s:Symbol) WHERE f.path = $value RETURN f.path, 'DEFINES', s.qualified_name{confidence_select}{limit_clause}",
                f"MATCH (f:File)-[r:DEFINES]->(s:Symbol) WHERE s.qualified_name = $value RETURN f.path, 'DEFINES', s.qualified_name{confidence_select}{limit_clause}",

            )
        return (

            f"MATCH (s1:Symbol)-[r:{relation}]->(s2:Symbol) WHERE s1.qualified_name = $value RETURN s1.qualified_name, '{relation}', s2.qualified_name{confidence_select}{limit_clause}",
            f"MATCH (s1:Symbol)-[r:{relation}]->(s2:Symbol) WHERE s2.qualified_name = $value RETURN s1.qualified_name, '{relation}', s2.qualified_name{confidence_select}{limit_clause}",

        )
 
    def _rows_to_edges(self, rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:

        edges: list[dict[str, Any]] = []
        for row in rows:
            if len(row) < 3:
                continue
            edge: dict[str, Any] = {
                "source": str(row[0]),
                "relation": str(row[1]),
                "target": str(row[2]),
            }
            if len(row) >= 4:
                confidence = str(row[3] or "").strip().upper()
                edge["confidence"] = confidence if confidence in {"EXTRACTED", "INFERRED", "AMBIGUOUS"} else DEFAULT_EDGE_CONFIDENCE
            else:
                edge["confidence"] = DEFAULT_EDGE_CONFIDENCE
            edges.append(edge)
        return edges

    def symbols_for_file(self, file_path: str, limit: int | None = None) -> list[dict[str, Any]]:
        limit_clause = f" LIMIT {int(limit)}" if limit is not None and int(limit) > 0 else ""
        try:
            rows = _safe_get_all(
                self._safe_execute(
                    f"""
                    MATCH (s:Symbol)
                    WHERE s.file_path = $file_path
                    RETURN s.qualified_name, s.file_path, s.kind, s.start_line, s.end_line
                    ORDER BY s.start_line ASC, s.qualified_name ASC{limit_clause}
                    """,
                    {"file_path": file_path},
                )
            )
        except RuntimeError:
            logger.debug("kuzu: read query failed")
            rows = []
        return [
            {
                "qualified_name": str(row[0]),
                "file_path": str(row[1]),
                "kind": str(row[2]),
                "start_line": int(row[3] or 0),
                "end_line": int(row[4] or 0),
            }
            for row in rows
            if len(row) >= 5
        ]

    def symbol_edges_for_target_file(self, file_path: str, relation: str, limit: int | None = None) -> list[dict[str, Any]]:
        if relation not in SYMBOL_RELATIONS:
            return []
        limit_clause = f" LIMIT {int(limit)}" if limit is not None and int(limit) > 0 else ""
        try:
            rows = _safe_get_all(
                self._safe_execute(
                    f"""
                    MATCH (source:Symbol)-[:{relation}]->(target:Symbol)
                    WHERE target.file_path = $file_path
                    RETURN source.qualified_name, source.file_path, '{relation}', target.qualified_name, target.file_path
                    ORDER BY source.file_path ASC, source.qualified_name ASC{limit_clause}
                    """,
                    {"file_path": file_path},
                )
            )
        except RuntimeError:
            logger.debug("kuzu: read query failed")
            rows = []
        return [
            {
                "source": str(row[0]),
                "source_file": str(row[1]),
                "relation": str(row[2]),
                "target": str(row[3]),
                "target_file": str(row[4]),
            }
            for row in rows
            if len(row) >= 5
        ]

    def symbol_edges_for_target_symbol(self, target: str, relation: str, limit: int | None = None) -> list[dict[str, Any]]:
        if relation not in SYMBOL_RELATIONS:
            return []
        limit_clause = f" LIMIT {int(limit)}" if limit is not None and int(limit) > 0 else ""
        try:
            rows = _safe_get_all(
                self._safe_execute(
                    f"""
                    MATCH (source:Symbol)-[:{relation}]->(target:Symbol)
                    WHERE target.qualified_name = $target
                    RETURN source.qualified_name, source.file_path, '{relation}', target.qualified_name, target.file_path
                    ORDER BY source.file_path ASC, source.qualified_name ASC{limit_clause}
                    """,
                    {"target": target},
                )
            )
        except RuntimeError:
            logger.debug("kuzu: read query failed")
            rows = []
        return [
            {
                "source": str(row[0]),
                "source_file": str(row[1]),
                "relation": str(row[2]),
                "target": str(row[3]),
                "target_file": str(row[4]),
            }
            for row in rows
            if len(row) >= 5
        ]
 
    def count_edges(self) -> int:
        total = 0
        for query in (
            "MATCH (f:File)-[:DEFINES]->(s:Symbol) RETURN COUNT(*)",
            *[f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) RETURN COUNT(*)" for relation in self._existing_symbol_relations()],
        ):
            try:
                rows = _safe_get_all(self._safe_execute(query))
            except RuntimeError:
                logger.debug("kuzu: count_edges query failed")
                rows = []
            if rows:
                total += int(rows[0][0])
        return total

    def get_impacted_files(self, touched_files: list[str]) -> set[str]:
        details = self.get_impacted_file_details(touched_files)
        return set(str(path) for path in details.get("impacted_files", []))

    def get_impacted_file_details(self, touched_files: list[str]) -> dict[str, Any]:
        impacted = set(touched_files)
        if not touched_files:
            return {
                "impacted_files": [],
                "by_touched_file": {},
                "relation_totals": {},
            }
        relation_queries = {
            relation: f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) WHERE s2.file_path = $file_path RETURN DISTINCT s1.file_path"
            for relation in self._existing_symbol_relations()
        }
        by_touched_file: dict[str, dict[str, list[str]]] = {}
        relation_totals: dict[str, set[str]] = {name: set() for name in relation_queries}
        for file_path in touched_files:
            file_breakdown: dict[str, list[str]] = {}
            for relation_name, query in relation_queries.items():
                try:
                    rows = _safe_get_all(self._safe_execute(query, {"file_path": file_path}))
                except RuntimeError:
                    logger.debug("kuzu: get_impacted_file_details query failed for %s", relation_name)
                    rows = []
                related_files = sorted({str(row[0]) for row in rows if row and row[0]})
                file_breakdown[relation_name] = related_files
                impacted.update(related_files)
                relation_totals[relation_name].update(related_files)
            by_touched_file[file_path] = file_breakdown
        return {
            "impacted_files": sorted(impacted),
            "by_touched_file": by_touched_file,
            "relation_totals": {name: sorted(paths) for name, paths in relation_totals.items()},
        }

    def all_edges(self) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        for relation, query in {
            "DEFINES": "MATCH (f:File)-[:DEFINES]->(s:Symbol) RETURN f.path, s.qualified_name",
            **{relation: f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) RETURN s1.qualified_name, s2.qualified_name" for relation in self._existing_symbol_relations()},
        }.items():
            try:
                rows = self._safe_execute(query).get_all()
            except RuntimeError:
                logger.debug("kuzu: all_edges query failed for %s", relation)
                rows = []
            edges.extend(
                {"source": row[0], "relation": relation, "target": row[1]}
                for row in rows
            )
        return edges

    def graph_integrity_report(self) -> dict[str, Any]:
        try:
            file_rows = _safe_get_all(self._safe_execute("MATCH (f:File) RETURN f.path"))
        except RuntimeError:
            logger.warning("kuzu: file query failed in graph_integrity_report", exc_info=True)
            file_rows = []
        file_paths = {str(row[0]) for row in file_rows if row and row[0]}
        try:
            symbol_rows = _safe_get_all(
                self._safe_execute("MATCH (s:Symbol) RETURN s.qualified_name, s.file_path")
            )
        except RuntimeError:
            logger.warning("kuzu: symbol query failed in graph_integrity_report", exc_info=True)
            symbol_rows = []
        symbols = [
            {"qualified_name": str(row[0]), "file_path": str(row[1])}
            for row in symbol_rows
            if len(row) >= 2
        ]
        try:
            define_rows = _safe_get_all(
                self._safe_execute("MATCH (f:File)-[:DEFINES]->(s:Symbol) RETURN f.path, s.qualified_name")
            )
        except RuntimeError:
            logger.warning("kuzu: defines query failed in graph_integrity_report", exc_info=True)
            define_rows = []
        defines = {(str(row[0]), str(row[1])) for row in define_rows if len(row) >= 2}
        symbols_missing_file_node = [
            symbol
            for symbol in symbols
            if symbol["file_path"] and symbol["file_path"] not in file_paths
        ]
        symbols_missing_defines_edge = [
            symbol
            for symbol in symbols
            if symbol["file_path"]
            and not symbol["qualified_name"].startswith("property:")
            and (symbol["file_path"], symbol["qualified_name"]) not in defines
        ]
        return {
            "file_count": len(file_paths),
            "symbol_count": len(symbols),
            "edge_count": self.count_edges(),
            "symbols_missing_file_node": symbols_missing_file_node,
            "symbols_missing_defines_edge": symbols_missing_defines_edge,
            "ok": not symbols_missing_file_node and not symbols_missing_defines_edge,
        }

    def edges_for_relation(self, relation: str) -> list[dict[str, Any]]:
        relation_name = relation.upper()

        confidence_select = ", r.confidence" if self._relation_confidence_supported(relation_name) else ""
        if relation_name == "DEFINES":
            query = f"MATCH (f:File)-[r:DEFINES]->(s:Symbol) RETURN f.path, 'DEFINES', s.qualified_name{confidence_select}"
        elif relation_name in SYMBOL_RELATIONS:
            query = f"MATCH (s1:Symbol)-[r:{relation_name}]->(s2:Symbol) RETURN s1.qualified_name, '{relation_name}', s2.qualified_name{confidence_select}"
        else:

            return []
        try:
            rows = self._safe_execute(query).get_all()
        except RuntimeError:
            logger.debug("kuzu: edges_for_relation query failed for %s", relation_name)
            rows = []

        return self._rows_to_edges(rows)

    def edges_for_target(self, target: str, relation: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        if relation is not None:
            relations = [relation]
        else:
            relations = ["DEFINES", *self._existing_symbol_relations()]
        edges: list[dict[str, Any]] = []
        for relation_name in relations:
            _, target_query = self._relation_queries(relation_name, limit=limit)
            try:
                rows = _safe_get_all(self._safe_execute(target_query, {"value": target}))
            except RuntimeError:
                logger.debug("kuzu: edges_for_target query failed for %s", relation_name)
                rows = []
            edges.extend(self._rows_to_edges(rows))
        return edges
 
    def edges_for_source(self, source: str, relation: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        if relation is not None:
            relations = [relation]
        else:
            relations = ["DEFINES", *self._existing_symbol_relations()]
        edges: list[dict[str, Any]] = []
        for relation_name in relations:
            source_query, _ = self._relation_queries(relation_name, limit=limit)
            try:
                rows = _safe_get_all(self._safe_execute(source_query, {"value": source}))
            except RuntimeError:
                logger.debug("kuzu: edges_for_source query failed for %s", relation_name)
                rows = []
            edges.extend(self._rows_to_edges(rows))
        return edges
 
    def neighborhood(self, target: str, depth: int = 1) -> dict[str, Any]:
        seen = {target}
        frontier = {target}
        collected: list[dict[str, Any]] = []
        for _ in range(max(depth, 1)):
            next_frontier: set[str] = set()
            frontier_edges: list[dict[str, Any]] = []
            for node in frontier:
                frontier_edges.extend(self.edges_for_source(node))
                frontier_edges.extend(self.edges_for_target(node))
            unique_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
            for edge in frontier_edges:
                unique_edges[(edge["source"], edge["relation"], edge["target"])] = edge
            for edge in unique_edges.values():
                collected.append(edge)
                if edge["source"] not in seen:
                    seen.add(edge["source"])
                    next_frontier.add(edge["source"])
                if edge["target"] not in seen:
                    seen.add(edge["target"])
                    next_frontier.add(edge["target"])
            frontier = next_frontier
            if not frontier:
                break
        return {"target": target, "depth": depth, "nodes": sorted(seen), "edges": collected}

    def execute_query(self, query: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self._safe_execute(query, parameters or {})
        columns = _result_columns(result)
        rows = _safe_get_all(result)
        mapped_rows: list[dict[str, Any]] = []
        if columns:
            for row in rows:
                mapped_rows.append({columns[index]: row[index] for index in range(min(len(columns), len(row)))})
        return {
            "query": query,
            "parameters": parameters or {},
            "columns": columns,
            "row_count": len(rows),
            "rows": mapped_rows,
        }
