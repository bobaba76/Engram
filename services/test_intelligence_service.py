from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.detect_changes_service import detect_changes
from services.symbol_resolution_service import resolve_candidates

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


__test__ = False

TEST_PATH_MARKERS = ("/test", "/tests/", "test_", "_test.", ".test.", ".spec.")

SUBSYSTEM_TEST_MAP = (
    (("indexing/parsers/",), ("tests/test_parser_registry.py", "tests/test_graph_builder.py")),
    (("indexing/graph_builder.py",), ("tests/test_graph_builder.py",)),
    (("storage/kuzu_store.py", "storage/duckdb_store.py"), ("tests/test_graph_builder.py", "tests/test_graph_service.py")),
    (("services/api_impact_service.py",), ("tests/test_api_impact_service.py",)),
    (("services/shape_check_service.py",), ("tests/test_shape_check_service.py",)),
    (("services/route_map_service.py", "services/route_parsing.py"), ("tests/test_route_map_service.py", "tests/test_shape_check_service.py")),
    (("services/process_service.py",), ("tests/test_process_service.py",)),
    (("services/change_report_service.py", "services/detect_changes_service.py"), ("tests/test_impact_change_frontend_signal.py",)),
    (("services/test_intelligence_service.py",), ("tests/test_test_intelligence_service.py",)),
    (("mcp_server/formatters.py",), ("tests/test_mcp_formatters.py",)),
    (("scripts/run_mcp.py",), ("tests/test_mcp_formatters.py", "tests/test_impact_change_frontend_signal.py")),
)


def _is_test_path(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/").lower()
    return any(marker in normalized for marker in TEST_PATH_MARKERS)


def _tokens(value: str) -> set[str]:
    normalized = value.replace("\\", "/").replace("_", " ").replace("-", " ").replace(".", " ").lower()
    return {token for token in normalized.split() if len(token) >= 3}


def _rank_tests(target_tokens: set[str], rows: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    ranked = []
    for row in rows:
        file_path = str(row.get("file_path") or row.get("path") or "")
        qualified = str(row.get("qualified_name") or row.get("name") or "")
        overlap = len(target_tokens & (_tokens(file_path) | _tokens(qualified)))
        score = overlap + (2 if _is_test_path(file_path) else 0)
        ranked.append({**row, "score": score, "token_overlap": overlap})
    ranked.sort(key=lambda item: (int(item.get("score", 0)), str(item.get("file_path") or item.get("path") or "")), reverse=True)
    return ranked[:limit]


def _keep_relevant_tests(rows: list[dict[str, object]], fallback_limit: int) -> list[dict[str, object]]:
    relevant = [
        row
        for row in rows
        if int(row.get("token_overlap", 0) or 0) >= 2 or int(row.get("score", 0) or 0) > 3
    ]
    return relevant


def _indexed_test_paths(duckdb_store: DuckDBStore) -> set[str]:
    paths: set[str] = set()
    try:
        file_rows = duckdb_store.files.fetch_all()
    except Exception:
        return paths
    for row in file_rows:
        path = str(row.get("path", "") if isinstance(row, dict) else "")
        if _is_test_path(path):
            paths.add(path.replace("\\", "/"))
    return paths


def _mapped_tests_for_seed(duckdb_store: DuckDBStore, seed_values: list[str]) -> list[dict[str, object]]:
    indexed_paths = _indexed_test_paths(duckdb_store)
    seed_text = " ".join(value.replace("\\", "/").lower() for value in seed_values if value)
    mapped: list[dict[str, object]] = []
    for source_markers, test_paths in SUBSYSTEM_TEST_MAP:
        if not any(marker in seed_text for marker in source_markers):
            continue
        for test_path in test_paths:
            if indexed_paths and test_path not in indexed_paths:
                continue
            mapped.append(
                {
                    "file_path": test_path,
                    "name": Path(test_path).stem,
                    "qualified_name": Path(test_path).stem,
                    "kind": "test_file",
                    "score": 10,
                    "token_overlap": 2,
                    "why_relevant": "mapped Coder subsystem coverage",
                }
            )
    unique: dict[str, dict[str, object]] = {}
    for row in mapped:
        unique[str(row["file_path"])] = row
    return list(unique.values())


def find_tests_for_target(duckdb_store: DuckDBStore, target: str, limit: int = 10) -> dict[str, object]:
    candidates = resolve_candidates(duckdb_store, target=target, limit=5)
    target_files = []
    target_symbols = []
    for item in candidates:
        symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
        file_path = str(symbol.get("file_path", "") or "")
        qualified = str(symbol.get("qualified_name", "") or symbol.get("name", "") or "")
        if file_path and file_path not in target_files:
            target_files.append(file_path)
        if qualified:
            target_symbols.append(qualified)
    seed = " ".join([target, *target_files, *target_symbols])
    seed_tokens = _tokens(seed)
    test_symbols = []
    for row in duckdb_store.symbols.fetch_for_target(target, limit=max(limit * 12, 60)):
        if _is_test_path(str(row.get("file_path", ""))):
            test_symbols.append(row)
    for file_row in duckdb_store.files.fetch_all():
        path = str(file_row.get("path", ""))
        if _is_test_path(path):
            test_symbols.append({"file_path": path, "name": Path(path).name, "qualified_name": Path(path).stem, "kind": "test_file"})
    mapped_tests = _mapped_tests_for_seed(duckdb_store, [target, *target_files, *target_symbols])
    ranked_tests = _keep_relevant_tests(_rank_tests(seed_tokens, test_symbols, limit=limit), fallback_limit=0)
    tests_by_file: dict[str, dict[str, object]] = {}
    for item in [*mapped_tests, *ranked_tests]:
        file_path = str(item.get("file_path", "") or item.get("file", "") or "")
        if file_path and file_path not in tests_by_file:
            tests_by_file[file_path] = item
    tests = list(tests_by_file.values())[:limit]
    warnings = [] if tests else [f"No focused tests found for {target}."]
    next_tools = [] if tests else [
        {
            "tool": "get_file_summary",
            "target": target,
            "why": "Inspect indexed symbols for the target before adding or selecting coverage.",
        },
        {
            "tool": "get_source_context",
            "target": target,
            "why": "Review the changed source to decide what focused coverage is needed.",
        },
    ]
    return {
        "target": target,
        "resolved_targets": target_symbols,
        "test_candidates": tests,
        "compact_results": [
            {
                "target": item.get("qualified_name") or item.get("name") or item.get("file_path"),
                "file": item.get("file_path"),
                "kind": item.get("kind", "test"),
                "score": item.get("score", 0),
                "why_relevant": str(item.get("why_relevant") or f"test path with {item.get('token_overlap', 0)} target token overlaps"),
            }
            for item in tests
        ],
        "warnings": warnings,
        "next_tools": next_tools,
        "compact_summary": {
            "target": target,
            "test_count": len(tests),
            "top_files": [item.get("file_path", "") for item in tests[:8]],
            "top_symbols": [item.get("qualified_name") or item.get("name") for item in tests[:8]],
            "warnings": warnings,
            "next_tools": next_tools,
        },
    }


def suggest_tests_for_change(repo_root: Path, duckdb_store: DuckDBStore, kuzu_store: KuzuStore, scope: str = "unstaged", base_ref: str = "", changes: dict[str, object] | None = None) -> dict[str, object]:
    changes = changes or detect_changes(repo_root, duckdb_store, kuzu_store, scope=scope, base_ref=base_ref or None)
    targets = []
    for symbol in changes.get("changed_symbols", []) if isinstance(changes, dict) else []:
        if isinstance(symbol, dict):
            target = str(symbol.get("qualified_name") or symbol.get("name") or "")
            if target:
                targets.append(target)
    if not targets:
        targets = [str(path) for path in changes.get("changed_files", [])[:5]] if isinstance(changes, dict) else []
    merged: dict[str, dict[str, object]] = {}
    changed_files = [str(path) for path in changes.get("changed_files", []) if str(path)] if isinstance(changes, dict) and isinstance(changes.get("changed_files", []), list) else []
    mapped_files: set[str] = set()
    for item in _mapped_tests_for_seed(duckdb_store, changed_files):
        file_path = str(item.get("file_path", "") or "")
        if file_path:
            mapped_files.add(file_path)
            merged[file_path] = {
                "target": item.get("qualified_name") or item.get("name") or file_path,
                "file": file_path,
                "kind": item.get("kind", "test_file"),
                "score": item.get("score", 10),
                "why_relevant": item.get("why_relevant", "mapped Coder subsystem coverage"),
            }
    for target in targets[:8]:
        tests = find_tests_for_target(duckdb_store, target, limit=8)
        for item in tests.get("compact_results", []):
            if isinstance(item, dict) and item.get("file"):
                file_path = str(item["file"])
                score = int(item.get("score", 0) or 0)
                why = str(item.get("why_relevant", "") or "")
                if mapped_files and file_path not in mapped_files and score < 8 and "mapped" not in why:
                    continue
                merged[file_path] = item
    selected = list(merged.values())[:12]
    selected = _keep_relevant_tests(selected, fallback_limit=5)[:12]
    return {
        "scope": scope,
        "base_ref": base_ref,
        "changes": changes,
        "recommended_tests": selected,
        "compact_results": selected,
        "compact_summary": {
            "target": str(
                changes.get("focused_target")
                or changes.get("compact_summary", {}).get("target")
                or f"{scope} changes"
            ) if isinstance(changes, dict) else f"{scope} changes",
            "changed_file_count": changes.get("compact_summary", {}).get("changed_file_count", 0) if isinstance(changes, dict) else 0,
            "test_count": len(selected),
            "top_files": [item.get("file", "") for item in selected[:8]],
        },
    }


def test_impact(repo_root: Path, duckdb_store: DuckDBStore, kuzu_store: KuzuStore, scope: str = "unstaged", base_ref: str = "") -> dict[str, object]:
    suggestions = suggest_tests_for_change(repo_root, duckdb_store, kuzu_store, scope=scope, base_ref=base_ref)
    changes = suggestions.get("changes", {}) if isinstance(suggestions, dict) else {}
    summary = changes.get("compact_summary", {}) if isinstance(changes, dict) else {}
    risk = summary.get("risk", "LOW") if isinstance(summary, dict) else "LOW"
    tests = suggestions.get("recommended_tests", [])
    risk_note = "No direct tests found; add focused coverage before merging." if not tests else "Run the recommended tests first."
    return {
        "scope": scope,
        "base_ref": base_ref,
        "risk": risk,
        "recommended_tests": tests,
        "testing_notes": [risk_note, "Add integration coverage if changed files touch routes, repositories, or process orchestration."],
        "compact_results": tests,
        "compact_summary": {
            "target": f"{scope} test impact",
            "risk": risk,
            "test_count": len(tests) if isinstance(tests, list) else 0,
            "top_files": [item.get("file", "") for item in tests[:8]] if isinstance(tests, list) else [],
        },
    }
