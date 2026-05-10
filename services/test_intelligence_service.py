from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from services.detect_changes_service import detect_changes
from services.symbol_resolution_service import resolve_candidates

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


__test__ = False

TEST_PATH_MARKERS = ("/test", "/tests/", ".test/", ".tests/", "test_", "_test.", ".test.", ".tests.", ".spec.")

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


def _csharp_test_name_variants(file_path: str, qualified: str = "") -> set[str]:
    normalized = str(file_path or "").replace("\\", "/")
    stem = Path(normalized).stem
    names = {stem}
    for suffix in ("Controller", "Service", "Repository", "Dto", "Request", "Response"):
        if stem.endswith(suffix):
            names.add(stem[: -len(suffix)])
    if qualified:
        tail = str(qualified).replace("::", ".").rsplit(".", 1)[-1]
        if tail:
            names.add(tail)
    variants: set[str] = set()
    for name in names:
        if not name:
            continue
        variants.add(name)
        variants.add(f"{name}Tests")
        variants.add(f"{name}Test")
        variants.add(f"{name}Specs")
    return {variant.lower() for variant in variants if variant}


def _native_test_name_variants(file_path: str, qualified: str = "") -> set[str]:
    normalized = str(file_path or "").replace("\\", "/")
    stem = Path(normalized).stem
    names = {stem}
    if qualified:
        tail = str(qualified).replace("::", ".").rsplit(".", 1)[-1]
        if tail:
            names.add(tail)
    variants: set[str] = set()
    for name in names:
        if not name:
            continue
        variants.update(
            {
                name,
                f"test_{name}",
                f"{name}_test",
                f"{name}_tests",
                f"{name}Test",
                f"{name}Tests",
                f"{name}_spec",
            }
        )
    return {variant.lower() for variant in variants if variant}


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


def _csharp_convention_tests(duckdb_store: DuckDBStore, target_files: list[str], target_symbols: list[str]) -> list[dict[str, object]]:
    indexed_paths = _indexed_test_paths(duckdb_store)
    if not indexed_paths:
        return []
    variants: set[str] = set()
    for index, file_path in enumerate(target_files):
        variants.update(_csharp_test_name_variants(file_path, target_symbols[index] if index < len(target_symbols) else ""))
    mapped: list[dict[str, object]] = []
    for path in indexed_paths:
        if not path.lower().endswith(".cs"):
            continue
        stem = Path(path).stem.lower()
        if stem not in variants:
            continue
        mapped.append(
            {
                "file_path": path,
                "name": Path(path).stem,
                "qualified_name": Path(path).stem,
                "kind": "test_file",
                "score": 9,
                "token_overlap": 2,
                "why_relevant": "C# test naming convention match",
            }
        )
    return sorted(mapped, key=lambda item: str(item["file_path"]))


def _native_convention_tests(duckdb_store: DuckDBStore, target_files: list[str], target_symbols: list[str]) -> list[dict[str, object]]:
    indexed_paths = _indexed_test_paths(duckdb_store)
    if not indexed_paths:
        return []
    variants: set[str] = set()
    for index, file_path in enumerate(target_files):
        if not str(file_path).lower().endswith((".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx")):
            continue
        variants.update(_native_test_name_variants(file_path, target_symbols[index] if index < len(target_symbols) else ""))
    mapped: list[dict[str, object]] = []
    for path in indexed_paths:
        if not path.lower().endswith((".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx")):
            continue
        stem = Path(path).stem.lower()
        if stem not in variants:
            continue
        mapped.append(
            {
                "file_path": path,
                "name": Path(path).stem,
                "qualified_name": Path(path).stem,
                "kind": "test_file",
                "score": 8,
                "token_overlap": 2,
                "why_relevant": "C/C++ test naming convention match",
            }
        )
    return sorted(mapped, key=lambda item: str(item["file_path"]))


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


def _indexed_paths(duckdb_store: DuckDBStore) -> set[str]:
    paths: set[str] = set()
    try:
        file_rows = duckdb_store.files.fetch_all()
    except Exception:
        return paths
    for row in file_rows:
        path = str(row.get("path", "") if isinstance(row, dict) else "")
        if path:
            paths.add(path.replace("\\", "/"))
    return paths


def _nearest_project(file_path: str, project_paths: set[str]) -> str:
    normalized = str(file_path or "").replace("\\", "/")
    candidates = [
        project
        for project in project_paths
        if normalized.startswith(str(Path(project).parent).replace("\\", "/").rstrip("/") + "/")
    ]
    candidates.sort(key=lambda item: len(str(Path(item).parent).replace("\\", "/")), reverse=True)
    return candidates[0] if candidates else ""


def _project_references(duckdb_store: DuckDBStore, project_path: str) -> set[str]:
    try:
        symbols = duckdb_store.fetch_symbols_for_file(project_path)
    except Exception:
        return set()
    references: set[str] = set()
    for symbol in symbols:
        metadata = symbol.get("metadata") if isinstance(symbol, dict) else {}
        if not isinstance(metadata, dict):
            raw_json = str(symbol.get("metadata_json", "") if isinstance(symbol, dict) else "" or "").strip()
            try:
                metadata = json.loads(raw_json) if raw_json else {}
            except json.JSONDecodeError:
                metadata = {}
        raw_refs = metadata.get("project_references", []) if isinstance(metadata, dict) else []
        if isinstance(raw_refs, list):
            references.update(str(item).replace("\\", "/") for item in raw_refs if str(item).strip())
    project_dir = str(Path(project_path).parent).replace("\\", "/")
    normalized: set[str] = set()
    for ref in references:
        ref_path = Path(project_dir) / ref
        normalized.add(str(ref_path).replace("\\", "/"))
        normalized.add(ref)
        normalized.add(Path(ref).name)
    return normalized


def _project_references_source(test_project: str, source_project: str, references: set[str]) -> bool:
    if not references:
        return False
    source_normalized = str(source_project).replace("\\", "/")
    source_name = Path(source_normalized).name
    test_dir = str(Path(test_project).parent).replace("\\", "/")
    candidates = {
        source_normalized,
        source_name,
        str(Path(test_dir) / source_normalized).replace("\\", "/"),
    }
    return bool(candidates & references)


def _csharp_project_tests(duckdb_store: DuckDBStore, target_files: list[str], target_symbols: list[str]) -> list[dict[str, object]]:
    indexed_paths = _indexed_paths(duckdb_store)
    project_paths = {path for path in indexed_paths if path.lower().endswith(".csproj")}
    if not project_paths:
        return []
    mapped: list[dict[str, object]] = []
    test_project_paths = {
        project
        for project in project_paths
        if _is_test_path(project) or Path(project).stem.lower().endswith(("tests", "test", "specs"))
    }
    for index, file_path in enumerate(target_files):
        if not str(file_path).lower().endswith(".cs"):
            continue
        source_project = _nearest_project(file_path, project_paths - test_project_paths)
        if not source_project:
            continue
        source_name = Path(source_project).stem.lower()
        variants = _csharp_test_name_variants(file_path, target_symbols[index] if index < len(target_symbols) else "")
        for test_project in test_project_paths:
            test_name = Path(test_project).stem.lower()
            references = _project_references(duckdb_store, test_project)
            explicit_reference = _project_references_source(test_project, source_project, references)
            if source_name and source_name not in test_name and not explicit_reference:
                continue
            test_root = str(Path(test_project).parent).replace("\\", "/").rstrip("/")
            for path in sorted(indexed_paths):
                if not path.lower().endswith(".cs") or not path.startswith(test_root + "/"):
                    continue
                stem = Path(path).stem.lower()
                if stem not in variants:
                    continue
                mapped.append(
                    {
                        "file_path": path,
                        "name": Path(path).stem,
                        "qualified_name": Path(path).stem,
                        "kind": "test_file",
                        "score": 11 if explicit_reference else 10,
                        "token_overlap": 2,
                        "why_relevant": "C# explicit ProjectReference test match" if explicit_reference else "C# project test reference match",
                    }
                )
    unique: dict[str, dict[str, object]] = {}
    for row in mapped:
        unique[str(row["file_path"])] = row
    return list(unique.values())


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
    csharp_project_tests = _csharp_project_tests(duckdb_store, target_files, target_symbols)
    csharp_tests = [] if csharp_project_tests else _csharp_convention_tests(duckdb_store, target_files, target_symbols)
    native_tests = _native_convention_tests(duckdb_store, target_files, target_symbols)
    ranked_tests = _keep_relevant_tests(_rank_tests(seed_tokens, test_symbols, limit=limit), fallback_limit=0)
    tests_by_file: dict[str, dict[str, object]] = {}
    for item in [*mapped_tests, *csharp_project_tests, *csharp_tests, *native_tests, *ranked_tests]:
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
