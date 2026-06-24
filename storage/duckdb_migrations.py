"""Versioned DuckDB schema migrations.

Each migration is a function that executes DDL statements. The runner tracks
applied migrations in a `_schema_migrations` table and only executes pending
ones, ensuring forward-only evolution of the schema.
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION_LATEST = 3


def _migration_v1(conn: Any) -> None:
    """Base schema — all tables with their original column sets."""
    conn.execute(
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
    conn.execute(
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            file_path TEXT,
            symbol_name TEXT,
            chunk_kind TEXT,
            start_line INTEGER,
            end_line INTEGER,
            content TEXT
        )
        """
    )
    conn.execute(
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
    conn.execute(
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
    conn.execute(
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
    conn.execute(
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
    conn.execute(
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
    conn.execute(
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
    conn.execute(
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
    conn.execute(
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
    conn.execute(
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


def _migration_v2(conn: Any) -> None:
    """Add columns that were originally added via inline ALTER TABLE checks."""
    chunk_columns = {row[1] for row in conn.execute("PRAGMA table_info('chunks')").fetchall()}
    if "qualified_name" not in chunk_columns:
        conn.execute("ALTER TABLE chunks ADD COLUMN qualified_name TEXT DEFAULT ''")
    if "content_hash" not in chunk_columns:
        conn.execute("ALTER TABLE chunks ADD COLUMN content_hash TEXT DEFAULT ''")
    if "source_hash" not in chunk_columns:
        conn.execute("ALTER TABLE chunks ADD COLUMN source_hash TEXT DEFAULT ''")
    if "parser_name" not in chunk_columns:
        conn.execute("ALTER TABLE chunks ADD COLUMN parser_name TEXT DEFAULT ''")
    if "chunking_version" not in chunk_columns:
        conn.execute("ALTER TABLE chunks ADD COLUMN chunking_version TEXT DEFAULT ''")
    if "metadata_json" not in chunk_columns:
        conn.execute("ALTER TABLE chunks ADD COLUMN metadata_json TEXT DEFAULT '{}'")

    run_columns = {row[1] for row in conn.execute("PRAGMA table_info('index_runs')").fetchall()}
    if "stage_results_json" not in run_columns:
        conn.execute("ALTER TABLE index_runs ADD COLUMN stage_results_json TEXT DEFAULT '[]'")
    if "warnings_json" not in run_columns:
        conn.execute("ALTER TABLE index_runs ADD COLUMN warnings_json TEXT DEFAULT '[]'")
    if "errors_json" not in run_columns:
        conn.execute("ALTER TABLE index_runs ADD COLUMN errors_json TEXT DEFAULT '[]'")
    if "report_paths_json" not in run_columns:
        conn.execute("ALTER TABLE index_runs ADD COLUMN report_paths_json TEXT DEFAULT '{}'")


def _migration_v3(conn: Any) -> None:
    """Community detection tables."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS communities (
            community_id TEXT PRIMARY KEY,
            name TEXT,
            symbol_count INTEGER,
            file_count INTEGER,
            cohesion DOUBLE,
            top_kinds_json TEXT,
            file_paths_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS community_members (
            community_id TEXT,
            symbol TEXT,
            PRIMARY KEY(community_id, symbol)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS repo_groups (
            group_name TEXT PRIMARY KEY,
            group_path TEXT,
            repos_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS repo_group_members (
            group_name TEXT,
            repo_name TEXT,
            repo_path TEXT,
            hierarchy_path TEXT,
            PRIMARY KEY(group_name, repo_name)
        )
        """
    )


_MIGRATIONS: dict[int, callable] = {
    1: _migration_v1,
    2: _migration_v2,
    3: _migration_v3,
}


def run_migrations(conn: Any) -> None:
    """Apply all pending schema migrations to the DuckDB connection."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        row[0]
        for row in conn.execute("SELECT version FROM _schema_migrations").fetchall()
    }
    for version in sorted(_MIGRATIONS):
        if version in applied:
            continue
        _MIGRATIONS[version](conn)
        conn.execute("INSERT INTO _schema_migrations (version) VALUES (?)", [version])
