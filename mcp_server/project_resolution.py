"""Project root resolution and indexing utilities for MCP server."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.run_modes import FULL, INCREMENTAL
from config.settings import load_settings
from storage.manifest_store import ManifestStore

ROOT = Path(__file__).resolve().parent.parent


def _manifest_path_for(root: Path) -> Path:
    return root / "data" / "manifests" / "current_manifest.json"


def has_index_manifest(root: Path) -> bool:
    return _manifest_path_for(root).exists()


def _repo_signal(root: Path) -> bool:
    return (root / ".git").exists() or (root / "pyproject.toml").exists() or (root / "package.json").exists()


def most_recent_indexed_sibling() -> Path | None:
    parent = ROOT.parent
    candidates: list[tuple[float, Path]] = []
    for child in parent.iterdir():
        if not child.is_dir() or child.resolve() == ROOT.resolve():
            continue
        manifest_path = _manifest_path_for(child)
        if not manifest_path.exists():
            continue
        try:
            candidates.append((manifest_path.stat().st_mtime, child.resolve()))
        except OSError:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def resolve_project_root() -> tuple[Path | None, str]:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).resolve(), "argv"
    env_root = os.environ.get("CODER_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve(), "env"
    cwd = Path.cwd().resolve()
    if cwd != ROOT.resolve() and (has_index_manifest(cwd) or _repo_signal(cwd)):
        return cwd, "cwd"
    sibling = most_recent_indexed_sibling()
    if sibling is not None:
        return sibling, "recent_indexed_sibling"
    if cwd != ROOT.resolve():
        return cwd, "cwd_fallback"
    return None, "default_coder_root"


def normalize_run_mode(run_mode: str) -> str:
    requested = str(run_mode or '').strip().lower()
    if requested == FULL:
        return FULL
    return INCREMENTAL


def index_project(project_root: Path, run_mode: str) -> dict[str, object]:
    resolved_root = project_root.resolve()
    settings = load_settings(resolved_root)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_index.py"),
        str(resolved_root),
        normalize_run_mode(run_mode),
    ]
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        stdin=subprocess.DEVNULL,
    )
    refreshed_manifest = ManifestStore(settings.manifest_path).read_current()
    refreshed_manifest.setdefault("mcp_resolved_repo_root", str(settings.repo_root))
    refreshed_manifest.setdefault("mcp_resolution_source", "reindex_tool")
    return {
        "command": command,
        "project_root": str(resolved_root),
        "run_mode": normalize_run_mode(run_mode),
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "manifest": refreshed_manifest,
        "ok": completed.returncode == 0,
    }
