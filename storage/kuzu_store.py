from __future__ import annotations
 
from pathlib import Path
from typing import Any
 
import kuzu
 
 
def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")
 
 
def _is_already_exists_error(exc: RuntimeError) -> bool:
    message = str(exc).lower()
    return "already exists" in message or "catalog exception" in message
 
 
def _safe_get_all(result) -> list[tuple[Any, ...]]:
    try:
        return result.get_all()
    except RuntimeError:
        return []


SYMBOL_RELATIONS = (
    "IMPORTS",
    "CALLS",
    "REFERENCES",
    "DECLARES",
    "ASSOCIATED_WITH",
    "ACCESSES",
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
        return []


class KuzuStore:
    def __init__(self, data_path: Path, read_only: bool = False) -> None:
        self.data_path = data_path
        self.read_only = read_only
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self.database = kuzu.Database(str(self.data_path), read_only=read_only)
        self.connection = kuzu.Connection(self.database)
        if not self.read_only:
            self._initialize_schema()

    def close(self) -> None:
        self.connection = None
        self.database = None
 
    def _initialize_schema(self) -> None:
        try:
            self.connection.execute("CREATE NODE TABLE File(path STRING, PRIMARY KEY(path))")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self.connection.execute(
                "CREATE NODE TABLE Symbol(qualified_name STRING, file_path STRING, kind STRING, start_line INT64, end_line INT64, PRIMARY KEY(qualified_name))"
            )
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self.connection.execute("CREATE REL TABLE DEFINES(FROM File TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self.connection.execute("CREATE REL TABLE IMPORTS(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self.connection.execute("CREATE REL TABLE CALLS(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self.connection.execute("CREATE REL TABLE REFERENCES(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self.connection.execute("CREATE REL TABLE DECLARES(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self.connection.execute("CREATE REL TABLE ASSOCIATED_WITH(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        try:
            self.connection.execute("CREATE REL TABLE ACCESSES(FROM Symbol TO Symbol)")
        except RuntimeError as exc:
            if not _is_already_exists_error(exc):
                raise
        for relation in ("FETCHES", "READS_FIELD", "EXTENDS", "IMPLEMENTS", "METHOD_OVERRIDES", "METHOD_IMPLEMENTS"):
            try:
                self.connection.execute(f"CREATE REL TABLE {relation}(FROM Symbol TO Symbol)")
            except RuntimeError as exc:
                if not _is_already_exists_error(exc):
                    raise
 
    def reset(self) -> None:
        for query in (
            "MATCH (f:File) DETACH DELETE f",
            "MATCH (s:Symbol) DETACH DELETE s",
        ):
            try:
                self.connection.execute(query)
            except RuntimeError:
                pass
 
    def delete_index_data_for_files(self, file_paths: list[str]) -> None:
        if not file_paths:
            return
        for file_path in file_paths:
            try:
                self.connection.execute(
                    "MATCH (f:File {path: $file_path}) DETACH DELETE f",
                    {"file_path": file_path},
                )
            except RuntimeError:
                pass
            try:
                self.connection.execute(
                    "MATCH (s:Symbol {file_path: $file_path}) DETACH DELETE s",
                    {"file_path": file_path},
                )
            except RuntimeError:
                pass
 
    def ensure_file(self, path: str) -> None:
        result = self.connection.execute(
            "MATCH (f:File {path: $path}) RETURN f.path LIMIT 1",
            {"path": path},
        )
        if result.get_num_tuples() == 0:
            self.connection.execute("CREATE (f:File {path: $path})", {"path": path})
 
    def ensure_symbol(self, qualified_name: str, file_path: str, kind: str, start_line: int, end_line: int) -> None:
        result = self.connection.execute(
            "MATCH (s:Symbol {qualified_name: $qualified_name}) RETURN s.qualified_name LIMIT 1",
            {"qualified_name": qualified_name},
        )
        if result.get_num_tuples() == 0:
            self.connection.execute(
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
            self.connection.execute(query, {"source": source, "target": target})
        except RuntimeError:
            pass
 
    def _relation_queries(self, relation: str) -> tuple[str, str]:
        if relation == "DEFINES":
            return (
                "MATCH (f:File)-[:DEFINES]->(s:Symbol) WHERE f.path = $value RETURN f.path, 'DEFINES', s.qualified_name",
                "MATCH (f:File)-[:DEFINES]->(s:Symbol) WHERE s.qualified_name = $value RETURN f.path, 'DEFINES', s.qualified_name",
            )
        return (
            f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) WHERE s1.qualified_name = $value RETURN s1.qualified_name, '{relation}', s2.qualified_name",
            f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) WHERE s2.qualified_name = $value RETURN s1.qualified_name, '{relation}', s2.qualified_name",
        )
 
    def _rows_to_edges(self, rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
        return [
            {"source": str(row[0]), "relation": str(row[1]), "target": str(row[2])}
            for row in rows
            if len(row) >= 3
        ]
 
    def count_edges(self) -> int:
        total = 0
        for query in (
            "MATCH (f:File)-[:DEFINES]->(s:Symbol) RETURN COUNT(*)",
            *[f"MATCH (s1:Symbol)-[:{relation}]->(s2:Symbol) RETURN COUNT(*)" for relation in SYMBOL_RELATIONS],
        ):
            try:
                rows = _safe_get_all(self.connection.execute(query))
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
                    rows = _safe_get_all(self.connection.execute(query, {"file_path": file_path}))
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
                rows = self.connection.execute(query).get_all()
            except RuntimeError:
                rows = []
            edges.extend(
                {"source": row[0], "relation": relation, "target": row[1]}
                for row in rows
            )
        return edges

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
            rows = self.connection.execute(query).get_all()
        except RuntimeError:
            rows = []
        return [
            {"source": row[0], "relation": relation_name, "target": row[1]}
            for row in rows
        ]
 
    def edges_for_target(self, target: str, relation: str | None = None) -> list[dict[str, Any]]:
        relations = [relation] if relation is not None else ["DEFINES", *SYMBOL_RELATIONS]
        edges: list[dict[str, Any]] = []
        for relation_name in relations:
            _, target_query = self._relation_queries(relation_name)
            try:
                rows = _safe_get_all(self.connection.execute(target_query, {"value": target}))
            except RuntimeError:
                rows = []
            edges.extend(self._rows_to_edges(rows))
        return edges
 
    def edges_for_source(self, source: str, relation: str | None = None) -> list[dict[str, Any]]:
        relations = [relation] if relation is not None else ["DEFINES", *SYMBOL_RELATIONS]
        edges: list[dict[str, Any]] = []
        for relation_name in relations:
            source_query, _ = self._relation_queries(relation_name)
            try:
                rows = _safe_get_all(self.connection.execute(source_query, {"value": source}))
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
        result = self.connection.execute(query, parameters or {})
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
