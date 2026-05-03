import sys
import io

if sys.platform == "win32":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import load_settings
from mcp_server.formatters import enrich_payload
from mcp_server.resolvers import resolve_tool_target
from services.app_context_service import app_context
from services.change_report_service import change_impact_report
from services.feature_context_service import feature_context
from services.impact_service import analyze_impact
from services.index_health_service import index_health
from services.investigation_service import investigate_codebase
from services.semantic_search import semantic_code_search
from services.source_retrieval_service import get_source_context
from services.test_intelligence_service import find_tests_for_target, suggest_tests_for_change, test_impact
from services.unified_context_service import get_unified_context
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from storage.vector_store import VectorStore


CaseFn = Callable[[], dict[str, object]]


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _print_case(name: str, payload: dict[str, object]) -> None:
    print(f"=== {name} ===")
    summary_text = str(payload.get("summary_text", "") or "")
    if summary_text:
        print(summary_text[:1600])
    else:
        print("<no summary>")
    print()


def _validate_summary(payload: dict[str, object], *, max_lines: int = 16) -> None:
    summary_text = str(payload.get("summary_text", "") or "")
    _assert(bool(summary_text.strip()), "expected non-empty summary_text")
    _assert("JSON:" not in summary_text, "summary_text should not include JSON marker")
    _assert(len(summary_text.splitlines()) <= max_lines, f"summary_text too large ({len(summary_text.splitlines())} lines)")


def main() -> int:
    repo_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT
    settings = load_settings(repo_root)
    duckdb_store = DuckDBStore(settings.duckdb_path, read_only=True)
    kuzu_store = KuzuStore(settings.kuzu_path, read_only=True)
    vector_store = VectorStore(settings.lancedb_path)
    failures: list[str] = []

    cases: list[tuple[str, CaseFn, Callable[[dict[str, object]], None]]] = [
        (
            "resolve_target",
            lambda: resolve_tool_target(duckdb_store, repo_root, target="Coordinator.run", limit=5),
            lambda payload: (
                _validate_summary(payload),
                _assert(payload.get("status") in {"found", "ambiguous"}, "resolve_target should find Coordinator.run"),
                _assert(len(payload.get("matches", [])) >= 1, "resolve_target should return matches"),
            ),
        ),
        (
            "get_source_context",
            lambda: get_source_context(duckdb_store, "Coordinator.run", limit=3, repo_root=repo_root),
            lambda payload: (
                _validate_summary(payload),
                _assert(len(payload.get("symbol_matches", [])) >= 1, "get_source_context should resolve a symbol"),
                _assert(len(payload.get("snippet_results", [])) >= 1, "get_source_context should return snippets"),
            ),
        ),
        (
            "semantic_code_search",
            lambda: semantic_code_search(
                vector_store,
                task="where is repo selection for MCP handled",
                model_name=settings.embedding_model,
                duckdb_store=duckdb_store,
                kuzu_store=kuzu_store,
                limit=5,
                max_length=settings.embedding_max_length,
                device=settings.embedding_device,
                provider_name=settings.embedding_provider,
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
            ),
            lambda payload: (
                _validate_summary(payload),
                _assert(len(payload.get("compact_results", [])) >= 1, "semantic_code_search should return at least one result"),
            ),
        ),
        (
            "app_context",
            lambda: app_context(repo_root, duckdb_store, kuzu_store, target="Coordinator.run", limit=8),
            lambda payload: (
                _validate_summary(payload),
                _assert("compact_summary" in payload, "app_context should include compact_summary"),
            ),
        ),
        (
            "unified_context",
            lambda: get_unified_context(duckdb_store, kuzu_store, target="Coordinator.run", max_matches=5, neighborhood_depth=1),
            lambda payload: (
                _validate_summary(payload),
                _assert(payload.get("status") in {"found", "ambiguous"}, "unified_context should resolve the symbol"),
                _assert(len(payload.get("matches", [])) >= 1, "unified_context should return matches"),
            ),
        ),
        (
            "impact_analysis",
            lambda: analyze_impact(duckdb_store, kuzu_store, target="Coordinator.run", direction="upstream", max_depth=2),
            lambda payload: (
                _validate_summary(payload),
                _assert(payload.get("status") in {"found", "ambiguous"}, "impact_analysis should resolve the symbol"),
                _assert(payload.get("risk") in {"LOW", "MEDIUM", "HIGH"}, "impact_analysis should report a known risk"),
            ),
        ),
        (
            "investigate_codebase",
            lambda: investigate_codebase(
                repo_root,
                duckdb_store,
                kuzu_store,
                question="where is MCP repo selection handled",
                search_payload=semantic_code_search(
                    vector_store,
                    task="where is MCP repo selection handled",
                    model_name=settings.embedding_model,
                    duckdb_store=duckdb_store,
                    kuzu_store=kuzu_store,
                    limit=3,
                    max_length=settings.embedding_max_length,
                    device=settings.embedding_device,
                    provider_name=settings.embedding_provider,
                    api_key=settings.embedding_api_key,
                    base_url=settings.embedding_base_url,
                ),
                limit=3,
            ),
            lambda payload: (
                _validate_summary(payload),
                _assert(len(payload.get("answer_outline", [])) >= 1, "investigate_codebase should return an answer outline"),
            ),
        ),
        (
            "feature_context",
            lambda: feature_context(repo_root, duckdb_store, kuzu_store, feature="MCP repo selection", limit=6),
            lambda payload: (
                _validate_summary(payload),
                _assert("compact_summary" in payload, "feature_context should include compact_summary"),
            ),
        ),
        (
            "find_tests_for_target",
            lambda: find_tests_for_target(duckdb_store, target="Coordinator.run", limit=8),
            lambda payload: (
                _validate_summary(payload),
                _assert("test_candidates" in payload, "find_tests_for_target should include candidates"),
            ),
        ),
        (
            "suggest_tests_for_change",
            lambda: suggest_tests_for_change(repo_root, duckdb_store, kuzu_store, scope="unstaged"),
            lambda payload: (
                _validate_summary(payload),
                _assert("recommended_tests" in payload, "suggest_tests_for_change should include recommendations"),
            ),
        ),
        (
            "test_impact",
            lambda: test_impact(repo_root, duckdb_store, kuzu_store, scope="unstaged"),
            lambda payload: (
                _validate_summary(payload),
                _assert(payload.get("risk") in {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}, "test_impact should return risk"),
            ),
        ),
        (
            "change_impact_report",
            lambda: change_impact_report(repo_root, duckdb_store, kuzu_store, scope="unstaged", max_symbols=2),
            lambda payload: (
                _validate_summary(payload),
                _assert("changes" in payload, "change_impact_report should include changes"),
            ),
        ),
        (
            "index_health",
            lambda: index_health(repo_root, duckdb_store, kuzu_store),
            lambda payload: (
                _validate_summary(payload),
                _assert(payload.get("counts", {}).get("files", 0) >= 1, "index_health should report files"),
            ),
        ),
    ]

    try:
        for name, runner, validator in cases:
            try:
                payload = enrich_payload(runner())
                _print_case(name, payload)
                validator(payload)
            except Exception as exc:
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
                print(f"FAIL {name}: {type(exc).__name__}: {exc}\n")
    finally:
        duckdb_store.close()
        kuzu_store.close()

    if failures:
        print("Smoke failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("All MCP smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
