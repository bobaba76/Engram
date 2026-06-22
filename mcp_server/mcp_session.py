"""MCP session state management.

Encapsulates the shared state, repo context caching, reindex job management,
and helper methods that were previously closures inside ``run_mcp.main()``.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from config.settings import load_settings
from mcp_server.git_change_cache import (
    fast_repo_root_for_tool,
    mcp_change_preflight_payload,
    mcp_git_changed_files,
    read_git_change_cache,
    refresh_git_change_cache,
    wait_for_git_change_cache,
)
from mcp_server.project_resolution import ROOT, normalize_run_mode
from services.detect_changes_service import detect_changes
from services.repo_registry_service import resolve_indexed_repo
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from storage.manifest_store import ManifestStore
from storage.vector_store import VectorStore


class LazyKuzuStore:
    def __init__(self, opener):
        self._opener = opener

    def _store(self):
        return self._opener()

    def __getattr__(self, name):
        return getattr(self._store(), name)


class MCPSession:
    """Holds MCP server session state and provides shared helpers for tool handlers."""

    def __init__(self, settings, manifest: dict[str, object], resolved_by: str) -> None:
        self.settings = settings
        self.manifest = manifest
        self.resolved_by = resolved_by
        self.selected_repo_root = settings.repo_root.resolve()
        self.repo_context_cache: dict[Path, dict[str, Any]] = {}
        self.reindex_jobs: dict[str, dict[str, Any]] = {}
        self._kuzu_init_lock = threading.Lock()

    # --- Reindex job management ---------------------------------------------

    def _reindex_job_root(self, job_id: str) -> Path:
        safe_job_id = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in {"-", "_"})[:64] or "unknown"
        return ROOT / "data" / "reindex_jobs" / safe_job_id

    def _reindex_job_state_path(self, job_id: str) -> Path:
        return self._reindex_job_root(job_id) / "job.json"

    @staticmethod
    def _serializable_reindex_job(job: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in job.items() if key != "process"}

    def _persist_reindex_job(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("job_id", ""))
        if not job_id:
            return
        state_path = self._reindex_job_state_path(job_id)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = state_path.with_suffix(".tmp")
        try:
            temp_path.write_text(json.dumps(self._serializable_reindex_job(job), indent=2, sort_keys=True), encoding="utf-8")
            temp_path.replace(state_path)
        except OSError:
            return

    def _load_reindex_job(self, job_id: str) -> dict[str, Any] | None:
        state_path = self._reindex_job_state_path(job_id)
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        payload.setdefault("job_id", job_id)
        return payload

    @staticmethod
    def _read_log_tail(path: Path, max_chars: int = 4000) -> str:
        if not path or not path.exists():
            return ""
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                if size > max_chars:
                    handle.seek(max(0, size - max_chars))
                data = handle.read(max_chars)
        except OSError:
            return ""
        return data.decode("utf-8", errors="replace")

    def reindex_status_payload(self, job_id: str) -> dict[str, object]:
        job = self.reindex_jobs.get(job_id)
        if job is None:
            job = self._load_reindex_job(job_id)
            if job is None:
                return {"job_id": job_id, "status": "not_found", "ok": False}
            self.reindex_jobs[job_id] = job
        process = job.get("process")
        if isinstance(process, subprocess.Popen) and job.get("status") == "running":
            return_code = process.poll()
            if return_code is not None:
                target_root = Path(str(job.get("project_root", ""))).resolve()
                repo_settings = load_settings(target_root)
                refreshed_manifest = ManifestStore(repo_settings.manifest_path).read_current()
                refreshed_manifest.setdefault("mcp_resolved_repo_root", str(repo_settings.repo_root))
                refreshed_manifest.setdefault("mcp_resolution_source", "reindex_tool_background")
                job["return_code"] = return_code
                job["finished_at"] = time.time()
                job["status"] = "completed" if return_code == 0 else "failed"
                job["manifest"] = refreshed_manifest
                self._persist_reindex_job(job)
                self.close_all_repo_contexts()
                self.refresh_selected_manifest(target_root, refreshed_manifest)
        stdout_path = Path(str(job.get("stdout_path", "")))
        stderr_path = Path(str(job.get("stderr_path", "")))
        warnings: list[str] = []
        if job.get("status") == "running" and not isinstance(job.get("process"), subprocess.Popen):
            warnings.append(
                "Job state was restored after an MCP restart; live process polling is unavailable for this job. Check stdout/stderr tails or start a new reindex if status does not change."
            )
        return {
            "job_id": job_id,
            "status": job.get("status", "unknown"),
            "ok": job.get("status") == "completed",
            "project_root": job.get("project_root", ""),
            "run_mode": job.get("run_mode", ""),
            "pid": job.get("pid"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "return_code": job.get("return_code"),
            "command": job.get("command", []),
            "stdout_tail": self._read_log_tail(stdout_path),
            "stderr_tail": self._read_log_tail(stderr_path),
            "manifest": job.get("manifest", {}),
            "warnings": warnings,
            "persisted_state_path": str(self._reindex_job_state_path(job_id)),
            "compact_summary": {
                "target": job.get("project_root", ""),
                "status": job.get("status", "unknown"),
                "run_mode": job.get("run_mode", ""),
                "return_code": job.get("return_code"),
                "manifest_counts": (job.get("manifest", {}) if isinstance(job.get("manifest", {}), dict) else {}).get("counts", {}),
                "warnings": warnings,
            },
        }

    def start_background_reindex(self, target_root: Path, run_mode: str) -> dict[str, object]:
        normalized_mode = normalize_run_mode(run_mode)
        job_id = uuid.uuid4().hex[:12]
        job_root = self._reindex_job_root(job_id)
        job_root.mkdir(parents=True, exist_ok=True)
        stdout_path = job_root / "stdout.log"
        stderr_path = job_root / "stderr.log"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "run_index.py"),
            str(target_root.resolve()),
            normalized_mode,
        ]
        self.close_all_repo_contexts()
        stdout_handle = stdout_path.open("w", encoding="utf-8", errors="replace")
        stderr_handle = stderr_path.open("w", encoding="utf-8", errors="replace")
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
        finally:
            stdout_handle.close()
            stderr_handle.close()
        self.reindex_jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "project_root": str(target_root.resolve()),
            "run_mode": normalized_mode,
            "command": command,
            "pid": process.pid,
            "process": process,
            "started_at": time.time(),
            "finished_at": None,
            "return_code": None,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "manifest": {},
        }
        self._persist_reindex_job(self.reindex_jobs[job_id])
        return {
            "job_id": job_id,
            "status": "started",
            "ok": True,
            "project_root": str(target_root.resolve()),
            "run_mode": normalized_mode,
            "pid": process.pid,
            "status_tool": "reindex_status",
            "compact_summary": {
                "target": str(target_root.resolve()),
                "status": "started",
                "run_mode": normalized_mode,
                "job_id": job_id,
            },
        }

    # --- Repo context management --------------------------------------------

    def get_repo_context(self, repo: str = "") -> dict[str, Any]:
        repo_root = resolve_indexed_repo(self.selected_repo_root, repo or None) if str(repo or "").strip() else self.selected_repo_root
        cached = self.repo_context_cache.get(repo_root)
        if cached is not None:
            return cached
        repo_settings = load_settings(repo_root)
        repo_manifest = ManifestStore(repo_settings.manifest_path).read_current()
        repo_manifest.setdefault("mcp_resolved_repo_root", str(repo_settings.repo_root))
        repo_manifest.setdefault("mcp_resolution_source", "tool_repo_param" if str(repo or "").strip() else self.resolved_by)
        context = {
            "repo_root": repo_root,
            "settings": repo_settings,
            "duckdb_store": DuckDBStore(repo_settings.duckdb_path, read_only=True),
            "kuzu_store": None,
            "vector_store": VectorStore(repo_settings.lancedb_path),
            "manifest": repo_manifest,
        }
        self.repo_context_cache[repo_root] = context
        return context

    def get_kuzu_store(self, repo: str = "") -> KuzuStore:
        context = self.get_repo_context(repo)
        cached_store = context.get("kuzu_store")
        if isinstance(cached_store, KuzuStore):
            return cached_store
        with self._kuzu_init_lock:
            cached_store = context.get("kuzu_store")
            if isinstance(cached_store, KuzuStore):
                return cached_store
            kuzu_store = KuzuStore(context["settings"].kuzu_path, read_only=True)
            context["kuzu_store"] = kuzu_store
            return kuzu_store

    def lazy_kuzu(self, repo: str = "") -> LazyKuzuStore:
        return LazyKuzuStore(lambda: self.get_kuzu_store(repo))

    def detect_changes_from_cache(self, scope: str, base_ref: str, repo: str = "") -> dict[str, object] | None:
        repo_root = fast_repo_root_for_tool(self.selected_repo_root, repo)
        normalized_scope = scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"
        cached = read_git_change_cache(repo_root, normalized_scope, base_ref)
        if cached is None:
            started_at = time.time()
            refresh_git_change_cache(repo_root, normalized_scope, base_ref)
            cached = wait_for_git_change_cache(repo_root, normalized_scope, base_ref, started_at=started_at)
        else:
            refresh_git_change_cache(repo_root, normalized_scope, base_ref)
        if cached is None:
            return None
        context = self.get_repo_context(repo)
        warnings = cached.get("warnings", [])
        warning_text = "; ".join(str(item) for item in warnings if item) if isinstance(warnings, list) else ""
        return detect_changes(
            context["repo_root"],
            context["duckdb_store"],
            self.lazy_kuzu(repo),
            scope=normalized_scope,
            base_ref=base_ref or None,
            diff_text_override=str(cached.get("diff_text") or ""),
            git_warning=warning_text or None,
        )

    @staticmethod
    def _close_repo_context(context: dict[str, Any]) -> None:
        for key in ("kuzu_store", "duckdb_store", "vector_store"):
            store = context.get(key)
            close = getattr(store, "close", None)
            if callable(close):
                close()
        context["kuzu_store"] = None
        context["duckdb_store"] = None
        context["vector_store"] = None

    def close_all_repo_contexts(self) -> None:
        for cached_context in list(self.repo_context_cache.values()):
            self._close_repo_context(cached_context)
        self.repo_context_cache.clear()

    def refresh_selected_manifest(self, target_root: Path, refreshed_manifest: dict[str, object]) -> None:
        if target_root == self.settings.repo_root:
            self.manifest.clear()
            self.manifest.update(refreshed_manifest)

    # --- Git change helpers -------------------------------------------------

    def git_changed_files(self, scope: str, base_ref: str, repo: str = "") -> tuple[list[str], str]:
        repo_root = fast_repo_root_for_tool(self.selected_repo_root, repo)
        return mcp_git_changed_files(repo_root, scope, base_ref)

    def change_preflight(self, scope: str, base_ref: str, changed_files: list[str], normalized_scope: str, force: bool = False) -> dict[str, object] | None:
        repo_root = fast_repo_root_for_tool(self.selected_repo_root, "")
        return mcp_change_preflight_payload(repo_root, scope, base_ref, changed_files, normalized_scope, force=force)
