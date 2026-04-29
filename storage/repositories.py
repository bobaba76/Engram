from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore


def _batches(records: list[Any], batch_size: int = 1000) -> list[list[Any]]:
    return [records[index:index + batch_size] for index in range(0, len(records), batch_size)]


class FileRepository:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store

    def upsert(self, record: dict[str, Any]) -> None:
        self.store.execute(
            """
            INSERT OR REPLACE INTO files(path, language, size_bytes, sha256, modified_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            [record["path"], record["language"], record["size_bytes"], record["sha256"], record["modified_time"]],
        )

    def upsert_many(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        rows = [
            [record["path"], record["language"], record["size_bytes"], record["sha256"], record["modified_time"]]
            for record in records
        ]
        for batch in _batches(rows):
            self.store.executemany(
                """
                INSERT OR REPLACE INTO files(path, language, size_bytes, sha256, modified_time)
                VALUES (?, ?, ?, ?, ?)
                """,
                batch,
            )

    def fetch_index(self) -> dict[str, dict[str, Any]]:
        return {row["path"]: row for row in self.fetch_all()}

    def delete_index_data_for_files(self, file_paths: list[str]) -> None:
        self.store.delete_index_data_for_files(file_paths)

    def fetch_all(self) -> list[dict[str, Any]]:
        rows = self.store.execute("SELECT * FROM files").fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]


class SymbolRepository:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store

    def insert(self, record: dict[str, Any]) -> None:
        self.store.execute(
            """
            INSERT OR REPLACE INTO symbols(file_path, qualified_name, name, kind, start_line, end_line, signature, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["file_path"],
                record["qualified_name"],
                record["name"],
                record["kind"],
                record["start_line"],
                record["end_line"],
                record["signature"],
                record["metadata_json"],
            ],
        )

    def insert_many(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        rows = [
            [
                record["file_path"],
                record["qualified_name"],
                record["name"],
                record["kind"],
                record["start_line"],
                record["end_line"],
                record["signature"],
                record["metadata_json"],
            ]
            for record in records
        ]
        for batch in _batches(rows):
            self.store.executemany(
                """
                INSERT OR REPLACE INTO symbols(file_path, qualified_name, name, kind, start_line, end_line, signature, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )

    def fetch_for_file(self, file_path: str) -> list[dict[str, Any]]:
        rows = self.store.execute(
            "SELECT * FROM symbols WHERE file_path = ? ORDER BY start_line ASC, qualified_name ASC",
            [file_path],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_by_file(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        rows = self.store.execute(
            "SELECT * FROM symbols ORDER BY file_path ASC, start_line ASC, qualified_name ASC"
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        for row in rows:
            mapped = dict(zip(columns, row))
            grouped.setdefault(mapped["file_path"], []).append(mapped)
        return grouped

    def fetch_for_target(self, target: str, limit: int = 50) -> list[dict[str, Any]]:
        pattern = f"%{target}%"
        rows = self.store.execute(
            """
            SELECT *
            FROM symbols
            WHERE file_path = ?
               OR name = ?
               OR qualified_name = ?
               OR lower(name) LIKE lower(?)
               OR lower(qualified_name) LIKE lower(?)
               OR lower(file_path) LIKE lower(?)
            ORDER BY CASE
                WHEN qualified_name = ? THEN 0
                WHEN name = ? THEN 1
                WHEN file_path = ? THEN 2
                WHEN lower(name) = lower(?) THEN 3
                WHEN lower(qualified_name) = lower(?) THEN 4
                ELSE 5
            END,
            start_line ASC,
            qualified_name ASC
            LIMIT ?
            """,
            [target, target, target, pattern, pattern, pattern, target, target, target, target, target, limit],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_by_uid(self, uid: str) -> dict[str, Any] | None:
        normalized = str(uid or "").strip()
        if not normalized:
            return None
        parts = normalized.split(":", 2)
        if len(parts) != 3:
            return None
        _, file_path, qualified_name = parts
        row = self.store.execute(
            "SELECT * FROM symbols WHERE file_path = ? AND qualified_name = ? LIMIT 1",
            [file_path, qualified_name],
        ).fetchone()
        if row is None:
            return None
        columns = [column[0] for column in self.store.connection.description]
        return dict(zip(columns, row))


class ChunkRepository:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store

    def insert(self, record: dict[str, Any]) -> None:
        self.store.execute(
            """
            INSERT OR REPLACE INTO chunks(
                chunk_id, file_path, symbol_name, qualified_name, chunk_kind, start_line, end_line,
                content, content_hash, source_hash, parser_name, chunking_version, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["chunk_id"],
                record["file_path"],
                record["symbol_name"],
                record.get("qualified_name", record.get("symbol_name", "")),
                record["chunk_kind"],
                record["start_line"],
                record["end_line"],
                record["content"],
                record.get("content_hash", ""),
                record.get("source_hash", ""),
                record.get("parser_name", ""),
                record.get("chunking_version", ""),
                json.dumps(record.get("metadata", record.get("metadata_json", {}))),
            ],
        )

    def insert_many(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        rows = [
            [
                record["chunk_id"],
                record["file_path"],
                record["symbol_name"],
                record.get("qualified_name", record.get("symbol_name", "")),
                record["chunk_kind"],
                record["start_line"],
                record["end_line"],
                record["content"],
                record.get("content_hash", ""),
                record.get("source_hash", ""),
                record.get("parser_name", ""),
                record.get("chunking_version", ""),
                json.dumps(record.get("metadata", record.get("metadata_json", {}))),
            ]
            for record in records
        ]
        for batch in _batches(rows):
            self.store.executemany(
                """
                INSERT OR REPLACE INTO chunks(
                    chunk_id, file_path, symbol_name, qualified_name, chunk_kind, start_line, end_line,
                    content, content_hash, source_hash, parser_name, chunking_version, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )

    def fetch_for_files(self, file_paths: list[str]) -> list[dict[str, Any]]:
        normalized = [str(path or "").strip() for path in file_paths if str(path or "").strip()]
        if not normalized:
            return []
        rows_out: list[dict[str, Any]] = []
        for batch in _batches(normalized):
            placeholders = ", ".join("?" for _ in batch)
            rows = self.store.execute(
                f"SELECT * FROM chunks WHERE file_path IN ({placeholders})",
                batch,
            ).fetchall()
            columns = [column[0] for column in self.store.connection.description]
            rows_out.extend(dict(zip(columns, row)) for row in rows)
        return rows_out

    def fetch_for_target(self, target: str, limit: int = 5) -> list[dict[str, Any]]:
        pattern = f"%{target}%"
        rows = self.store.execute(
            """
            SELECT *
            FROM chunks
            WHERE file_path = ?
               OR symbol_name = ?
               OR qualified_name = ?
               OR lower(symbol_name) LIKE lower(?)
               OR lower(qualified_name) LIKE lower(?)
               OR lower(file_path) LIKE lower(?)
               OR lower(content) LIKE lower(?)
               OR file_path IN (
                   SELECT file_path FROM symbols
                   WHERE name = ?
                      OR qualified_name = ?
                      OR lower(name) LIKE lower(?)
                      OR lower(qualified_name) LIKE lower(?)
               )
            ORDER BY CASE
                WHEN qualified_name = ? THEN 0
                WHEN symbol_name = ? THEN 1
                WHEN file_path = ? THEN 2
                WHEN lower(symbol_name) = lower(?) THEN 3
                WHEN lower(qualified_name) = lower(?) THEN 4
                ELSE 3
            END, start_line ASC
            LIMIT ?
            """,
            [
                target,
                target,
                target,
                pattern,
                pattern,
                pattern,
                pattern,
                target,
                target,
                pattern,
                pattern,
                target,
                target,
                target,
                target,
                target,
                limit,
            ],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def search_content(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        tokens = [
            token.strip().lower()
            for token in str(query or "").replace("_", " ").replace("-", " ").split()
            if len(token.strip()) >= 3
        ]
        if not tokens:
            return []
        tokens = list(dict.fromkeys(tokens))[:8]
        clauses = " OR ".join("lower(content) LIKE ?" for _ in tokens)
        params = [f"%{token}%" for token in tokens]
        rows = self.store.execute(
            f"""
            SELECT *,
                ({' + '.join('CASE WHEN lower(content) LIKE ? THEN 1 ELSE 0 END' for _ in tokens)}) AS token_hits
            FROM chunks
            WHERE {clauses}
            ORDER BY token_hits DESC, file_path ASC, start_line ASC
            LIMIT ?
            """,
            [*params, *params, max(limit, 1)],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_for_file_range(self, file_path: str, start_line: int | None, end_line: int | None, limit: int = 5) -> list[dict[str, Any]]:
        normalized_file = str(file_path or "").strip()
        if not normalized_file:
            return []
        start = int(start_line or 1)
        end = int(end_line or start)
        rows = self.store.execute(
            """
            SELECT *
            FROM chunks
            WHERE file_path = ?
              AND start_line <= ?
              AND end_line >= ?
            ORDER BY
                CASE
                    WHEN start_line <= ? AND end_line >= ? THEN 0
                    ELSE 1
                END,
                ABS(start_line - ?),
                start_line ASC
            LIMIT ?
            """,
            [normalized_file, end, start, start, end, start, limit],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_all(self) -> list[dict[str, Any]]:
        rows = self.store.execute("SELECT * FROM chunks").fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def count(self) -> int:
        row = self.store.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0]) if row is not None else 0


class ReviewRepository:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store

    def insert_job(self, record: dict[str, Any]) -> None:
        self.store.execute(
            """
            INSERT OR REPLACE INTO review_jobs(job_id, run_id, review_type, file_path, priority, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["job_id"],
                record["run_id"],
                record["review_type"],
                record["file_path"],
                record["priority"],
                record["status"],
                record["created_at"],
            ],
        )

    def insert_observation(self, record: dict[str, Any]) -> None:
        self.store.execute(
            """
            INSERT OR REPLACE INTO review_observations(
                observation_id, job_id, run_id, review_type, file_path, category, severity, title,
                description, confidence, suggested_fix, start_line, end_line, review_model, prompt_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["observation_id"],
                record["job_id"],
                record["run_id"],
                record["review_type"],
                record["file_path"],
                record["category"],
                record["severity"],
                record["title"],
                record["description"],
                record["confidence"],
                record["suggested_fix"],
                record["start_line"],
                record["end_line"],
                record["review_model"],
                record["prompt_version"],
            ],
        )

    def insert_agent_analysis(self, record: dict[str, Any]) -> None:
        self.store.execute(
            """
            INSERT OR REPLACE INTO review_agent_analyses(
                analysis_id, job_id, run_id, file_path, agent_type, provider_name, model_name,
                prompt_version, summary, output_json, input_context_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["analysis_id"],
                record["job_id"],
                record["run_id"],
                record["file_path"],
                record["agent_type"],
                record["provider_name"],
                record["model_name"],
                record["prompt_version"],
                record["summary"],
                record["output_json"],
                record["input_context_json"],
                record["status"],
                record["created_at"],
            ],
        )

    def upsert_finding(self, record: dict[str, Any]) -> None:
        self.store.execute(
            """
            INSERT OR REPLACE INTO findings(
                finding_id, file_path, review_type, category, severity, title, description, confidence,
                suggested_fix, start_line, end_line, fingerprint, status, first_seen_at, last_seen_at,
                occurrence_count, source_review_types
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["finding_id"],
                record["file_path"],
                record["review_type"],
                record["category"],
                record["severity"],
                record["title"],
                record["description"],
                record["confidence"],
                record["suggested_fix"],
                record["start_line"],
                record["end_line"],
                record["fingerprint"],
                record["status"],
                record["first_seen_at"],
                record["last_seen_at"],
                record["occurrence_count"],
                record["source_review_types"],
            ],
        )

    def resolve_findings_for_files(self, file_paths: list[str]) -> None:
        if not file_paths:
            return
        placeholders = ", ".join("?" for _ in file_paths)
        self.store.execute(
            f"UPDATE findings SET status = 'resolved' WHERE file_path IN ({placeholders})",
            file_paths,
        )

    def fetch_finding_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        row = self.store.execute(
            "SELECT * FROM findings WHERE fingerprint = ? LIMIT 1",
            [fingerprint],
        ).fetchone()
        if row is None:
            return None
        columns = [column[0] for column in self.store.connection.description]
        return dict(zip(columns, row))

    def fetch_findings_for_target(self, target: str) -> list[dict[str, Any]]:
        rows = self.store.execute(
            "SELECT * FROM findings WHERE file_path = ? ORDER BY severity DESC, last_seen_at DESC",
            [target],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_agent_analyses_for_target(self, target: str) -> list[dict[str, Any]]:
        rows = self.store.execute(
            "SELECT * FROM review_agent_analyses WHERE file_path = ? ORDER BY created_at DESC, agent_type ASC",
            [target],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]


class ProcessRepository:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store

    def delete_for_files(self, file_paths: list[str]) -> None:
        normalized = [str(path or "").strip() for path in file_paths if str(path or "").strip()]
        if not normalized:
            return
        process_ids: set[str] = set()
        cluster_ids: set[str] = set()
        for file_path in normalized:
            pattern = f'%"{file_path}"%'
            process_rows = self.store.execute(
                "SELECT process_id FROM processes WHERE file_paths_json LIKE ?",
                [pattern],
            ).fetchall()
            cluster_rows = self.store.execute(
                "SELECT cluster_id FROM process_clusters WHERE file_paths_json LIKE ?",
                [pattern],
            ).fetchall()
            process_ids.update(str(row[0]) for row in process_rows if row and row[0])
            cluster_ids.update(str(row[0]) for row in cluster_rows if row and row[0])
        if process_ids:
            process_placeholders = ", ".join("?" for _ in process_ids)
            process_params = list(process_ids)
            membership_cluster_rows = self.store.execute(
                f"SELECT DISTINCT cluster_id FROM process_symbol_memberships WHERE process_id IN ({process_placeholders})",
                process_params,
            ).fetchall()
            cluster_ids.update(str(row[0]) for row in membership_cluster_rows if row and row[0])
            self.store.execute(
                f"DELETE FROM process_symbol_memberships WHERE process_id IN ({process_placeholders})",
                process_params,
            )
            self.store.execute(
                f"DELETE FROM processes WHERE process_id IN ({process_placeholders})",
                process_params,
            )
        if cluster_ids:
            cluster_placeholders = ", ".join("?" for _ in cluster_ids)
            cluster_params = list(cluster_ids)
            self.store.execute(
                f"DELETE FROM process_relationships WHERE source_cluster_id IN ({cluster_placeholders}) OR target_cluster_id IN ({cluster_placeholders})",
                [*cluster_params, *cluster_params],
            )
            self.store.execute(
                f"DELETE FROM process_symbol_memberships WHERE cluster_id IN ({cluster_placeholders})",
                cluster_params,
            )
            self.store.execute(
                f"DELETE FROM process_clusters WHERE cluster_id IN ({cluster_placeholders})",
                cluster_params,
            )

    def insert_processes(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        rows = [
                [
                    record["process_id"],
                    record["name"],
                    record["process_type"],
                    record["entry_symbol"],
                    record["terminal_symbol"],
                    record["step_count"],
                    record.get("step_list_json", json.dumps(record.get("step_list", []))),
                    record.get("module_tags_json", json.dumps(record.get("module_tags", []))),
                    record.get("community_tags_json", json.dumps(record.get("community_tags", []))),
                    record.get("file_paths_json", json.dumps(record.get("file_paths", []))),
                ]
                for record in records
            ]
        for batch in _batches(rows):
            self.store.executemany(
                """
                INSERT OR REPLACE INTO processes(
                    process_id, name, process_type, entry_symbol, terminal_symbol,
                    step_count, step_list_json, module_tags_json, community_tags_json, file_paths_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )

    def insert_clusters(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        rows = [
                [
                    record["cluster_id"],
                    record["name"],
                    record["process_type"],
                    record["canonical_entry_symbol"],
                    record["canonical_terminal_symbol"],
                    record["process_count"],
                    record["avg_step_count"],
                    record.get("module_tags_json", json.dumps(record.get("module_tags", []))),
                    record.get("community_tags_json", json.dumps(record.get("community_tags", []))),
                    record.get("file_paths_json", json.dumps(record.get("file_paths", []))),
                    record.get("keywords_json", json.dumps(record.get("keywords", []))),
                ]
                for record in records
            ]
        for batch in _batches(rows):
            self.store.executemany(
                """
                INSERT OR REPLACE INTO process_clusters(
                    cluster_id, name, process_type, canonical_entry_symbol, canonical_terminal_symbol,
                    process_count, avg_step_count, module_tags_json, community_tags_json, file_paths_json, keywords_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )

    def insert_symbol_memberships(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        rows = [[record["cluster_id"], record["process_id"], record["symbol"], record["step_index"], record["role"]] for record in records]
        for batch in _batches(rows):
            self.store.executemany(
                """
                INSERT OR REPLACE INTO process_symbol_memberships(cluster_id, process_id, symbol, step_index, role)
                VALUES (?, ?, ?, ?, ?)
                """,
                batch,
            )

    def insert_relationships(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        rows = [[record["source_cluster_id"], record["target_cluster_id"], record["relation_type"], record.get("shared_symbol", "")] for record in records]
        for batch in _batches(rows):
            self.store.executemany(
                """
                INSERT OR REPLACE INTO process_relationships(source_cluster_id, target_cluster_id, relation_type, shared_symbol)
                VALUES (?, ?, ?, ?)
                """,
                batch,
            )

    def fetch_clusters(self, limit: int = 50, query: str = "") -> list[dict[str, Any]]:
        normalized = str(query or "").strip()
        if normalized:
            pattern = f"%{normalized}%"
            rows = self.store.execute(
                """
                SELECT * FROM process_clusters
                WHERE lower(name) LIKE lower(?)
                   OR lower(canonical_entry_symbol) LIKE lower(?)
                   OR lower(canonical_terminal_symbol) LIKE lower(?)
                   OR lower(file_paths_json) LIKE lower(?)
                   OR lower(module_tags_json) LIKE lower(?)
                ORDER BY process_count DESC, avg_step_count DESC, name ASC
                LIMIT ?
                """,
                [pattern, pattern, pattern, pattern, pattern, limit],
            ).fetchall()
        else:
            rows = self.store.execute(
                "SELECT * FROM process_clusters ORDER BY process_count DESC, avg_step_count DESC, name ASC LIMIT ?",
                [limit],
            ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_clusters_for_symbol(self, symbol_name: str, limit: int = 50) -> list[dict[str, Any]]:
        normalized = str(symbol_name or "").strip()
        if not normalized:
            return []
        rows = self.store.execute(
            """
            SELECT DISTINCT c.*
            FROM process_clusters c
            JOIN process_symbol_memberships m ON c.cluster_id = m.cluster_id
            WHERE m.symbol = ?
               OR c.canonical_entry_symbol = ?
               OR c.canonical_terminal_symbol = ?
            ORDER BY c.process_count DESC, c.avg_step_count DESC, c.name ASC
            LIMIT ?
            """,
            [normalized, normalized, normalized, limit],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_memberships_for_cluster(self, cluster_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.store.execute(
            "SELECT * FROM process_symbol_memberships WHERE cluster_id = ? ORDER BY process_id ASC, step_index ASC LIMIT ?",
            [cluster_id, limit],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_relationships(self, cluster_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.store.execute(
            """
            SELECT * FROM process_relationships
            WHERE source_cluster_id = ? OR target_cluster_id = ?
            ORDER BY relation_type ASC, source_cluster_id ASC, target_cluster_id ASC
            LIMIT ?
            """,
            [cluster_id, cluster_id, limit],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]


class RunRepository:
    def __init__(self, store: DuckDBStore) -> None:
        self.store = store

    def upsert(self, record: dict[str, Any]) -> None:
        self.store.execute(
            """
            INSERT OR REPLACE INTO index_runs(
                run_id, run_mode, status, file_count, symbol_count, chunk_count, finding_count,
                stage_results_json, warnings_json, errors_json, report_paths_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["run_id"],
                record["run_mode"],
                record["status"],
                record["file_count"],
                record["symbol_count"],
                record["chunk_count"],
                record["finding_count"],
                record.get("stage_results_json", "[]"),
                record.get("warnings_json", "[]"),
                record.get("errors_json", "[]"),
                record.get("report_paths_json", "{}"),
            ],
        )

    def fetch_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.store.execute(
            "SELECT * FROM index_runs ORDER BY created_at DESC, run_id DESC LIMIT ?",
            [max(limit, 1)],
        ).fetchall()
        columns = [column[0] for column in self.store.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_by_run_id(self, run_id: str) -> dict[str, Any] | None:
        row = self.store.execute(
            "SELECT * FROM index_runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        if row is None:
            return None
        columns = [column[0] for column in self.store.connection.description]
        return dict(zip(columns, row))
