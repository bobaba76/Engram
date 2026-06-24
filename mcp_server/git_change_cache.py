"""Git change cache utilities for MCP server.

Provides cached git diff snapshots to avoid spawning git processes on every
MCP tool call that needs change detection.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MCP_CHANGE_PREFLIGHT_FILE_LIMIT = 20
MCP_CHANGE_CACHE_MAX_AGE_SECONDS = 15
MCP_CHANGE_CACHE_WAIT_SECONDS = 3.0


def _scope_key(scope: str, base_ref: str = "") -> str:
    normalized = scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"
    return f"{normalized}:{base_ref or ''}"


def git_cache_path(repo_root: Path, scope: str, base_ref: str = "") -> Path:
    digest = hashlib.sha1(f"{repo_root.resolve()}::{_scope_key(scope, base_ref)}".encode("utf-8")).hexdigest()[:16]
    return ROOT / "data" / "git_change_cache" / f"{digest}.json"


def read_git_change_cache(repo_root: Path, scope: str, base_ref: str = "", min_created_at: float = 0) -> dict[str, object] | None:
    cache_path = git_cache_path(repo_root, scope, base_ref)
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if str(payload.get("repo_root", "")) != str(repo_root.resolve()):
        return None
    if payload.get("scope") != (scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"):
        return None
    if str(payload.get("base_ref") or "") != str(base_ref or ""):
        return None
    created_at = float(payload.get("created_at") or 0)
    if min_created_at and created_at < min_created_at:
        return None
    if time.time() - created_at > MCP_CHANGE_CACHE_MAX_AGE_SECONDS:
        return None
    return payload


def wait_for_git_change_cache(repo_root: Path, scope: str, base_ref: str = "", started_at: float = 0) -> dict[str, object] | None:
    deadline = time.time() + MCP_CHANGE_CACHE_WAIT_SECONDS
    while time.time() < deadline:
        cached = read_git_change_cache(repo_root, scope, base_ref, min_created_at=started_at)
        if cached is not None:
            return cached
        time.sleep(0.05)
    return None


def refresh_git_change_cache(repo_root: Path, scope: str, base_ref: str = "") -> None:
    cache_path = git_cache_path(repo_root, scope, base_ref)
    script = ROOT / "scripts" / "git_change_snapshot.py"
    command = [
        sys.executable,
        str(script),
        "--repo-root",
        str(repo_root.resolve()),
        "--scope",
        scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged",
        "--base-ref",
        base_ref or "",
        "--output",
        str(cache_path),
        "--timeout",
        "20",
    ]
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError:
        return


def mcp_git_changed_files(repo_root: Path, scope: str, base_ref: str = "") -> tuple[list[str], str]:
    normalized = scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"
    cached = read_git_change_cache(repo_root, normalized, base_ref)
    if cached is None:
        refresh_git_change_cache(repo_root, normalized, base_ref)
        return [], normalized
    diff_text = str(cached.get("diff_text") or "")
    changed_files: list[str] = []
    seen: set[str] = set()
    for line in diff_text.splitlines():
        if not line.startswith("+++ b/"):
            continue
        file_path = line[6:].strip()
        if file_path and file_path not in seen:
            seen.add(file_path)
            changed_files.append(file_path)
    return sorted(changed_files), normalized


def fast_repo_root_for_tool(default_repo_root: Path, repo: str = "") -> Path:
    from services.repo_registry_service import resolve_indexed_repo

    repo_text = str(repo or "").strip()
    if not repo_text:
        return default_repo_root
    try:
        return resolve_indexed_repo(default_repo_root, repo_text)
    except ValueError:
        pass
    explicit = Path(repo_text)
    if explicit.is_absolute() and explicit.exists():
        return explicit.resolve()
    sibling = (ROOT.parent / repo_text)
    if sibling.exists():
        return sibling.resolve()
    if default_repo_root.name.lower() == repo_text.lower():
        return default_repo_root
    return default_repo_root


def mcp_change_preflight_payload(repo_root: Path, scope: str, base_ref: str, changed_files: list[str], normalized_scope: str, force: bool = False) -> dict[str, object] | None:
    if not force and normalized_scope != "staged" and changed_files and len(changed_files) <= MCP_CHANGE_PREFLIGHT_FILE_LIMIT:
        return None
    def risk_hints(file_path: str) -> list[str]:
        normalized = file_path.replace("\\", "/").lower()
        name = Path(normalized).name
        hints: list[str] = []
        if normalized.endswith((".s", ".asm", ".inc")):
            hints.append("embedded/native assembly startup or include path")
        if normalized.endswith((".mcp", ".mcw", ".mptags", ".scl", ".plt")):
            hints.append("MPLAB embedded project/config path")
        if normalized.endswith((".h", ".hh", ".hpp", ".hxx")):
            hints.append("public/native header surface")
        if name in {"global.h", "globals.h", "typedefs.h", "sysdefs.h"}:
            hints.append("global embedded C contract header")
        if any(token in name for token in ("trap", "isr", "interrupt", "vector", "reset")):
            hints.append("interrupt/trap/startup path")
        if any(token in name for token in ("uart", "flash", "init", "bootloader")):
            hints.append("embedded peripheral/init/flash path")
        return hints

    high_risk_files = [file_path for file_path in changed_files if risk_hints(file_path)]
    risk = "LOW" if not changed_files else "CRITICAL" if len(changed_files) >= 25 else "HIGH" if high_risk_files else "MEDIUM"
    warnings: list[str] = [
        "MCP git preflight returned a bounded partial response without spawning git; run local detect_changes service or narrow the target for full analysis."
    ]
    git_metadata = {
        "repo_root": str(repo_root.resolve()),
        "scope": normalized_scope,
        "base_ref": base_ref or None,
        "changed_files_count": len(changed_files),
    }
    return {
        "repo_root": str(repo_root.resolve()),
        "scope": normalized_scope,
        "base_ref": base_ref or "",
        "git": git_metadata,
        "risk_scope": "staged_index" if normalized_scope == "staged" else "comparison_range" if normalized_scope == "compare" else "staged_and_unstaged_working_tree" if normalized_scope == "all" else "unstaged_working_tree",
        "risk_applies_to": [f"{normalized_scope} changes"],
        "not_limited_to_recent_edits": normalized_scope in {"unstaged", "staged", "all"},
        "risk_explanation": [
            f"{len(changed_files)} files changed",
            *([f"{len(high_risk_files)} embedded/native sensitive file(s) changed"] if high_risk_files else []),
            "Preflight response skipped symbol/graph traversal.",
        ],
        "risk_by_file": [
            {
                "file": file_path,
                "risk": "HIGH" if risk_hints(file_path) else "MEDIUM",
                "changed_symbols": 0,
                "impacted": False,
                "risk_factors": risk_hints(file_path),
            }
            for file_path in changed_files[:50]
        ],
        "changed_routes": [],
        "affected_consumers": [],
        "changed_response_shapes": [],
        "risk_by_route": [],
        "shape_mismatches": [],
        "affected_processes": [],
        "risk_by_process": [],
        "changed_files": changed_files,
        "changed_symbols": [],
        "impacted_files": [],
        "impacted_symbols": [],
        "risk": risk,
        "confidence": "low" if changed_files else "medium",
        "confidence_explanation": ["Fast git preflight only; graph and symbol analysis not run."] if changed_files else ["No changed files found by git preflight."],
        "warnings": warnings,
        "partial": True,
        "compact_summary": {
            "target": str(repo_root.resolve()),
            "scope": normalized_scope,
            "risk_scope": "staged_index" if normalized_scope == "staged" else "comparison_range" if normalized_scope == "compare" else "staged_and_unstaged_working_tree" if normalized_scope == "all" else "unstaged_working_tree",
            "changed_file_count": len(changed_files),
            "changed_symbol_count": 0,
            "impacted_file_count": 0,
            "risk": risk,
            "confidence": "low" if changed_files else "medium",
            "risk_explanation": [
                f"{len(changed_files)} files changed",
                *([f"{len(high_risk_files)} embedded/native sensitive file(s) changed"] if high_risk_files else []),
                "Preflight response skipped symbol/graph traversal.",
            ],
            "top_changed_files": changed_files[:8],
            "top_changed_symbols": [],
            "top_impacted_files": [],
            "status": "partial",
            "partial": True,
        },
    }
