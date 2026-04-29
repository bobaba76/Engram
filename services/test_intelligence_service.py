from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.detect_changes_service import detect_changes
from services.symbol_resolution_service import resolve_candidates

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


TEST_PATH_MARKERS = ("/test", "/tests/", "test_", "_test.", ".test.", ".spec.")


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
    tests = _rank_tests(seed_tokens, test_symbols, limit=limit)
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
                "why_relevant": f"test path with {item.get('token_overlap', 0)} target token overlaps",
            }
            for item in tests
        ],
        "compact_summary": {
            "target": target,
            "test_count": len(tests),
            "top_files": [item.get("file_path", "") for item in tests[:8]],
            "top_symbols": [item.get("qualified_name") or item.get("name") for item in tests[:8]],
        },
    }


def suggest_tests_for_change(repo_root: Path, duckdb_store: DuckDBStore, kuzu_store: KuzuStore, scope: str = "unstaged", base_ref: str = "") -> dict[str, object]:
    changes = detect_changes(repo_root, duckdb_store, kuzu_store, scope=scope, base_ref=base_ref or None)
    targets = []
    for symbol in changes.get("changed_symbols", []) if isinstance(changes, dict) else []:
        if isinstance(symbol, dict):
            target = str(symbol.get("qualified_name") or symbol.get("name") or "")
            if target:
                targets.append(target)
    if not targets:
        targets = [str(path) for path in changes.get("changed_files", [])[:5]] if isinstance(changes, dict) else []
    merged: dict[str, dict[str, object]] = {}
    for target in targets[:8]:
        tests = find_tests_for_target(duckdb_store, target, limit=8)
        for item in tests.get("compact_results", []):
            if isinstance(item, dict) and item.get("file"):
                merged[str(item["file"])] = item
    selected = list(merged.values())[:12]
    return {
        "scope": scope,
        "base_ref": base_ref,
        "changes": changes,
        "recommended_tests": selected,
        "compact_results": selected,
        "compact_summary": {
            "target": f"{scope} changes",
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
