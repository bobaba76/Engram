import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.coordinator import Coordinator
from config.settings import load_settings
from mcp_server.server import MCPServer
from services.dependency_service import get_dependencies
from services.file_summary_service import get_file_summary
from services.graph_service import get_callers_and_callees, get_graph_neighborhood
from services.index_status_service import get_index_status
from services.review_history_service import get_review_history
from services.semantic_search import semantic_code_search
from services.source_retrieval_service import get_source_context
from services.symbol_lookup_service import find_symbols
from services.symbol_context_service import get_symbol_context


def main() -> int:
    settings = load_settings()
    coordinator = Coordinator(settings)
    coordinator.run()

    manifest = coordinator.manifest_store.read_current()
    server = MCPServer()
    server.register_tool("index_status", lambda: get_index_status(manifest))
    server.register_tool(
        "semantic_code_search",
        lambda task, limit=5: semantic_code_search(
            coordinator.vector_store,
            task=task,
            model_name=settings.embedding_model,
            limit=limit,
        ),
    )
    server.register_tool(
        "get_dependencies",
        lambda target: get_dependencies(coordinator.kuzu, target=target),
    )
    server.register_tool(
        "get_review_history",
        lambda target: get_review_history(coordinator.duckdb, target=target),
    )
    server.register_tool(
        "get_symbol_context",
        lambda target: get_symbol_context(duckdb_store=coordinator.duckdb, target=target),
    )
    server.register_tool(
        "find_symbols",
        lambda query, limit=10: find_symbols(coordinator.duckdb, query=query, limit=limit),
    )
    server.register_tool(
        "get_callers_and_callees",
        lambda target: get_callers_and_callees(coordinator.kuzu, target=target),
    )
    server.register_tool(
        "get_graph_neighborhood",
        lambda target, depth=1: get_graph_neighborhood(coordinator.kuzu, target=target, depth=depth),
    )
    server.register_tool(
        "get_file_summary",
        lambda target: get_file_summary(coordinator.duckdb, target=target),
    )
    server.register_tool(
        "get_source_context",
        lambda target, limit=5: get_source_context(coordinator.duckdb, target=target, limit=limit),
    )
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
