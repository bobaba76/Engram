from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import duckdb


class DuckDBStore:
    def __init__(self, database_path: Path, read_only: bool = False) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._temp_database_path: Path | None = None
        try:
            self.connection = duckdb.connect(str(self.database_path), read_only=read_only)
        except duckdb.IOException:
            if not read_only:
                raise
            temp_dir = Path(tempfile.mkdtemp(prefix="coder-duckdb-ro-"))
            temp_path = temp_dir / self.database_path.name
            shutil.copy2(self.database_path, temp_path)
            self._temp_database_path = temp_path
            self.connection = duckdb.connect(str(temp_path), read_only=True)
        if not read_only:
            self._initialize_schema()

    def _initialize_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                language TEXT,
                size_bytes BIGINT,
                sha256 TEXT,
                modified_time DOUBLE
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS symbols (
                file_path TEXT,
                qualified_name TEXT,
                name TEXT,
                kind TEXT,
                start_line INTEGER,
                end_line INTEGER,
                signature TEXT,
                metadata_json TEXT,
                PRIMARY KEY(file_path, qualified_name)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                file_path TEXT,
                symbol_name TEXT,
                qualified_name TEXT,
                chunk_kind TEXT,
                start_line INTEGER,
                end_line INTEGER,
                content TEXT
            )
            """
        )
        chunk_columns = {row[1] for row in self.connection.execute("PRAGMA table_info('chunks')").fetchall()}
        if "qualified_name" not in chunk_columns:
            self.connection.execute("ALTER TABLE chunks ADD COLUMN qualified_name TEXT DEFAULT ''")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS index_runs (
                run_id TEXT PRIMARY KEY,
                run_mode TEXT,
                status TEXT,
                file_count INTEGER,
                symbol_count INTEGER,
                chunk_count INTEGER,
                finding_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_jobs (
                job_id TEXT PRIMARY KEY,
                run_id TEXT,
                review_type TEXT,
                file_path TEXT,
                priority TEXT,
                status TEXT,
                created_at DOUBLE
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_observations (
                observation_id TEXT PRIMARY KEY,
                job_id TEXT,
                run_id TEXT,
                review_type TEXT,
                file_path TEXT,
                category TEXT,
                severity TEXT,
                title TEXT,
                description TEXT,
                confidence DOUBLE,
                suggested_fix TEXT,
                start_line INTEGER,
                end_line INTEGER,
                review_model TEXT,
                prompt_version TEXT
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS findings (
                finding_id TEXT PRIMARY KEY,
                file_path TEXT,
                review_type TEXT,
                category TEXT,
                severity TEXT,
                title TEXT,
                description TEXT,
                confidence DOUBLE,
                suggested_fix TEXT,
                start_line INTEGER,
                end_line INTEGER,
                fingerprint TEXT,
                status TEXT,
                first_seen_at DOUBLE,
                last_seen_at DOUBLE,
                occurrence_count INTEGER,
                source_review_types TEXT
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_agent_analyses (
                analysis_id TEXT PRIMARY KEY,
                job_id TEXT,
                run_id TEXT,
                file_path TEXT,
                agent_type TEXT,
                provider_name TEXT,
                model_name TEXT,
                prompt_version TEXT,
                summary TEXT,
                output_json TEXT,
                input_context_json TEXT,
                status TEXT,
                created_at DOUBLE
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS processes (
                process_id TEXT PRIMARY KEY,
                name TEXT,
                process_type TEXT,
                entry_symbol TEXT,
                terminal_symbol TEXT,
                step_count INTEGER,
                step_list_json TEXT,
                module_tags_json TEXT,
                community_tags_json TEXT,
                file_paths_json TEXT
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS process_clusters (
                cluster_id TEXT PRIMARY KEY,
                name TEXT,
                process_type TEXT,
                canonical_entry_symbol TEXT,
                canonical_terminal_symbol TEXT,
                process_count INTEGER,
                avg_step_count DOUBLE,
                module_tags_json TEXT,
                community_tags_json TEXT,
                file_paths_json TEXT,
                keywords_json TEXT
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS process_symbol_memberships (
                cluster_id TEXT,
                process_id TEXT,
                symbol TEXT,
                step_index INTEGER,
                role TEXT,
                PRIMARY KEY(cluster_id, process_id, symbol, step_index)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS process_relationships (
                source_cluster_id TEXT,
                target_cluster_id TEXT,
                relation_type TEXT,
                shared_symbol TEXT,
                PRIMARY KEY(source_cluster_id, target_cluster_id, relation_type, shared_symbol)
            )
            """
        )

    def clear_index_tables(self) -> None:
        for table in (
            "files",
            "symbols",
            "chunks",
            "process_relationships",
            "process_symbol_memberships",
            "process_clusters",
            "processes",
            "review_jobs",
            "review_observations",
            "findings",
            "review_agent_analyses",
        ):
            self.connection.execute(f"DELETE FROM {table}")

    def delete_index_data_for_files(self, file_paths: list[str]) -> None:
        if not file_paths:
            return
        placeholders = ", ".join("?" for _ in file_paths)
        self.connection.execute(f"DELETE FROM review_jobs WHERE file_path IN ({placeholders})", file_paths)
        self.connection.execute(f"DELETE FROM review_observations WHERE file_path IN ({placeholders})", file_paths)
        self.connection.execute(f"DELETE FROM review_agent_analyses WHERE file_path IN ({placeholders})", file_paths)
        self.connection.execute(f"DELETE FROM chunks WHERE file_path IN ({placeholders})", file_paths)
        self.connection.execute(f"DELETE FROM symbols WHERE file_path IN ({placeholders})", file_paths)
        self.connection.execute(f"DELETE FROM files WHERE path IN ({placeholders})", file_paths)

    def resolve_findings_for_files(self, file_paths: list[str]) -> None:
        if not file_paths:
            return
        placeholders = ", ".join("?" for _ in file_paths)
        self.connection.execute(
            f"UPDATE findings SET status = 'resolved' WHERE file_path IN ({placeholders})",
            file_paths,
        )

    def upsert_file(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO files(path, language, size_bytes, sha256, modified_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            [record["path"], record["language"], record["size_bytes"], record["sha256"], record["modified_time"]],
        )

    def insert_symbol(self, record: dict[str, Any]) -> None:
        self.connection.execute(
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

    def insert_process_cluster(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO process_clusters(
                cluster_id, name, process_type, canonical_entry_symbol, canonical_terminal_symbol,
                process_count, avg_step_count, module_tags_json, community_tags_json, file_paths_json, keywords_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["cluster_id"],
                record["name"],
                record["process_type"],
                record["canonical_entry_symbol"],
                record["canonical_terminal_symbol"],
                record["process_count"],
                record["avg_step_count"],
                json.dumps(record.get("module_tags", [])),
                json.dumps(record.get("community_tags", [])),
                json.dumps(record.get("file_paths", [])),
                json.dumps(record.get("keywords", [])),
            ],
        )

    def insert_process_symbol_membership(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO process_symbol_memberships(cluster_id, process_id, symbol, step_index, role)
            VALUES (?, ?, ?, ?, ?)
            """,
            [record["cluster_id"], record["process_id"], record["symbol"], record["step_index"], record["role"]],
        )

    def insert_process_symbol_memberships(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO process_symbol_memberships(cluster_id, process_id, symbol, step_index, role)
            VALUES (?, ?, ?, ?, ?)
            """,
            [[record["cluster_id"], record["process_id"], record["symbol"], record["step_index"], record["role"]] for record in records],
        )

    def insert_process_relationship(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO process_relationships(source_cluster_id, target_cluster_id, relation_type, shared_symbol)
            VALUES (?, ?, ?, ?)
            """,
            [record["source_cluster_id"], record["target_cluster_id"], record["relation_type"], record.get("shared_symbol", "")],
        )

    def insert_process_relationships(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO process_relationships(source_cluster_id, target_cluster_id, relation_type, shared_symbol)
            VALUES (?, ?, ?, ?)
            """,
            [[record["source_cluster_id"], record["target_cluster_id"], record["relation_type"], record.get("shared_symbol", "")] for record in records],
        )

    def insert_process(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO processes(
                process_id, name, process_type, entry_symbol, terminal_symbol,
                step_count, step_list_json, module_tags_json, community_tags_json, file_paths_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["process_id"],
                record["name"],
                record["process_type"],
                record["entry_symbol"],
                record["terminal_symbol"],
                record["step_count"],
                json.dumps(record.get("step_list", [])),
                json.dumps(record.get("module_tags", [])),
                json.dumps(record.get("community_tags", [])),
                json.dumps(record.get("file_paths", [])),
            ],
        )

    def insert_processes(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO processes(
                process_id, name, process_type, entry_symbol, terminal_symbol,
                step_count, step_list_json, module_tags_json, community_tags_json, file_paths_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                [
                    record["process_id"],
                    record["name"],
                    record["process_type"],
                    record["entry_symbol"],
                    record["terminal_symbol"],
                    record["step_count"],
                    json.dumps(record.get("step_list", [])),
                    json.dumps(record.get("module_tags", [])),
                    json.dumps(record.get("community_tags", [])),
                    json.dumps(record.get("file_paths", [])),
                ]
                for record in records
            ],
        )

    def insert_process_clusters(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        self.connection.executemany(
            """
            INSERT OR REPLACE INTO process_clusters(
                cluster_id, name, process_type, canonical_entry_symbol, canonical_terminal_symbol,
                process_count, avg_step_count, module_tags_json, community_tags_json, file_paths_json, keywords_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                [
                    record["cluster_id"],
                    record["name"],
                    record["process_type"],
                    record["canonical_entry_symbol"],
                    record["canonical_terminal_symbol"],
                    record["process_count"],
                    record["avg_step_count"],
                    json.dumps(record.get("module_tags", [])),
                    json.dumps(record.get("community_tags", [])),
                    json.dumps(record.get("file_paths", [])),
                    json.dumps(record.get("keywords", [])),
                ]
                for record in records
            ],
        )

    def insert_review_agent_analysis(self, record: dict[str, Any]) -> None:
        self.connection.execute(
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

    def insert_chunk(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO chunks(chunk_id, file_path, symbol_name, qualified_name, chunk_kind, start_line, end_line, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ],
        )

    def insert_review_job(self, record: dict[str, Any]) -> None:
        self.connection.execute(
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

    def insert_review_observation(self, record: dict[str, Any]) -> None:
        self.connection.execute(
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

    def upsert_finding(self, record: dict[str, Any]) -> None:
        self.connection.execute(
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

    def upsert_run(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO index_runs(run_id, run_mode, status, file_count, symbol_count, chunk_count, finding_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record["run_id"],
                record["run_mode"],
                record["status"],
                record["file_count"],
                record["symbol_count"],
                record["chunk_count"],
                record["finding_count"],
            ],
        )

    def fetch_findings_for_target(self, target: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM findings WHERE file_path = ? ORDER BY severity DESC, last_seen_at DESC",
            [target],
        ).fetchall()
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_agent_analyses_for_target(self, target: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM review_agent_analyses WHERE file_path = ? ORDER BY created_at DESC, agent_type ASC",
            [target],
        ).fetchall()
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_finding_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM findings WHERE fingerprint = ? LIMIT 1",
            [fingerprint],
        ).fetchone()
        if row is None:
            return None
        columns = [column[0] for column in self.connection.description]
        return dict(zip(columns, row))

    def fetch_symbols_for_file(self, file_path: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM symbols WHERE file_path = ? ORDER BY start_line ASC, qualified_name ASC",
            [file_path],
        ).fetchall()
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_process_clusters(self, limit: int = 50, query: str = "") -> list[dict[str, Any]]:
        normalized = str(query or "").strip()
        if normalized:
            pattern = f"%{normalized}%"
            rows = self.connection.execute(
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
            rows = self.connection.execute(
                "SELECT * FROM process_clusters ORDER BY process_count DESC, avg_step_count DESC, name ASC LIMIT ?",
                [limit],
            ).fetchall()
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_process_clusters_for_symbol(self, symbol_name: str, limit: int = 50) -> list[dict[str, Any]]:
        normalized = str(symbol_name or "").strip()
        if not normalized:
            return []
        rows = self.connection.execute(
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
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_process_memberships_for_cluster(self, cluster_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM process_symbol_memberships WHERE cluster_id = ? ORDER BY process_id ASC, step_index ASC LIMIT ?",
            [cluster_id, limit],
        ).fetchall()
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_process_relationships(self, cluster_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM process_relationships
            WHERE source_cluster_id = ? OR target_cluster_id = ?
            ORDER BY relation_type ASC, source_cluster_id ASC, target_cluster_id ASC
            LIMIT ?
            """,
            [cluster_id, cluster_id, limit],
        ).fetchall()
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_symbol_by_uid(self, uid: str) -> dict[str, Any] | None:
        normalized = str(uid or "").strip()
        if not normalized:
            return None
        parts = normalized.split(":", 2)
        if len(parts) != 3:
            return None
        _, file_path, qualified_name = parts
        row = self.connection.execute(
            "SELECT * FROM symbols WHERE file_path = ? AND qualified_name = ? LIMIT 1",
            [file_path, qualified_name],
        ).fetchone()
        if row is None:
            return None
        columns = [column[0] for column in self.connection.description]
        return dict(zip(columns, row))

    def fetch_symbols_for_target(self, target: str, limit: int = 50) -> list[dict[str, Any]]:
        pattern = f"%{target}%"
        rows = self.connection.execute(
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
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_chunks_for_target(self, target: str, limit: int = 5) -> list[dict[str, Any]]:
        pattern = f"%{target}%"
        rows = self.connection.execute(
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
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def fetch_files_index(self) -> dict[str, dict[str, Any]]:
        return {row["path"]: row for row in self.fetch_all("files")}

    def fetch_symbols_by_file(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        rows = self.connection.execute(
            "SELECT * FROM symbols ORDER BY file_path ASC, start_line ASC, qualified_name ASC"
        ).fetchall()
        columns = [column[0] for column in self.connection.description]
        for row in rows:
            mapped = dict(zip(columns, row))
            grouped.setdefault(mapped["file_path"], []).append(mapped)
        return grouped

    def fetch_all(self, table: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(f"SELECT * FROM {table}").fetchall()
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]
