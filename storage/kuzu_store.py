from __future__ import annotations

import logging
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
        try:
            self._safe_execute("CREATE REL TABLE DEFINES(FROM File TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self._safe_execute("CREATE REL TABLE IMPORTS(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self._safe_execute("CREATE REL TABLE CALLS(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self._safe_execute("CREATE REL TABLE REFERENCES(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self._safe_execute("CREATE REL TABLE DECLARES(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self._safe_execute("CREATE REL TABLE ASSOCIATED_WITH(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self._safe_execute("CREATE REL TABLE ACCESSES(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        for relation in ("INCLUDES", "DECLARES_IN_HEADER", "DEFINES_IMPLEMENTATION", "INJECTS", "USES_SERVICE", "FETCHES", "READS_FIELD", "HAS_METHOD", "HAS_PROPERTY", "EXTENDS", "IMPLEMENTS", "METHOD_OVERRIDES", "METHOD_IMPLEMENTS"):
            try:
                self._safe_execute(f"CREATE REL TABLE {relation}(FROM Symbol TO Symbol)")
            except RuntimeError as exc:
                if not _is_already_exists_error(exc):
                    raise
 
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
 
    def add_edge(self, source: str, relation: str, target: str) -> None:
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

    def _relation_queries(self, relation: str, limit: int | None = None) -> tuple[str, str]:
        limit_clause = f" LIMIT {int(limit)}" if limit is not None and int(limit) > 0 else ""
        if relation == "DEFINES":
            return (
                f"MATCH (f:File)-[:DEFINES]->(s:Symbol) WHERE f.path = $value RETURN f.path, 'DEFINES', s.qualified_name{limit_clause}",
                f"MATCH (f:File)-[:DEFINES]->(s:Symbol) WHERE s.qualified_name = $value RETURN f.path, 'DEFINES', s.qualified_name{limit_clause}",
            )
        return (
            f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) WHERE s1.qualified_name = $value RETURN s1.qualified_name, '{relation}', s2.qualified_name{limit_clause}",
            f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) WHERE s2.qualified_name = $value RETURN s1.qualified_name, '{relation}', s2.qualified_name{limit_clause}",
        )
 
    def _rows_to_edges(self, rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
        return [
            {"source": str(row[0]), "relation": str(row[1]), "target": str(row[2])}
            for row in rows
            if len(row) >= 3
        ]

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
            *[f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) RETURN COUNT(*)" for relation in SYMBOL_RELATIONS],
        ):
            try:
                rows = _safe_get_all(self._safe_execute(query))
            except RuntimeError:
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
            for relation in SYMBOL_RELATIONS
        }
        by_touched_file: dict[str, dict[str, list[str]]] = {}
        relation_totals: dict[str, set[str]] = {name: set() for name in relation_queries}
        for file_path in touched_files:
            file_breakdown: dict[str, list[str]] = {}
            for relation_name, query in relation_queries.items():
                try:
                    rows = _safe_get_all(self._safe_execute(query, {"file_path": file_path}))
                except RuntimeError:
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
            **{relation: f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) RETURN s1.qualified_name, s2.qualified_name" for relation in SYMBOL_RELATIONS},
        }.items():
            try:
                rows = self._safe_execute(query).get_all()
            except RuntimeError:
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
            file_rows = []
        file_paths = {str(row[0]) for row in file_rows if row and row[0]}
        try:
            symbol_rows = _safe_get_all(
                self._safe_execute("MATCH (s:Symbol) RETURN s.qualified_name, s.file_path")
            )
        except RuntimeError:
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
        queries = {
            "DEFINES": "MATCH (f:File)-[:DEFINES]->(s:Symbol) RETURN f.path, s.qualified_name",
            **{relation: f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) RETURN s1.qualified_name, s2.qualified_name" for relation in SYMBOL_RELATIONS},
        }
        relation_name = relation.upper()
        query = queries.get(relation_name)
        if query is None:
            return []
        try:
            rows = self._safe_execute(query).get_all()
        except RuntimeError:
            rows = []
        return [
            {"source": row[0], "relation": relation_name, "target": row[1]}
            for row in rows
        ]
 
    def edges_for_target(self, target: str, relation: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        relations = [relation] if relation is not None else ["DEFINES", *SYMBOL_RELATIONS]
        edges: list[dict[str, Any]] = []
        for relation_name in relations:
            _, target_query = self._relation_queries(relation_name, limit=limit)
            try:
                rows = _safe_get_all(self._safe_execute(target_query, {"value": target}))
            except RuntimeError:
                rows = []
            edges.extend(self._rows_to_edges(rows))
        return edges
 
    def edges_for_source(self, source: str, relation: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        relations = [relation] if relation is not None else ["DEFINES", *SYMBOL_RELATIONS]
        edges: list[dict[str, Any]] = []
        for relation_name in relations:
            source_query, _ = self._relation_queries(relation_name, limit=limit)
            try:
                rows = _safe_get_all(self._safe_execute(source_query, {"value": source}))
            except RuntimeError:
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
