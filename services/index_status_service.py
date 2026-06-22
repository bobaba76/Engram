import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from indexing.scanner import SUPPORTED_EXTENSIONS, SUPPORTED_FILE_NAMES

logger = logging.getLogger(__name__)


def get_index_status(manifest: dict[str, object]) -> dict[str, object]:
    return {
        "status": manifest.get("status", "missing"),
        "run_id": manifest.get("run_id", ""),
        "counts": manifest.get("counts", {}),
        "versions": manifest.get("versions", {}),
        "manifest": manifest,
    }


def _decode_json_field(value: object, fallback):
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def get_recent_runs(duckdb_store, limit: int = 10) -> dict[str, object]:
    rows = duckdb_store.runs.fetch_recent(limit=limit)
    runs: list[dict[str, object]] = []
    for row in rows:
        runs.append(
            {
                "run_id": row.get("run_id", ""),
                "run_mode": row.get("run_mode", ""),
                "status": row.get("status", ""),
                "file_count": int(row.get("file_count") or 0),
                "symbol_count": int(row.get("symbol_count") or 0),
                "chunk_count": int(row.get("chunk_count") or 0),
                "finding_count": int(row.get("finding_count") or 0),
                "stage_results": _decode_json_field(row.get("stage_results_json"), []),
                "warnings": _decode_json_field(row.get("warnings_json"), []),
                "errors": _decode_json_field(row.get("errors_json"), []),
                "report_paths": _decode_json_field(row.get("report_paths_json"), {}),
                "created_at": row.get("created_at"),
            }
        )
    return {
        "run_count": len(runs),
        "runs": runs,
        "compact_summary": {
            "run_count": len(runs),
            "latest_run_id": runs[0]["run_id"] if runs else "",
            "latest_status": runs[0]["status"] if runs else "missing",
        },
    }


def get_run_metrics(duckdb_store, run_id: str) -> dict[str, object]:
    row = duckdb_store.runs.fetch_by_run_id(run_id)
    if row is None:
        return {"run_id": run_id, "status": "missing"}
    return {
        "run_id": row.get("run_id", ""),
        "run_mode": row.get("run_mode", ""),
        "status": row.get("status", ""),
        "file_count": int(row.get("file_count") or 0),
        "symbol_count": int(row.get("symbol_count") or 0),
        "chunk_count": int(row.get("chunk_count") or 0),
        "finding_count": int(row.get("finding_count") or 0),
        "stage_results": _decode_json_field(row.get("stage_results_json"), []),
        "warnings": _decode_json_field(row.get("warnings_json"), []),
        "errors": _decode_json_field(row.get("errors_json"), []),
        "report_paths": _decode_json_field(row.get("report_paths_json"), {}),
        "created_at": row.get("created_at"),
    }


_EXCLUDED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build", ".next", ".nuxt", ".uv"}


def _latest_index_timestamp(duckdb_store) -> float | None:
    """Return the created_at timestamp of the most recent successful index run as epoch seconds."""
    rows = duckdb_store.runs.fetch_recent(limit=10)
    for row in rows:
        if str(row.get("status", "")).lower() in ("completed", "ok", "success", "done"):
            created = row.get("created_at")
            if created is None:
                continue
            if isinstance(created, datetime):
                return created.timestamp()
            if isinstance(created, str):
                try:
                    return datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                except (ValueError, TypeError):
                    continue
            try:
                return float(created)
            except (TypeError, ValueError):
                continue
    return None


def check_stale_index(repo_root: Path, duckdb_store) -> dict[str, object]:
    """Detect files modified after the most recent successful index run.

    Walks the repo root, compares file mtimes against the latest index run timestamp,
    and returns a summary including stale file count and a warning if significant.
    """
    index_ts = _latest_index_timestamp(duckdb_store)
    if index_ts is None:
        return {
            "stale": False,
            "reason": "no_completed_index_run_found",
            "stale_file_count": 0,
            "total_scanned": 0,
            "index_timestamp": None,
            "warnings": [],
        }

    repo_path = Path(repo_root)
    stale_files: list[str] = []
    total_scanned = 0
    scan_limit = 5000

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS and not d.startswith(".")]
        for filename in files:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in SUPPORTED_EXTENSIONS and filename.lower() not in SUPPORTED_FILE_NAMES:
                continue
            filepath = Path(root) / filename
            try:
                mtime = filepath.stat().st_mtime
            except OSError:
                continue
            total_scanned += 1
            if mtime > index_ts:
                try:
                    rel = str(filepath.relative_to(repo_path)).replace("\\", "/")
                except ValueError:
                    rel = str(filepath)
                stale_files.append(rel)
            if total_scanned >= scan_limit:
                break
        if total_scanned >= scan_limit:
            break

    stale_count = len(stale_files)
    stale_pct = (stale_count / total_scanned * 100) if total_scanned > 0 else 0.0
    warnings: list[str] = []
    if stale_count > 0:
        if stale_pct >= 5:
            warnings.append(f"Index may be stale: {stale_count} files ({stale_pct:.1f}%) modified since last index run.")
        elif stale_count >= 3:
            warnings.append(f"Index may be stale: {stale_count} files modified since last index run.")

    return {
        "stale": stale_count > 0,
        "stale_file_count": stale_count,
        "total_scanned": total_scanned,
        "stale_percentage": round(stale_pct, 1),
        "index_timestamp": datetime.fromtimestamp(index_ts, tz=timezone.utc).isoformat(),
        "stale_files": stale_files[:50],
        "warnings": warnings,
    }
