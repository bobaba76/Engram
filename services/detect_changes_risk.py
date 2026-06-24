"""Risk assessment helpers for change detection."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
from services.risk_profiles import (
    embedded_sensitive_path_hints,
    high_risk_path_hints,
    high_risk_symbol_hints,
    path_risk_hints,
)


def _normalized_scope(scope: str) -> str:
    return scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"


def _risk_scope(scope: str) -> str:
    normalized = _normalized_scope(scope)
    if normalized == "staged":
        return "staged_index"
    if normalized == "all":
        return "staged_and_unstaged_working_tree"
    if normalized == "compare":
        return "comparison_range"
    return "unstaged_working_tree"


def _risk_applies_to(scope: str, base_ref: str | None) -> list[str]:
    normalized = _normalized_scope(scope)
    if normalized == "staged":
        return ["all staged changes"]
    if normalized == "all":
        return ["all staged changes", "all unstaged changes"]
    if normalized == "compare":
        compare_ref = (base_ref or "HEAD").strip() or "HEAD"
        return [f"changes from {compare_ref} to HEAD"]
    return ["all unstaged changes"]


def _diff_command_equivalent(scope: str, base_ref: str | None) -> str:
    normalized = _normalized_scope(scope)
    if normalized == "staged":
        return "git diff --cached --"
    if normalized == "all":
        return "git diff --cached -- && git diff --"
    if normalized == "compare":
        compare_ref = (base_ref or "HEAD").strip() or "HEAD"
        return f"git diff {compare_ref}...HEAD --"
    return "git diff --"


def _symbol_metadata(symbol: dict[str, object]) -> dict[str, object]:
    raw = symbol.get("metadata")
    if isinstance(raw, dict):
        return raw
    raw_json = str(symbol.get("metadata_json", "") or "").strip()
    if not raw_json:
        return {}
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _symbols_for_changed_lines(duckdb_store: DuckDBStore, file_path: str, changed_lines: set[int]) -> list[dict[str, object]]:
    symbols = []
    for symbol in duckdb_store.fetch_symbols_for_file(file_path):
        start = int(symbol.get("start_line") or 0)
        end = int(symbol.get("end_line") or start)
        if any(start <= line <= end for line in changed_lines):
            metadata = _symbol_metadata(symbol)
            build_context = metadata.get("build_context", {}) if isinstance(metadata.get("build_context", {}), dict) else {}
            symbols.append(
                {
                    "qualified_name": symbol.get("qualified_name", ""),
                    "name": symbol.get("name", ""),
                    "kind": symbol.get("kind", ""),
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                    "metadata": metadata,
                    "native_build_target": build_context.get("target", ""),
                    "native_build_confidence": build_context.get("confidence", ""),
                }
            )
    return symbols


def _symbol_risk_hints(file_path: str, symbols: list[dict[str, object]]) -> list[str]:
    normalized = str(file_path or "").replace("\\", "/").lower()
    hints: list[str] = []
    is_native_header = normalized.endswith((".h", ".hh", ".hpp", ".hxx"))
    native_public_kinds = {"type", "typedef", "class", "macro", "constant"}
    if is_native_header and any(str(symbol.get("kind", "")).lower() in native_public_kinds for symbol in symbols):
        hints.append("native ABI/layout surface symbol")
    if any(bool(symbol.get("metadata", {}).get("is_exported")) for symbol in symbols if isinstance(symbol.get("metadata", {}), dict)):
        hints.append("native exported symbol")
    abi_surfaces = sorted({
        str(symbol.get("metadata", {}).get("abi_surface", "") or "")
        for symbol in symbols
        if isinstance(symbol.get("metadata", {}), dict) and str(symbol.get("metadata", {}).get("abi_surface", "") or "")
    })
    if abi_surfaces:
        hints.append(f"native ABI surface kind(s): {', '.join(abi_surfaces[:3])}")
    layout_fields = sorted({
        field
        for symbol in symbols
        if isinstance(symbol.get("metadata", {}), dict)
        for field in symbol.get("metadata", {}).get("layout_fields", [])
        if str(field)
    })
    if layout_fields:
        hints.append(f"native layout field(s): {', '.join(layout_fields[:5])}")
    native_targets = sorted({str(symbol.get("native_build_target", "") or "") for symbol in symbols if str(symbol.get("native_build_target", "") or "")})
    if native_targets:
        hints.append(f"native build target(s): {', '.join(native_targets[:3])}")
    if any(bool(symbol.get("metadata", {}).get("public_dependency_surface")) for symbol in symbols if isinstance(symbol.get("metadata", {}), dict)):
        hints.append("Object Pascal public unit dependency surface")
    if any(bool(symbol.get("metadata", {}).get("project_ownership_surface")) for symbol in symbols if isinstance(symbol.get("metadata", {}), dict)):
        hints.append("Object Pascal project ownership surface")
    if any(bool(symbol.get("metadata", {}).get("include_files")) for symbol in symbols if isinstance(symbol.get("metadata", {}), dict)):
        hints.append("Object Pascal include dependency surface")
    if any(bool(symbol.get("metadata", {}).get("conditional_symbols")) for symbol in symbols if isinstance(symbol.get("metadata", {}), dict)):
        hints.append("Object Pascal conditional compilation surface")
    return hints


def _path_risk_hints(file_path: str) -> list[str]:
    return path_risk_hints(file_path)


def _file_risk(file_path: str, changed_symbol_count: int, impacted: bool) -> str:
    hints = _path_risk_hints(file_path)
    if changed_symbol_count >= 8 or high_risk_path_hints(hints):
        return "HIGH"
    if changed_symbol_count >= 3 or impacted or hints:
        return "MEDIUM"
    return "LOW"


def _risk_by_file(changed_files: list[str], changed_symbols: list[dict[str, object]], impacted_files: list[str]) -> list[dict[str, object]]:
    symbols_by_file: dict[str, list[dict[str, object]]] = {}
    for symbol in changed_symbols:
        file_path = str(symbol.get("file_path", "") or "")
        if file_path:
            symbols_by_file.setdefault(file_path, []).append(symbol)
    impacted_set = set(impacted_files)
    rows = []
    for file_path in changed_files:
        file_symbols = symbols_by_file.get(file_path, [])
        risk_factors = [*_path_risk_hints(file_path), *_symbol_risk_hints(file_path, file_symbols)]
        file_risk = _file_risk(file_path, len(file_symbols), file_path in impacted_set)
        if high_risk_symbol_hints(risk_factors):
            file_risk = "HIGH"
        rows.append(
            {
                "file": file_path,
                "risk": file_risk,
                "changed_symbols": len(file_symbols),
                "impacted": file_path in impacted_set,
                "risk_factors": risk_factors,
                "native_build_targets": sorted({str(symbol.get("native_build_target", "") or "") for symbol in file_symbols if str(symbol.get("native_build_target", "") or "")}),
                "top_changed_symbols": [
                    symbol.get("qualified_name") or symbol.get("name") or ""
                    for symbol in file_symbols[:5]
                    if symbol.get("qualified_name") or symbol.get("name")
                ],
            }
        )
    return rows


def _risk_explanation(changed_files: list[str], changed_symbols: list[dict[str, object]], impacted_files: list[str], risk_by_file: list[dict[str, object]]) -> list[str]:
    reasons = [
        f"{len(changed_files)} files changed",
        f"{len(changed_symbols)} indexed symbols changed",
        f"{len(impacted_files)} graph-impacted files detected",
    ]
    high_risk_files = [row["file"] for row in risk_by_file if row.get("risk") == "HIGH"]
    medium_risk_files = [row["file"] for row in risk_by_file if row.get("risk") == "MEDIUM"]
    if high_risk_files:
        reasons.append(f"{len(high_risk_files)} changed files have high-risk characteristics")
    elif medium_risk_files:
        reasons.append(f"{len(medium_risk_files)} changed files have medium-risk characteristics")
    if len(changed_files) >= 25:
        reasons.append("25+ changed files escalates whole-tree risk")
    if len(changed_symbols) >= 100:
        reasons.append("100+ changed symbols escalates whole-tree risk")
    if len(impacted_files) >= 50:
        reasons.append("50+ impacted files indicates broad graph blast radius")
    embedded_files = [
        row["file"]
        for row in risk_by_file
        if embedded_sensitive_path_hints([str(factor) for factor in row.get("risk_factors", [])])
    ]
    if embedded_files:
        reasons.append(f"{len(embedded_files)} embedded-C sensitive file(s) changed")
    return reasons


def _overall_risk(changed_files: list[str], changed_symbols: list[dict[str, object]], impacted_files: list[str], risk_by_file: list[dict[str, object]]) -> str:
    if len(changed_files) >= 25 or len(changed_symbols) >= 100 or len(impacted_files) >= 50:
        return "CRITICAL"
    if any(row.get("risk") == "HIGH" for row in risk_by_file) or len(changed_symbols) >= 8 or len(impacted_files) >= 12:
        return "HIGH"
    if any(row.get("risk") == "MEDIUM" for row in risk_by_file) or len(changed_symbols) >= 3 or len(impacted_files) >= 5:
        return "MEDIUM"
    return "LOW"


def _weighted_risk(
    changed_files: list[str],
    changed_symbols: list[dict[str, object]],
    impacted_files: list[str],
    risk_by_file: list[dict[str, object]],
    route_summary: dict[str, object],
    process_summary: dict[str, object],
) -> dict[str, object]:
    score = 0
    factors: list[str] = []

    def add(points: int, reason: str) -> None:
        nonlocal score
        if points <= 0:
            return
        score += points
        factors.append(f"+{points}: {reason}")

    add(min(len(changed_files) * 2, 50), f"{len(changed_files)} changed file(s)")
    add(min(len(changed_symbols), 60), f"{len(changed_symbols)} changed symbol(s)")
    add(min(len(impacted_files) // 2, 40), f"{len(impacted_files)} graph-impacted file(s)")
    high_files = [row for row in risk_by_file if row.get("risk") == "HIGH"]
    medium_files = [row for row in risk_by_file if row.get("risk") == "MEDIUM"]
    embedded_sensitive = [
        row for row in risk_by_file
        if embedded_sensitive_path_hints([str(factor) for factor in row.get("risk_factors", [])])
    ]
    add(len(high_files) * 10, f"{len(high_files)} high-risk changed file(s)")
    add(len(medium_files) * 4, f"{len(medium_files)} medium-risk changed file(s)")
    add(len(embedded_sensitive) * 12, f"{len(embedded_sensitive)} embedded-C sensitive changed file(s)")
    changed_routes = route_summary.get("changed_routes", []) if isinstance(route_summary.get("changed_routes", []), list) else []
    affected_consumers = route_summary.get("affected_consumers", []) if isinstance(route_summary.get("affected_consumers", []), list) else []
    shape_mismatches = route_summary.get("shape_mismatches", []) if isinstance(route_summary.get("shape_mismatches", []), list) else []
    affected_processes = process_summary.get("affected_processes", []) if isinstance(process_summary.get("affected_processes", []), list) else []
    high_processes = [row for row in process_summary.get("risk_by_process", []) if isinstance(row, dict) and row.get("risk") == "HIGH"] if isinstance(process_summary.get("risk_by_process", []), list) else []
    add(len(changed_routes) * 12, f"{len(changed_routes)} changed route(s)")
    add(len(affected_consumers) * 5, f"{len(affected_consumers)} affected frontend/API consumer(s)")
    add(len(shape_mismatches) * 35, f"{len(shape_mismatches)} response-shape mismatch(es)")
    add(len(affected_processes) * 6, f"{len(affected_processes)} affected execution flow(s)")
    add(len(high_processes) * 10, f"{len(high_processes)} high-risk execution flow(s)")
    if score >= 100:
        label = "CRITICAL"
    elif score >= 55:
        label = "HIGH"
    elif score >= 20:
        label = "MEDIUM"
    else:
        label = "LOW"
    return {"score": score, "label": label, "factors": factors[:10]}


def _confidence(changed_files: list[str], changed_symbols: list[dict[str, object]], impacted_files: list[str], warnings: list[str]) -> dict[str, object]:
    if warnings:
        graph_limited = all("Graph blast-radius traversal skipped" in warning or "Process tracing skipped" in warning or "Process tracing was capped" in warning for warning in warnings)
        if graph_limited:
            return {"level": "medium", "why": ["git diff and symbol mapping were available; broad graph/process traversal was capped for responsiveness"]}
        return {"level": "low", "why": ["some git, graph, or process impact information was incomplete"]}
    if changed_files and not changed_symbols:
        return {"level": "low", "why": ["changed files did not map to indexed symbols"]}
    if changed_files and not impacted_files:
        return {"level": "medium", "why": ["changed symbols were detected, but graph impact was shallow or unavailable"]}
    return {"level": "high" if changed_symbols else "medium", "why": ["git diff, symbol mapping, and graph impact data were available"]}


def _focused_followups(file_risks: list[dict[str, object]], changed_symbols: list[dict[str, object]], warnings: list[str]) -> list[dict[str, str]]:
    followups: list[dict[str, str]] = []

    def add(tool: str, target: str, why: str) -> None:
        if not target:
            return
        item = {"tool": tool, "target": target, "why": why}
        if item not in followups:
            followups.append(item)

    capped = any("skipped" in warning.lower() or "capped" in warning.lower() for warning in warnings)
    high_files = [row for row in file_risks if isinstance(row, dict) and row.get("risk") in {"CRITICAL", "HIGH"}]
    first_high_file = str(high_files[0].get("file", "") if high_files else "")
    if capped and first_high_file:
        add("change_impact_report", first_high_file, "Run a focused report because broad graph/process traversal was capped.")
    for symbol in changed_symbols[:6]:
        if not isinstance(symbol, dict):
            continue
        name = str(symbol.get("qualified_name") or symbol.get("name") or "")
        file_path = str(symbol.get("file_path", "") or "")
        if name and file_path == first_high_file:
            add("trace_processes", name, "Trace execution flows for the highest-risk changed symbol.")
            break
    if first_high_file:
        add("find_tests_for_target", first_high_file, "Find focused tests for the highest-risk changed area.")
    return followups[:6]
