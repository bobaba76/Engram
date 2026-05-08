import sys
import io
import hashlib
import json
import time

if sys.platform == "win32":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

import os
import subprocess
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import load_settings
from mcp_server.resolvers import resolve_tool_target
from mcp_server.server import MCPServer
from services.api_impact_service import api_impact
from services.app_context_service import app_context
from services.change_report_service import change_impact_report
from services.detect_changes_service import detect_changes
from services.dependency_service import get_dependencies
from services.feature_context_service import feature_context
from services.field_impact_service import field_impact
from services.file_summary_service import get_file_summary
from services.graph_query_service import execute_graph_query
from services.graph_service import get_callers_and_callees, get_graph_neighborhood_with_options
from services.impact_service import analyze_impact
from services.index_health_service import index_health
from services.index_status_service import get_index_status, get_recent_runs, get_run_metrics
from services.investigation_service import broad_lexical_search_terms, investigate_codebase, investigation_search_task, should_allow_broad_vector_fallback
from services.process_catalog_service import get_symbol_process_participation, list_processes
from services.process_service import trace_execution_flows
from services.rename_service import preview_rename
from services.repo_registry_service import list_indexed_repos, resolve_indexed_repo
from services.review_history_service import get_review_history
from services.route_map_service import route_map
from services.semantic_search import semantic_code_search
from services.shape_check_service import shape_check
from indexing.embeddings import prewarm_jina_model, is_model_ready, get_model_load_error
from services.source_retrieval_service import get_source_context
from services.symbol_lookup_service import find_symbols
from services.symbol_context_service import get_symbol_context
from services.test_intelligence_service import find_tests_for_target, suggest_tests_for_change, test_impact
from services.unified_context_service import get_unified_context
from app.run_modes import FULL, INCREMENTAL
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from storage.manifest_store import ManifestStore
from storage.vector_store import VectorStore


class LazyKuzuStore:
    def __init__(self, opener):
        self._opener = opener

    def _store(self):
        return self._opener()

    def get_impacted_files(self, *args, **kwargs):
        return self._store().get_impacted_files(*args, **kwargs)

    def edges_for_target(self, *args, **kwargs):
        return self._store().edges_for_target(*args, **kwargs)

    def edges_for_source(self, *args, **kwargs):
        return self._store().edges_for_source(*args, **kwargs)


MCP_CHANGE_PREFLIGHT_FILE_LIMIT = 20
MCP_CHANGE_CACHE_MAX_AGE_SECONDS = 15
MCP_CHANGE_CACHE_WAIT_SECONDS = 3.0


def _scope_key(scope: str, base_ref: str = "") -> str:
    normalized = scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"
    return f"{normalized}:{base_ref or ''}"


def _git_cache_path(repo_root: Path, scope: str, base_ref: str = "") -> Path:
    digest = hashlib.sha1(f"{repo_root.resolve()}::{_scope_key(scope, base_ref)}".encode("utf-8")).hexdigest()[:16]
    return ROOT / "data" / "git_change_cache" / f"{digest}.json"


def _read_git_change_cache(repo_root: Path, scope: str, base_ref: str = "", min_created_at: float = 0) -> dict[str, object] | None:
    cache_path = _git_cache_path(repo_root, scope, base_ref)
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


def _wait_for_git_change_cache(repo_root: Path, scope: str, base_ref: str = "", started_at: float = 0) -> dict[str, object] | None:
    deadline = time.time() + MCP_CHANGE_CACHE_WAIT_SECONDS
    while time.time() < deadline:
        cached = _read_git_change_cache(repo_root, scope, base_ref, min_created_at=started_at)
        if cached is not None:
            return cached
        time.sleep(0.05)
    return None


def _refresh_git_change_cache(repo_root: Path, scope: str, base_ref: str = "") -> None:
    cache_path = _git_cache_path(repo_root, scope, base_ref)
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


def _mcp_git_changed_files(repo_root: Path, scope: str, base_ref: str = "") -> tuple[list[str], str]:
    normalized = scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"
    cached = _read_git_change_cache(repo_root, normalized, base_ref)
    if cached is None:
        _refresh_git_change_cache(repo_root, normalized, base_ref)
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


def _fast_repo_root_for_tool(selected_repo_root: Path, repo: str = "") -> Path:
    repo_text = str(repo or "").strip()
    if not repo_text:
        return selected_repo_root
    explicit = Path(repo_text)
    if explicit.is_absolute() and explicit.exists():
        return explicit.resolve()
    sibling = (ROOT.parent / repo_text)
    if sibling.exists():
        return sibling.resolve()
    if selected_repo_root.name.lower() == repo_text.lower():
        return selected_repo_root
    return selected_repo_root


def _mcp_change_preflight_payload(repo_root: Path, scope: str, base_ref: str, changed_files: list[str], normalized_scope: str, force: bool = False) -> dict[str, object] | None:
    if not force and normalized_scope != "staged" and changed_files and len(changed_files) <= MCP_CHANGE_PREFLIGHT_FILE_LIMIT:
        return None
    risk = "LOW" if not changed_files else "CRITICAL" if len(changed_files) >= 25 else "HIGH"
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
        "risk_explanation": [f"{len(changed_files)} files changed", "Preflight response skipped symbol/graph traversal."],
        "risk_by_file": [{"file": file_path, "risk": "MEDIUM", "changed_symbols": 0, "impacted": False, "risk_factors": []} for file_path in changed_files[:50]],
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
            "risk_explanation": [f"{len(changed_files)} files changed", "Preflight response skipped symbol/graph traversal."],
            "top_changed_files": changed_files[:8],
            "top_changed_symbols": [],
            "top_impacted_files": [],
            "status": "partial",
            "partial": True,
        },
    }


def _manifest_path_for(root: Path) -> Path:
    return root / "data" / "manifests" / "current_manifest.json"


def _has_index_manifest(root: Path) -> bool:
    return _manifest_path_for(root).exists()


def _repo_signal(root: Path) -> bool:
    return (root / ".git").exists() or (root / "pyproject.toml").exists() or (root / "package.json").exists()


def _most_recent_indexed_sibling() -> Path | None:
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


def _resolve_project_root() -> tuple[Path | None, str]:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).resolve(), "argv"
    env_root = os.environ.get("CODER_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve(), "env"
    cwd = Path.cwd().resolve()
    if cwd != ROOT.resolve() and (_has_index_manifest(cwd) or _repo_signal(cwd)):
        return cwd, "cwd"
    sibling = _most_recent_indexed_sibling()
    if sibling is not None:
        return sibling, "recent_indexed_sibling"
    if cwd != ROOT.resolve():
        return cwd, "cwd_fallback"
    return None, "default_coder_root"


def _normalize_run_mode(run_mode: str) -> str:
    requested = str(run_mode or '').strip().lower()
    if requested == FULL:
        return FULL
    return INCREMENTAL


def _index_project(project_root: Path, run_mode: str) -> dict[str, object]:
    resolved_root = project_root.resolve()
    settings = load_settings(resolved_root)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_index.py"),
        str(resolved_root),
        _normalize_run_mode(run_mode),
    ]
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    refreshed_manifest = ManifestStore(settings.manifest_path).read_current()
    refreshed_manifest.setdefault("mcp_resolved_repo_root", str(settings.repo_root))
    refreshed_manifest.setdefault("mcp_resolution_source", "reindex_tool")
    return {
        "command": command,
        "project_root": str(resolved_root),
        "run_mode": _normalize_run_mode(run_mode),
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "manifest": refreshed_manifest,
        "ok": completed.returncode == 0,
    }


def main() -> int:
    project_root, resolved_by = _resolve_project_root()
    settings = load_settings(project_root)
    manifest_store = ManifestStore(settings.manifest_path)
    manifest = manifest_store.read_current()
    manifest.setdefault("mcp_resolved_repo_root", str(settings.repo_root))
    manifest.setdefault("mcp_resolution_source", resolved_by)
    server = MCPServer()
    repo_context_cache: dict[Path, dict[str, Any]] = {}
    _kuzu_init_lock = threading.Lock()
    selected_repo_root = settings.repo_root.resolve()

    def _get_repo_context(repo: str = "") -> dict[str, Any]:
        repo_root = resolve_indexed_repo(selected_repo_root, repo or None) if str(repo or "").strip() else selected_repo_root
        cached = repo_context_cache.get(repo_root)
        if cached is not None:
            return cached
        repo_settings = load_settings(repo_root)
        repo_manifest = ManifestStore(repo_settings.manifest_path).read_current()
        repo_manifest.setdefault("mcp_resolved_repo_root", str(repo_settings.repo_root))
        repo_manifest.setdefault("mcp_resolution_source", "tool_repo_param" if str(repo or "").strip() else resolved_by)
        context = {
            "repo_root": repo_root,
            "settings": repo_settings,
            "duckdb_store": DuckDBStore(repo_settings.duckdb_path, read_only=True),
            "kuzu_store": None,
            "vector_store": VectorStore(repo_settings.lancedb_path),
            "manifest": repo_manifest,
        }
        repo_context_cache[repo_root] = context
        return context

    def _get_kuzu_store(repo: str = "") -> KuzuStore:
        context = _get_repo_context(repo)
        cached_store = context.get("kuzu_store")
        if isinstance(cached_store, KuzuStore):
            return cached_store
        with _kuzu_init_lock:
            # Re-check inside the lock — another thread may have opened it
            cached_store = context.get("kuzu_store")
            if isinstance(cached_store, KuzuStore):
                return cached_store
            kuzu_store = KuzuStore(context["settings"].kuzu_path, read_only=True)
            context["kuzu_store"] = kuzu_store
            return kuzu_store

    def _detect_changes_from_cache(scope: str, base_ref: str, repo: str = "") -> dict[str, object] | None:
        repo_root = _fast_repo_root_for_tool(selected_repo_root, repo)
        normalized_scope = scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"
        cached = _read_git_change_cache(repo_root, normalized_scope, base_ref)
        if cached is None:
            started_at = time.time()
            _refresh_git_change_cache(repo_root, normalized_scope, base_ref)
            cached = _wait_for_git_change_cache(repo_root, normalized_scope, base_ref, started_at=started_at)
        else:
            _refresh_git_change_cache(repo_root, normalized_scope, base_ref)
        if cached is None:
            return None
        context = _get_repo_context(repo)
        warnings = cached.get("warnings", [])
        warning_text = "; ".join(str(item) for item in warnings if item) if isinstance(warnings, list) else ""
        return detect_changes(
            context["repo_root"],
            context["duckdb_store"],
            LazyKuzuStore(lambda: _get_kuzu_store(repo)),
            scope=normalized_scope,
            base_ref=base_ref or None,
            diff_text_override=str(cached.get("diff_text") or ""),
            git_warning=warning_text or None,
        )

    def _close_repo_context(context: dict[str, Any]) -> None:
        for key in ("kuzu_store", "duckdb_store"):
            store = context.get(key)
            close = getattr(store, "close", None)
            if callable(close):
                close()
        context["kuzu_store"] = None

    def index_status(repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_index_status(context["manifest"])

    def list_repos_tool() -> dict[str, object]:
        payload = list_indexed_repos(selected_repo_root)
        payload["selected_repo"] = str(selected_repo_root)
        payload["compact_summary"]["selected_repo"] = selected_repo_root.name
        return payload

    def select_repo_tool(repo: str) -> dict[str, object]:
        nonlocal selected_repo_root
        resolved_repo_root = resolve_indexed_repo(selected_repo_root, repo)
        selected_repo_root = resolved_repo_root
        context = _get_repo_context()
        return {
            "selected_repo": str(selected_repo_root),
            "repo_name": selected_repo_root.name,
            "manifest": context["manifest"],
            "summary_text": f"Selected repo: {selected_repo_root}",
            "highlights": [f"Selected repo: {selected_repo_root.name}"],
        }

    def get_recent_runs_tool(limit: int = 10, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_recent_runs(context["duckdb_store"], limit=limit)

    def get_run_metrics_tool(run_id: str, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_run_metrics(context["duckdb_store"], run_id=run_id)

    def reindex_project_tool(project_root: str = "", run_mode: str = INCREMENTAL) -> dict[str, object]:
        target_root = Path(project_root).resolve() if str(project_root or '').strip() else settings.repo_root
        for cached_context in list(repo_context_cache.values()):
            _close_repo_context(cached_context)
        repo_context_cache.clear()
        result = _index_project(target_root, run_mode=run_mode)
        if target_root == settings.repo_root:
            manifest.clear()
            manifest.update(result["manifest"] if isinstance(result["manifest"], dict) else {})
        return result

    def unified_context_tool(
        target: str,
        max_matches: int = 5,
        neighborhood_depth: int = 1,
        file_path: str = "",
        kind: str = "",
        symbol_uid: str = "",
        repo: str = "",
    ) -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_unified_context(
            context["duckdb_store"],
            _get_kuzu_store(repo),
            target=target,
            max_matches=max_matches,
            neighborhood_depth=neighborhood_depth,
            file_path=file_path or None,
            kind=kind or None,
            symbol_uid=symbol_uid or None,
        )

    def impact_analysis_tool(
        target: str,
        direction: str = "upstream",
        max_depth: int = 3,
        file_path: str = "",
        kind: str = "",
        symbol_uid: str = "",
        repo: str = "",
    ) -> dict[str, object]:
        context = _get_repo_context(repo)
        return analyze_impact(
            context["duckdb_store"],
            _get_kuzu_store(repo),
            target=target,
            direction=direction,
            max_depth=max_depth,
            file_path=file_path or None,
            kind=kind or None,
            symbol_uid=symbol_uid or None,
        )

    def graph_query_tool(query: str, limit: int = 100, repo: str = "") -> dict[str, object]:
        return execute_graph_query(_get_kuzu_store(repo), query=query, limit=limit)

    def detect_changes_tool(scope: str = "unstaged", base_ref: str = "", repo: str = "") -> dict[str, object]:
        cached_changes = _detect_changes_from_cache(scope, base_ref, repo)
        if cached_changes is not None:
            return cached_changes
        repo_root = _fast_repo_root_for_tool(selected_repo_root, repo)
        changed_files, normalized_scope = _mcp_git_changed_files(repo_root, scope, base_ref)
        preflight = _mcp_change_preflight_payload(repo_root, scope, base_ref, changed_files, normalized_scope, force=True)
        if preflight is not None or normalized_scope == "staged":
            return preflight
        context = _get_repo_context(repo)
        return detect_changes(
            context["repo_root"],
            context["duckdb_store"],
            LazyKuzuStore(lambda: _get_kuzu_store(repo)),
            scope=scope,
            base_ref=base_ref or None,
        )

    def route_map_tool(route: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return route_map(context["repo_root"], context["duckdb_store"], route=route)

    def api_impact_tool(route: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return api_impact(context["repo_root"], context["duckdb_store"], route=route, kuzu_store=_get_kuzu_store(repo))

    def shape_check_tool(route: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return shape_check(context["repo_root"], context["duckdb_store"], route=route, kuzu_store=_get_kuzu_store(repo))

    def field_impact_tool(field: str, route: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return field_impact(
            context["repo_root"],
            context["duckdb_store"],
            field=field,
            route=route,
            kuzu_store=_get_kuzu_store(repo),
        )

    def app_context_tool(target: str = "", limit: int = 12, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return app_context(
            context["repo_root"],
            context["duckdb_store"],
            _get_kuzu_store(repo),
            target=target,
            limit=limit,
        )

    def resolve_target_tool(
        target: str = "",
        file_path: str = "",
        kind: str = "",
        symbol_uid: str = "",
        limit: int = 5,
        repo: str = "",
    ) -> dict[str, object]:
        context = _get_repo_context(repo)
        return resolve_tool_target(
            context["duckdb_store"],
            context["repo_root"],
            target=target,
            file_path=file_path or None,
            kind=kind or None,
            symbol_uid=symbol_uid or None,
            limit=limit,
        )

    def trace_processes_tool(
        target: str,
        file_path: str = "",
        kind: str = "",
        symbol_uid: str = "",
        max_depth: int = 4,
        max_flows: int = 8,
        changed_symbols: str = "",
        repo: str = "",
    ) -> dict[str, object]:
        context = _get_repo_context(repo)
        changed_symbol_list = [item.strip() for item in changed_symbols.split(",") if item.strip()]
        return trace_execution_flows(
            context["duckdb_store"],
            _get_kuzu_store(repo),
            target=target,
            file_path=file_path or None,
            kind=kind or None,
            symbol_uid=symbol_uid or None,
            max_depth=max_depth,
            max_flows=max_flows,
            changed_symbols=changed_symbol_list or None,
        )

    def list_processes_tool(query: str = "", limit: int = 25, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return list_processes(context["duckdb_store"], query=query, limit=limit)

    def symbol_process_participation_tool(
        target: str,
        file_path: str = "",
        kind: str = "",
        symbol_uid: str = "",
        limit: int = 25,
        repo: str = "",
    ) -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_symbol_process_participation(
            context["duckdb_store"],
            target=target,
            file_path=file_path or None,
            kind=kind or None,
            symbol_uid=symbol_uid or None,
            limit=limit,
        )

    def preview_rename_tool(symbol_name: str, new_name: str, file_path: str = "", symbol_uid: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return preview_rename(
            context["repo_root"],
            context["duckdb_store"],
            _get_kuzu_store(repo),
            symbol_name=symbol_name,
            new_name=new_name,
            file_path=file_path or None,
            symbol_uid=symbol_uid or None,
        )

    def semantic_code_search_tool(task: str, limit: int = 5, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        model_name = context["settings"].embedding_model
        prewarm_jina_model(
            model_name,
            device=context["settings"].embedding_device,
        )
        model_ready = is_model_ready(model_name)
        load_error = get_model_load_error(model_name) if not model_ready else ""
        result = semantic_code_search(
            context["vector_store"],
            task=task,
            model_name=model_name,
            duckdb_store=context["duckdb_store"],
            kuzu_store=_get_kuzu_store(repo),
            limit=limit,
            max_length=context["settings"].embedding_max_length,
            device=context["settings"].embedding_device,
            provider_name=context["settings"].embedding_provider,
            api_key=context["settings"].embedding_api_key,
            base_url=context["settings"].embedding_base_url,
            include_vector=model_ready,
        )
        if not model_ready:
            warnings = result.setdefault("warnings", [])
            if load_error:
                warnings.append(f"Vector search skipped: model failed to load ({load_error}). Lexical results only.")
            else:
                warnings.append(
                    "Vector search skipped: embedding model is still loading in the background. "
                    "Retry in a few seconds for full semantic results. Lexical results only."
                )
        return result

    def investigate_codebase_tool(question: str, limit: int = 5, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        search_task, search_plan = investigation_search_task(question, limit=limit)
        intent = search_plan.get("intent", {}) if isinstance(search_plan.get("intent", {}), dict) else {}
        guardrails = search_plan.get("guardrails", {}) if isinstance(search_plan.get("guardrails", {}), dict) else {}
        intent_primary = str(intent.get("primary", "general") or "general")
        broad_question = bool(guardrails.get("broad_question"))
        impact_question = intent_primary == "impact"
        exploratory_question = intent_primary in {"ui_ownership", "feature_exploration"}
        lightweight_exploratory = bool(exploratory_question and (broad_question or len(intent.get("tokens", [])) >= 8))
        safe_first_pass = broad_question or impact_question
        if lightweight_exploratory:
            return investigate_codebase(
                context["repo_root"],
                context["duckdb_store"],
                _get_kuzu_store(repo),
                question=question,
                search_payload={
                    "compact_results": [],
                    "retrieval_diagnostics": {
                        "exploratory_budget_short_circuit": True,
                        "investigation_safe_first_pass": True,
                        "exploratory_lightweight_path": True,
                    },
                    "investigation_search_plan": search_plan,
                },
                limit=limit,
            )
        search_limit = int(guardrails.get("search_limit", limit) or limit)
        lexical_terms = broad_lexical_search_terms(search_task, search_plan.get("query_rewrite", {}), limit=4) if safe_first_pass else [search_task]
        search_payload = semantic_code_search(
            context["vector_store"],
            task=search_task,
            model_name=context["settings"].embedding_model,
            duckdb_store=context["duckdb_store"],
            kuzu_store=_get_kuzu_store(repo),
            limit=search_limit,
            max_length=context["settings"].embedding_max_length,
            device=context["settings"].embedding_device,
            provider_name=context["settings"].embedding_provider,
            api_key=context["settings"].embedding_api_key,
            base_url=context["settings"].embedding_base_url,
            max_variants=1 if safe_first_pass else 3,
            include_vector=not safe_first_pass,
            include_graph=not safe_first_pass,
            include_expansion=not safe_first_pass,
            extra_query_terms=lexical_terms,
        )
        if safe_first_pass and isinstance(search_payload, dict):
            retrieval_diag = search_payload.get("retrieval_diagnostics", {})
            if isinstance(retrieval_diag, dict):
                retrieval_diag["investigation_safe_first_pass"] = True
                retrieval_diag["impact_safe_path"] = impact_question
                retrieval_diag["broad_safe_path"] = broad_question
        if safe_first_pass and isinstance(search_payload, dict) and not search_payload.get("compact_results") and should_allow_broad_vector_fallback(search_task, search_plan.get("query_rewrite", {})):
            fallback_payload = semantic_code_search(
                context["vector_store"],
                task=search_task,
                model_name=context["settings"].embedding_model,
                duckdb_store=context["duckdb_store"],
                kuzu_store=_get_kuzu_store(repo),
                limit=min(search_limit, 3),
                max_length=context["settings"].embedding_max_length,
                device=context["settings"].embedding_device,
                provider_name=context["settings"].embedding_provider,
                api_key=context["settings"].embedding_api_key,
                base_url=context["settings"].embedding_base_url,
                max_variants=1,
                include_vector=True,
                include_graph=False,
                include_expansion=False,
                extra_query_terms=lexical_terms,
            )
            if isinstance(fallback_payload, dict):
                fallback_payload["investigation_search_plan"] = search_plan
                fallback_diag = fallback_payload.get("retrieval_diagnostics", {})
                if isinstance(fallback_diag, dict):
                    fallback_diag["fallback_from_lexical_only"] = True
                    fallback_diag["impact_safe_path"] = impact_question
                    fallback_diag["broad_safe_path"] = broad_question
                search_payload = fallback_payload
        elif safe_first_pass and isinstance(search_payload, dict) and not search_payload.get("compact_results"):
            fallback_diag = search_payload.get("retrieval_diagnostics", {})
            if isinstance(fallback_diag, dict):
                fallback_diag["fallback_from_lexical_only"] = False
                fallback_diag["fallback_skipped_broad_target"] = True
                fallback_diag["impact_safe_path"] = impact_question
                fallback_diag["broad_safe_path"] = broad_question
        if isinstance(search_payload, dict):
            search_payload.setdefault("investigation_search_plan", search_plan)
        return investigate_codebase(
            context["repo_root"],
            context["duckdb_store"],
            _get_kuzu_store(repo),
            question=question,
            search_payload=search_payload,
            limit=limit,
        )

    def change_impact_report_tool(scope: str = "unstaged", base_ref: str = "", max_symbols: int = 5, repo: str = "", target: str = "") -> dict[str, object]:
        cached_changes = _detect_changes_from_cache(scope, base_ref, repo)
        if cached_changes is not None:
            context = _get_repo_context(repo)
            return change_impact_report(
                context["repo_root"],
                context["duckdb_store"],
                LazyKuzuStore(lambda: _get_kuzu_store(repo)),
                scope=scope,
                base_ref=base_ref,
                max_symbols=max_symbols,
                changes=cached_changes,
                target=target,
            )
        repo_root = _fast_repo_root_for_tool(selected_repo_root, repo)
        changed_files, normalized_scope = _mcp_git_changed_files(repo_root, scope, base_ref)
        preflight = _mcp_change_preflight_payload(repo_root, scope, base_ref, changed_files, normalized_scope, force=True)
        if preflight is not None and not target:
            return {
                "scope": normalized_scope,
                "base_ref": base_ref,
                "risk": preflight.get("risk", "LOW"),
                "confidence": preflight.get("confidence", "low"),
                "risk_scope": preflight.get("risk_scope", normalized_scope),
                "risk_explanation": preflight.get("risk_explanation", []),
                "risk_by_file": preflight.get("risk_by_file", []),
                "git": preflight.get("git", {}),
                "changed_routes": [],
                "affected_consumers": [],
                "changed_response_shapes": [],
                "risk_by_route": [],
                "shape_mismatches": [],
                "affected_processes": [],
                "risk_by_process": [],
                "changes": preflight,
                "symbol_impacts": [],
                "app_contexts": [],
                "frontend_graph": {
                    "frontend_file_count": len([path for path in changed_files if path.lower().endswith((".ts", ".tsx", ".js", ".jsx"))]),
                    "top_frontend_files": [path for path in changed_files if path.lower().endswith((".ts", ".tsx", ".js", ".jsx"))][:6],
                    "frontend_graph_edge_count": 0,
                    "top_relations": {},
                    "has_indirect_frontend_path": False,
                    "summary": "Preflight response only; route consumer graph not traversed.",
                },
                "test_recommendations": {"compact_summary": {"top_files": []}, "recommended_tests": []},
                "what_changed": [f"{len(changed_files)} files changed.", "Symbol analysis skipped by MCP preflight."],
                "what_to_test": [],
                "warnings": preflight.get("warnings", []),
                "partial": preflight.get("partial", False),
                "compact_summary": {
                    **dict(preflight.get("compact_summary", {}) if isinstance(preflight.get("compact_summary", {}), dict) else {}),
                    "frontend_graph": {
                        "frontend_file_count": len([path for path in changed_files if path.lower().endswith((".ts", ".tsx", ".js", ".jsx"))]),
                        "top_frontend_files": [path for path in changed_files if path.lower().endswith((".ts", ".tsx", ".js", ".jsx"))][:6],
                        "frontend_graph_edge_count": 0,
                        "has_indirect_frontend_path": False,
                    },
                },
            }
        context = _get_repo_context(repo)
        return change_impact_report(
            context["repo_root"],
            context["duckdb_store"],
            LazyKuzuStore(lambda: _get_kuzu_store(repo)),
            scope=scope,
            base_ref=base_ref,
            max_symbols=max_symbols,
            target=target,
        )

    def find_tests_for_target_tool(target: str, limit: int = 10, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return find_tests_for_target(context["duckdb_store"], target=target, limit=limit)

    def suggest_tests_for_change_tool(scope: str = "unstaged", base_ref: str = "", repo: str = "") -> dict[str, object]:
        cached_changes = _detect_changes_from_cache(scope, base_ref, repo)
        if cached_changes is not None:
            context = _get_repo_context(repo)
            return suggest_tests_for_change(
                context["repo_root"],
                context["duckdb_store"],
                LazyKuzuStore(lambda: _get_kuzu_store(repo)),
                scope=scope,
                base_ref=base_ref,
                changes=cached_changes,
            )
        repo_root = _fast_repo_root_for_tool(selected_repo_root, repo)
        changed_files, normalized_scope = _mcp_git_changed_files(repo_root, scope, base_ref)
        preflight = _mcp_change_preflight_payload(repo_root, scope, base_ref, changed_files, normalized_scope, force=True)
        if preflight is not None:
            return {
                "scope": normalized_scope,
                "base_ref": base_ref,
                "changes": preflight,
                "recommended_tests": [],
                "compact_results": [],
                "warnings": preflight.get("warnings", []),
                "partial": True,
                "compact_summary": {
                    "target": f"{normalized_scope} changes",
                    "changed_file_count": len(changed_files),
                    "test_count": 0,
                    "top_files": [],
                    "status": "partial",
                    "partial": True,
                },
                "status": "partial",
            }
        context = _get_repo_context(repo)
        return suggest_tests_for_change(context["repo_root"], context["duckdb_store"], LazyKuzuStore(lambda: _get_kuzu_store(repo)), scope=scope, base_ref=base_ref)

    def test_impact_tool(scope: str = "unstaged", base_ref: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return test_impact(context["repo_root"], context["duckdb_store"], LazyKuzuStore(lambda: _get_kuzu_store(repo)), scope=scope, base_ref=base_ref)

    def feature_context_tool(feature: str, limit: int = 12, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return feature_context(context["repo_root"], context["duckdb_store"], _get_kuzu_store(repo), feature=feature, limit=limit)

    def index_health_tool(repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return index_health(context["repo_root"], context["duckdb_store"], _get_kuzu_store(repo))

    def get_dependencies_tool(target: str, repo: str = "") -> dict[str, object]:
        return get_dependencies(_get_kuzu_store(repo), target=target)

    def get_review_history_tool(target: str, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_review_history(context["duckdb_store"], target=target)

    def get_symbol_context_tool(target: str, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_symbol_context(duckdb_store=context["duckdb_store"], kuzu_store=_get_kuzu_store(repo), target=target)

    def find_symbols_tool(query: str, limit: int = 10, file_path: str = "", kind: str = "", symbol_uid: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return find_symbols(context["duckdb_store"], query=query, limit=limit, file_path=file_path or None, kind=kind or None, symbol_uid=symbol_uid or None)

    def get_callers_and_callees_tool(target: str, repo: str = "") -> dict[str, object]:
        return get_callers_and_callees(_get_kuzu_store(repo), target=target)

    def get_graph_neighborhood_tool(
        target: str,
        depth: int = 1,
        relation: str = "",
        max_edges: int = 0,
        mode: str = "full",
        suppress_common_hubs: bool = False,
        repo: str = "",
    ) -> dict[str, object]:
        return get_graph_neighborhood_with_options(
            _get_kuzu_store(repo),
            target=target,
            depth=depth,
            relation=relation or None,
            max_edges=max_edges or None,
            mode=mode,
            suppress_common_hubs=suppress_common_hubs,
        )

    def get_file_summary_tool(target: str, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_file_summary(context["duckdb_store"], target=target)

    def get_source_context_tool(target: str, limit: int = 5, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_source_context(context["duckdb_store"], target=target, limit=limit, repo_root=context["repo_root"])

    tool_definitions = [
        ("index_status", index_status, "Show index readiness, counts, versions, and resolved repository metadata."),
        ("list_repos", list_repos_tool, "List indexed sibling repositories Coder can serve."),
        ("select_repo", select_repo_tool, "Select the default repo target for this MCP session."),
        ("get_recent_runs", get_recent_runs_tool, "List recent persisted index runs including parsed stage summaries."),
        ("get_run_metrics", get_run_metrics_tool, "Show parsed persisted stage metrics for a specific run ID."),
        ("reindex_project", reindex_project_tool, "Run an incremental or full index refresh for a repository."),
        ("unified_context", unified_context_tool, "Resolve an exact or near-exact target and return matches, callers/callees, dependencies, and graph neighborhood. Prefer after resolve_target for broad names."),
        ("impact_analysis", impact_analysis_tool, "Estimate upstream or downstream impact for a symbol target. Prefer exact symbols or resolved targets; broad inputs may return partial results with warnings."),
        ("graph_query", graph_query_tool, "Execute a read-only graph query against the indexed Kuzu graph."),
        ("detect_changes", detect_changes_tool, "Analyze changed files and related graph impact for the working tree or git ref."),
        ("route_map", route_map_tool, "Map API/frontend route strings to likely files and symbols."),
        ("api_impact", api_impact_tool, "Estimate code impact for an API route."),
        ("shape_check", shape_check_tool, "Check API route response shapes against frontend consumer field reads."),
        ("field_impact", field_impact_tool, "Show which consumers read a specific API response field, optionally within one route."),
        ("app_context", app_context_tool, "Map app-level context across routes, files, tables, graph edges, and processes. Broad natural-language targets are capped for safety and may return partial context."),
        ("resolve_target", resolve_target_tool, "Resolve a file, symbol name, or symbol UID to the indexed target Coder will use. Best first step before graph-heavy symbol tools."),
        ("trace_processes", trace_processes_tool, "Trace execution/process flows around a target symbol."),
        ("list_processes", list_processes_tool, "List inferred process clusters from the indexed codebase."),
        ("symbol_process_participation", symbol_process_participation_tool, "Show process clusters involving a target symbol."),
        ("preview_rename", preview_rename_tool, "Preview references that may need edits for a symbol rename."),
        ("semantic_code_search", semantic_code_search_tool, "Search indexed chunks semantically for a natural language task. Use when you do not yet have an exact symbol or file target."),
        ("investigate_codebase", investigate_codebase_tool, "Safely investigate a natural-language codebase question using search, symbol resolution, snippets, graph, and app context. Broad questions may be narrowed automatically."),
        ("change_impact_report", change_impact_report_tool, "Safely summarize git changes, likely impact, app context, and recommended tests for the current worktree or a base ref."),
        ("find_tests_for_target", find_tests_for_target_tool, "Find likely tests for a symbol, file, or feature target."),
        ("suggest_tests_for_change", suggest_tests_for_change_tool, "Suggest tests for current git changes."),
        ("test_impact", test_impact_tool, "Estimate testing impact and risk for current git changes."),
        ("feature_context", feature_context_tool, "Map a feature to related files, routes, tables, processes, and graph context."),
        ("index_health", index_health_tool, "Report index health, counts, parser/chunk distribution, recent runs, and warnings."),
        ("get_dependencies", get_dependencies_tool, "Show dependency graph context for a target."),
        ("get_review_history", get_review_history_tool, "Show persisted review findings and analyses for a target file."),
        ("get_symbol_context", get_symbol_context_tool, "Show direct symbol metadata and related source context."),
        ("find_symbols", find_symbols_tool, "Find symbols by query, file, kind, or symbol UID. Good follow-up when resolve_target reports ambiguity."),
        ("get_callers_and_callees", get_callers_and_callees_tool, "Show direct CALLS callers and callees for a symbol target."),
        ("get_graph_neighborhood", get_graph_neighborhood_tool, "Show filtered graph neighborhood for a target."),
        ("get_file_summary", get_file_summary_tool, "Summarize indexed symbols and chunks for a file."),
        ("get_source_context", get_source_context_tool, "Return source chunks and previews for a target."),
    ]
    for tool_name, handler, description in tool_definitions:
        server.register_tool(tool_name, handler, description=description)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
