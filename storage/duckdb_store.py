from __future__ import annotations

import shutil
import tempfile
from time import time
from pathlib import Path
from typing import Any

import duckdb

from storage.connection_manager import DuckDBConnectionManager
from storage.repositories import ChunkRepository, FileRepository, ProcessRepository, ReviewRepository, RunRepository, SymbolRepository


class DuckDBStore:
    def __init__(self, database_path: Path, read_only: bool = False) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._temp_database_path: Path | None = None
        self.read_only_snapshot_metadata: dict[str, Any] = {}
        try:
            self.connection_manager = DuckDBConnectionManager(self.database_path, read_only=read_only)
        except duckdb.IOException:
            if not read_only:
                raise
            copied_at = time()
            source_mtime = self.database_path.stat().st_mtime if self.database_path.exists() else 0.0
            temp_dir = Path(tempfile.mkdtemp(prefix="coder-duckdb-ro-"))
            temp_path = temp_dir / self.database_path.name
            shutil.copy2(self.database_path, temp_path)
            self._temp_database_path = temp_path
            self.connection_manager = DuckDBConnectionManager(temp_path, read_only=True)
            self.read_only_snapshot_metadata = {
                "active": True,
                "reason": "primary DuckDB file was locked; using read-only copied snapshot",
                "source_database_path": str(self.database_path),
                "snapshot_database_path": str(temp_path),
                "copied_at": copied_at,
                "source_mtime": source_mtime,
                "stale_read_risk": True,
            }
        if not read_only:
            self._initialize_schema()
        self.files = FileRepository(self)
        self.symbols = SymbolRepository(self)
        self.chunks = ChunkRepository(self)
        self.reviews = ReviewRepository(self)
        self.processes = ProcessRepository(self)
        self.runs = RunRepository(self)

    @property
    def connection(self):
        return self.connection_manager.connection

    def close(self) -> None:
        self.connection_manager.close()

    def execute(self, query: str, parameters: list[Any] | tuple[Any, ...] | None = None):
        return self.connection_manager.execute(query, parameters)

    def executemany(self, query: str, parameters: list[list[Any]] | list[tuple[Any, ...]]):
        return self.connection_manager.executemany(query, parameters)

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
                content TEXT,
                content_hash TEXT,
                source_hash TEXT,
                parser_name TEXT,
                chunking_version TEXT,
                metadata_json TEXT
            )
            """
        )
        chunk_columns = {row[1] for row in self.connection.execute("PRAGMA table_info('chunks')").fetchall()}
        if "qualified_name" not in chunk_columns:
            self.connection.execute("ALTER TABLE chunks ADD COLUMN qualified_name TEXT DEFAULT ''")
        if "content_hash" not in chunk_columns:
            self.connection.execute("ALTER TABLE chunks ADD COLUMN content_hash TEXT DEFAULT ''")
        if "source_hash" not in chunk_columns:
            self.connection.execute("ALTER TABLE chunks ADD COLUMN source_hash TEXT DEFAULT ''")
        if "parser_name" not in chunk_columns:
            self.connection.execute("ALTER TABLE chunks ADD COLUMN parser_name TEXT DEFAULT ''")
        if "chunking_version" not in chunk_columns:
            self.connection.execute("ALTER TABLE chunks ADD COLUMN chunking_version TEXT DEFAULT ''")
        if "metadata_json" not in chunk_columns:
            self.connection.execute("ALTER TABLE chunks ADD COLUMN metadata_json TEXT DEFAULT '{}'")
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
                stage_results_json TEXT,
                warnings_json TEXT,
                errors_json TEXT,
                report_paths_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        run_columns = {row[1] for row in self.connection.execute("PRAGMA table_info('index_runs')").fetchall()}
        if "stage_results_json" not in run_columns:
            self.connection.execute("ALTER TABLE index_runs ADD COLUMN stage_results_json TEXT DEFAULT '[]'")
        if "warnings_json" not in run_columns:
            self.connection.execute("ALTER TABLE index_runs ADD COLUMN warnings_json TEXT DEFAULT '[]'")
        if "errors_json" not in run_columns:
            self.connection.execute("ALTER TABLE index_runs ADD COLUMN errors_json TEXT DEFAULT '[]'")
        if "report_paths_json" not in run_columns:
            self.connection.execute("ALTER TABLE index_runs ADD COLUMN report_paths_json TEXT DEFAULT '{}'")
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
        self.reviews.resolve_findings_for_files(file_paths)

    def upsert_file(self, record: dict[str, Any]) -> None:
        self.files.upsert(record)

    def upsert_files(self, records: list[dict[str, Any]]) -> None:
        self.files.upsert_many(records)

    def insert_symbol(self, record: dict[str, Any]) -> None:
        self.symbols.insert(record)

    def insert_symbols(self, records: list[dict[str, Any]]) -> None:
        self.symbols.insert_many(records)

    def insert_process_cluster(self, record: dict[str, Any]) -> None:
        self.processes.insert_clusters([record])

    def insert_process_symbol_membership(self, record: dict[str, Any]) -> None:
        self.processes.insert_symbol_memberships([record])

    def insert_process_symbol_memberships(self, records: list[dict[str, Any]]) -> None:
        self.processes.insert_symbol_memberships(records)

    def insert_process_relationship(self, record: dict[str, Any]) -> None:
        self.processes.insert_relationships([record])

    def insert_process_relationships(self, records: list[dict[str, Any]]) -> None:
        self.processes.insert_relationships(records)

    def insert_process(self, record: dict[str, Any]) -> None:
        self.processes.insert_processes([record])

    def insert_processes(self, records: list[dict[str, Any]]) -> None:
        self.processes.insert_processes(records)

    def insert_process_clusters(self, records: list[dict[str, Any]]) -> None:
        self.processes.insert_clusters(records)

    def insert_review_agent_analysis(self, record: dict[str, Any]) -> None:
        self.reviews.insert_agent_analysis(record)

    def insert_chunk(self, record: dict[str, Any]) -> None:
        self.chunks.insert(record)

    def insert_chunks(self, records: list[dict[str, Any]]) -> None:
        self.chunks.insert_many(records)

    def insert_review_job(self, record: dict[str, Any]) -> None:
        self.reviews.insert_job(record)

    def insert_review_observation(self, record: dict[str, Any]) -> None:
        self.reviews.insert_observation(record)

    def upsert_finding(self, record: dict[str, Any]) -> None:
        self.reviews.upsert_finding(record)

    def upsert_run(self, record: dict[str, Any]) -> None:
        self.runs.upsert(record)

    def fetch_findings_for_target(self, target: str) -> list[dict[str, Any]]:
        return self.reviews.fetch_findings_for_target(target)

    def fetch_agent_analyses_for_target(self, target: str) -> list[dict[str, Any]]:
        return self.reviews.fetch_agent_analyses_for_target(target)

    def fetch_finding_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return self.reviews.fetch_finding_by_fingerprint(fingerprint)

    def fetch_symbols_for_file(self, file_path: str) -> list[dict[str, Any]]:
        return self.symbols.fetch_for_file(file_path)

    def fetch_process_clusters(self, limit: int = 50, query: str = "") -> list[dict[str, Any]]:
        return self.processes.fetch_clusters(limit=limit, query=query)

    def fetch_process_clusters_for_symbol(self, symbol_name: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.processes.fetch_clusters_for_symbol(symbol_name, limit=limit)

    def fetch_process_memberships_for_cluster(self, cluster_id: str, limit: int = 200) -> list[dict[str, Any]]:
        return self.processes.fetch_memberships_for_cluster(cluster_id, limit=limit)

    def fetch_process_relationships(self, cluster_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.processes.fetch_relationships(cluster_id, limit=limit)

    def fetch_symbol_by_uid(self, uid: str) -> dict[str, Any] | None:
        return self.symbols.fetch_by_uid(uid)

    def fetch_symbols_for_target(self, target: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.symbols.fetch_for_target(target, limit=limit)

    def fetch_chunks_for_target(self, target: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.chunks.fetch_for_target(target, limit=limit)

    def search_chunks_content(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.chunks.search_content(query, limit=limit)

    def fetch_chunks_for_files(self, file_paths: list[str]) -> list[dict[str, Any]]:
        return self.chunks.fetch_for_files(file_paths)

    def fetch_chunks_for_file_range(self, file_path: str, start_line: int | None, end_line: int | None, limit: int = 5) -> list[dict[str, Any]]:
        return self.chunks.fetch_for_file_range(file_path, start_line=start_line, end_line=end_line, limit=limit)

    def fetch_files_index(self) -> dict[str, dict[str, Any]]:
        return self.files.fetch_index()

    def fetch_symbols_by_file(self) -> dict[str, list[dict[str, Any]]]:
        return self.symbols.fetch_by_file()

    def fetch_all(self, table: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(f"SELECT * FROM {table}").fetchall()
        columns = [column[0] for column in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]
