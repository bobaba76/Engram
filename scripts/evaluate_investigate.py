import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import load_settings
from mcp_server.formatters import enrich_payload
from services.investigation_service import (
    broad_lexical_search_terms,
    investigate_codebase,
    investigation_search_task,
    should_allow_broad_vector_fallback,
)
from services.semantic_search import semantic_code_search
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from storage.vector_store import VectorStore


def _load_cases(path: Path) -> list[dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_case(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    vector_store: VectorStore,
    settings,
    case: dict[str, object],
) -> dict[str, object]:
    question = str(case.get("question", "") or "").strip()
    task, plan = investigation_search_task(question, limit=5)
    broad_question = bool(plan.get("guardrails", {}).get("broad_question"))
    lexical_terms = broad_lexical_search_terms(task, plan.get("query_rewrite", {}), limit=4) if broad_question else [task]
    search_payload = semantic_code_search(
        vector_store,
        task=task,
        model_name=settings.embedding_model,
        duckdb_store=duckdb_store,
        kuzu_store=kuzu_store,
        limit=int(plan.get("guardrails", {}).get("search_limit", 5) or 5),
        max_length=settings.embedding_max_length,
        device=settings.embedding_device,
        provider_name=settings.embedding_provider,
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        include_vector=not broad_question,
        include_graph=not broad_question,
        include_expansion=not broad_question,
        max_variants=1 if broad_question else 3,
        extra_query_terms=lexical_terms,
    )
    if broad_question and isinstance(search_payload, dict) and not search_payload.get("compact_results") and should_allow_broad_vector_fallback(task, plan.get("query_rewrite", {})):
        search_payload = semantic_code_search(
            vector_store,
            task=task,
            model_name=settings.embedding_model,
            duckdb_store=duckdb_store,
            kuzu_store=kuzu_store,
            limit=int(plan.get("guardrails", {}).get("search_limit", 5) or 5),
            max_length=settings.embedding_max_length,
            device=settings.embedding_device,
            provider_name=settings.embedding_provider,
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            include_vector=True,
            include_graph=False,
            include_expansion=False,
            max_variants=1,
            extra_query_terms=lexical_terms,
        )

    started = perf_counter()
    payload = enrich_payload(investigate_codebase(repo_root, duckdb_store, kuzu_store, question=question, search_payload=search_payload, limit=5))
    elapsed = perf_counter() - started

    top_files = payload.get("top_files", []) if isinstance(payload.get("top_files", []), list) else []
    next_tool_names = [str(item.get("tool", "")) for item in payload.get("next_tools", []) if isinstance(item, dict)]
    score = 0
    checks: list[str] = []

    max_seconds = float(case.get("max_seconds", 2.0) or 2.0)
    if elapsed <= max_seconds:
        score += 1
        checks.append("latency")

    expected_target = str(case.get("expect_target_contains", "") or "").strip()
    if not expected_target or expected_target.lower() in str(payload.get("target", "") or "").lower():
        score += 1
        checks.append("target")

    expected_file = str(case.get("expect_top_file_contains", "") or "").strip()
    expected_any_files = case.get("expect_any_top_file_contains", [])
    if expected_file and any(expected_file.lower() in str(file_path).lower() for file_path in top_files[:3]):
        score += 1
        checks.append("top_file")
    elif isinstance(expected_any_files, list) and expected_any_files and any(
            any(str(expected).lower() in str(file_path).lower() for file_path in top_files[:4])
            for expected in expected_any_files
    ):
        score += 1
        checks.append("top_file")
    elif not expected_file and (not isinstance(expected_any_files, list) or not expected_any_files):
        score += 1
        checks.append("top_file")

    expected_tools = case.get("expect_next_tools", [])
    if not isinstance(expected_tools, list):
        expected_tools = []
    expected_any_tools = case.get("expect_any_next_tools", [])
    if expected_tools and all(tool in next_tool_names for tool in expected_tools):
        score += 1
        checks.append("next_tools")
    elif isinstance(expected_any_tools, list) and expected_any_tools and any(tool in next_tool_names for tool in expected_any_tools):
        score += 1
        checks.append("next_tools")
    elif not expected_tools and (not isinstance(expected_any_tools, list) or not expected_any_tools):
        score += 1
        checks.append("next_tools")

    expected_partial = case.get("expect_partial")
    if expected_partial is None or bool(payload.get("partial")) is bool(expected_partial):
        score += 1
        checks.append("partial")

    return {
        "question": question,
        "elapsed_seconds": round(elapsed, 4),
        "score": score,
        "max_score": 5,
        "checks": checks,
        "target": payload.get("target", ""),
        "top_files": top_files[:3],
        "next_tools": next_tool_names[:5],
        "partial": payload.get("partial"),
        "confidence": payload.get("confidence"),
    }


def main() -> int:
    repo_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT
    cases_path = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else repo_root / "scripts" / "investigate_eval_cases.json"
    settings = load_settings(repo_root)
    duckdb_store = DuckDBStore(settings.duckdb_path, read_only=True)
    kuzu_store = KuzuStore(settings.kuzu_path, read_only=True)
    vector_store = VectorStore(settings.lancedb_path)

    try:
        cases = _load_cases(cases_path)
        reports = [_run_case(repo_root, duckdb_store, kuzu_store, vector_store, settings, case) for case in cases]
    finally:
        duckdb_store.close()
        kuzu_store.close()

    total_score = sum(int(report["score"]) for report in reports)
    max_score = sum(int(report["max_score"]) for report in reports)
    print(json.dumps({"total_score": total_score, "max_score": max_score, "cases": reports}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
