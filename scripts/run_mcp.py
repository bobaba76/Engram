import sys
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import load_settings
from mcp_server.server import MCPServer
from services.api_impact_service import api_impact
from services.detect_changes_service import detect_changes
from services.dependency_service import get_dependencies
from services.file_summary_service import get_file_summary
from services.graph_query_service import execute_graph_query
from services.graph_service import get_callers_and_callees, get_graph_neighborhood_with_options
from services.impact_service import analyze_impact
from services.index_status_service import get_index_status
from services.process_catalog_service import get_symbol_process_participation, list_processes
from services.process_service import trace_execution_flows
from services.rename_service import preview_rename
from services.repo_registry_service import list_indexed_repos, resolve_indexed_repo
from services.review_history_service import get_review_history
from services.route_map_service import route_map
from services.semantic_search import semantic_code_search
from services.source_retrieval_service import get_source_context
from services.symbol_lookup_service import find_symbols
from services.symbol_context_service import get_symbol_context
from services.unified_context_service import get_unified_context
from app.run_modes import FULL, INCREMENTAL
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from storage.manifest_store import ManifestStore
from storage.vector_store import VectorStore


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

    def _get_repo_context(repo: str = "") -> dict[str, Any]:
        repo_root = resolve_indexed_repo(settings.repo_root, repo or None)
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
            "kuzu_store": KuzuStore(repo_settings.kuzu_path),
            "vector_store": VectorStore(repo_settings.lancedb_path),
            "manifest": repo_manifest,
        }
        repo_context_cache[repo_root] = context
        return context

    _get_repo_context()

    def index_status(repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_index_status(context["manifest"])

    def list_repos_tool() -> dict[str, object]:
        return list_indexed_repos(settings.repo_root)

    def reindex_project_tool(project_root: str = "", run_mode: str = INCREMENTAL) -> dict[str, object]:
        target_root = Path(project_root).resolve() if str(project_root or '').strip() else settings.repo_root
        result = _index_project(target_root, run_mode=run_mode)
        if target_root == settings.repo_root:
            manifest.clear()
            manifest.update(result["manifest"] if isinstance(result["manifest"], dict) else {})
            repo_context_cache.pop(settings.repo_root, None)
        repo_context_cache.pop(target_root.resolve(), None)
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
            context["kuzu_store"],
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
            context["kuzu_store"],
            target=target,
            direction=direction,
            max_depth=max_depth,
            file_path=file_path or None,
            kind=kind or None,
            symbol_uid=symbol_uid or None,
        )

    def graph_query_tool(query: str, limit: int = 100, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return execute_graph_query(context["kuzu_store"], query=query, limit=limit)

    def detect_changes_tool(scope: str = "unstaged", base_ref: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return detect_changes(
            context["repo_root"],
            context["duckdb_store"],
            context["kuzu_store"],
            scope=scope,
            base_ref=base_ref or None,
        )

    def route_map_tool(route: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return route_map(context["repo_root"], context["duckdb_store"], route=route)

    def api_impact_tool(route: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return api_impact(context["repo_root"], context["duckdb_store"], route=route)

    def trace_processes_tool(
        target: str,
        file_path: str = "",
        kind: str = "",
        symbol_uid: str = "",
        max_depth: int = 4,
        max_flows: int = 8,
        repo: str = "",
    ) -> dict[str, object]:
        context = _get_repo_context(repo)
        return trace_execution_flows(
            context["duckdb_store"],
            context["kuzu_store"],
            target=target,
            file_path=file_path or None,
            kind=kind or None,
            symbol_uid=symbol_uid or None,
            max_depth=max_depth,
            max_flows=max_flows,
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
            context["kuzu_store"],
            symbol_name=symbol_name,
            new_name=new_name,
            file_path=file_path or None,
            symbol_uid=symbol_uid or None,
        )

    def semantic_code_search_tool(task: str, limit: int = 5, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return semantic_code_search(
            context["vector_store"],
            task=task,
            model_name=context["settings"].embedding_model,
            duckdb_store=context["duckdb_store"],
            limit=limit,
        )

    def get_dependencies_tool(target: str, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_dependencies(context["kuzu_store"], target=target)

    def get_review_history_tool(target: str, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_review_history(context["duckdb_store"], target=target)

    def get_symbol_context_tool(target: str, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_symbol_context(duckdb_store=context["duckdb_store"], target=target)

    def find_symbols_tool(query: str, limit: int = 10, file_path: str = "", kind: str = "", symbol_uid: str = "", repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return find_symbols(context["duckdb_store"], query=query, limit=limit, file_path=file_path or None, kind=kind or None, symbol_uid=symbol_uid or None)

    def get_callers_and_callees_tool(target: str, repo: str = "") -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_callers_and_callees(context["kuzu_store"], target=target)

    def get_graph_neighborhood_tool(
        target: str,
        depth: int = 1,
        relation: str = "",
        max_edges: int = 0,
        mode: str = "full",
        suppress_common_hubs: bool = False,
        repo: str = "",
    ) -> dict[str, object]:
        context = _get_repo_context(repo)
        return get_graph_neighborhood_with_options(
            context["kuzu_store"],
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
        return get_source_context(context["duckdb_store"], target=target, limit=limit)

    server.register_tool("index_status", index_status)
    server.register_tool("list_repos", list_repos_tool)
    server.register_tool("reindex_project", reindex_project_tool)
    server.register_tool("unified_context", unified_context_tool)
    server.register_tool("impact_analysis", impact_analysis_tool)
    server.register_tool("graph_query", graph_query_tool)
    server.register_tool("detect_changes", detect_changes_tool)
    server.register_tool("route_map", route_map_tool)
    server.register_tool("api_impact", api_impact_tool)
    server.register_tool("trace_processes", trace_processes_tool)
    server.register_tool("list_processes", list_processes_tool)
    server.register_tool("symbol_process_participation", symbol_process_participation_tool)
    server.register_tool("preview_rename", preview_rename_tool)
    server.register_tool("semantic_code_search", semantic_code_search_tool)
    server.register_tool("get_dependencies", get_dependencies_tool)
    server.register_tool("get_review_history", get_review_history_tool)
    server.register_tool("get_symbol_context", get_symbol_context_tool)
    server.register_tool("find_symbols", find_symbols_tool)
    server.register_tool("get_callers_and_callees", get_callers_and_callees_tool)
    server.register_tool("get_graph_neighborhood", get_graph_neighborhood_tool)
    server.register_tool("get_file_summary", get_file_summary_tool)
    server.register_tool("get_source_context", get_source_context_tool)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
