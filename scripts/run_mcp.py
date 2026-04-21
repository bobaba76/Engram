import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import load_settings
from mcp_server.server import MCPServer
from services.dependency_service import get_dependencies
from services.file_summary_service import get_file_summary
from services.graph_service import get_callers_and_callees, get_graph_neighborhood_with_options
from services.index_status_service import get_index_status
from services.review_history_service import get_review_history
from services.semantic_search import semantic_code_search
from services.source_retrieval_service import get_source_context
from services.symbol_lookup_service import find_symbols
from services.symbol_context_service import get_symbol_context
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


def main() -> int:
    project_root, resolved_by = _resolve_project_root()
    settings = load_settings(project_root)
    duckdb_store = DuckDBStore(settings.duckdb_path, read_only=True)
    kuzu_store = KuzuStore(settings.kuzu_path)
    vector_store = VectorStore(settings.lancedb_path)
    manifest_store = ManifestStore(settings.manifest_path)
    manifest = manifest_store.read_current()
    manifest.setdefault("mcp_resolved_repo_root", str(settings.repo_root))
    manifest.setdefault("mcp_resolution_source", resolved_by)
    server = MCPServer()

    def index_status() -> dict[str, object]:
        return get_index_status(manifest)

    def semantic_code_search_tool(task: str, limit: int = 5) -> dict[str, object]:
        return semantic_code_search(
            vector_store,
            task=task,
            model_name=settings.embedding_model,
            duckdb_store=duckdb_store,
            limit=limit,
        )

    def get_dependencies_tool(target: str) -> dict[str, object]:
        return get_dependencies(kuzu_store, target=target)

    def get_review_history_tool(target: str) -> dict[str, object]:
        return get_review_history(duckdb_store, target=target)

    def get_symbol_context_tool(target: str) -> dict[str, object]:
        return get_symbol_context(duckdb_store=duckdb_store, target=target)

    def find_symbols_tool(query: str, limit: int = 10) -> dict[str, object]:
        return find_symbols(duckdb_store, query=query, limit=limit)

    def get_callers_and_callees_tool(target: str) -> dict[str, object]:
        return get_callers_and_callees(kuzu_store, target=target)

    def get_graph_neighborhood_tool(
        target: str,
        depth: int = 1,
        relation: str = "",
        max_edges: int = 0,
        mode: str = "full",
        suppress_common_hubs: bool = False,
    ) -> dict[str, object]:
        return get_graph_neighborhood_with_options(
            kuzu_store,
            target=target,
            depth=depth,
            relation=relation or None,
            max_edges=max_edges or None,
            mode=mode,
            suppress_common_hubs=suppress_common_hubs,
        )

    def get_file_summary_tool(target: str) -> dict[str, object]:
        return get_file_summary(duckdb_store, target=target)

    def get_source_context_tool(target: str, limit: int = 5) -> dict[str, object]:
        return get_source_context(duckdb_store, target=target, limit=limit)

    server.register_tool("index_status", index_status)
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
