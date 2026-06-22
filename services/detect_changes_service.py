from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from services.api_impact_service import api_impact
from services.process_service import trace_execution_flows
from services.risk_profiles import (
    embedded_sensitive_path_hints,
    high_risk_path_hints,
    high_risk_symbol_hints,
    path_risk_hints,
)
from services.route_map_service import _backend_handlers, _direct_frontend_consumers, _read_text
from services.timeout_utils import run_with_timeout


HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@", re.MULTILINE)
BROAD_GRAPH_FILE_LIMIT = 20
BROAD_PROCESS_SYMBOL_LIMIT = 80
GRAPH_OPERATION_TIMEOUT_SECONDS = 1.5
ROUTE_OPERATION_TIMEOUT_SECONDS = 2.0
PROCESS_OPERATION_TIMEOUT_SECONDS = 2.0


def _run_git(repo_root: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _git_top_level(repo_root: Path) -> Path:
    output = _run_git(repo_root, ["rev-parse", "--show-toplevel"]).strip()
    return Path(output).resolve() if output else repo_root


def _normalize_status_path(repo_root: Path, git_top: Path, path: str) -> str:
    direct = repo_root / path
    if direct.exists():
        return path
    from_top = git_top / path
    try:
        return str(from_top.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return path


def _untracked_files(repo_root: Path) -> list[str]:
    output = _run_git(repo_root, ["status", "--porcelain=v1", "-uall", "--"])
    files: list[str] = []
    git_top = _git_top_level(repo_root)
    for line in output.splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip().strip('"').replace("\\", "/")
        if path:
            files.append(_normalize_status_path(repo_root, git_top, path))
    return sorted(dict.fromkeys(files))


def _synthetic_untracked_diff(repo_root: Path, files: list[str]) -> str:
    parts: list[str] = []
    for file_path in files:
        absolute = repo_root / file_path
        if not absolute.is_file():
            continue
        try:
            line_count = len(absolute.read_text(encoding="utf-8", errors="ignore").splitlines())
        except OSError:
            line_count = 1
        line_count = max(line_count, 1)
        parts.extend(
            [
                f"diff --git a/{file_path} b/{file_path}",
                "new file mode 100644",
                "index 0000000..0000000",
                "--- /dev/null",
                f"+++ b/{file_path}",
                f"@@ -0,0 +1,{line_count} @@",
            ]
        )
    return "\n".join(parts)


def _diff_output(repo_root: Path, scope: str, base_ref: str | None = None) -> str:
    normalized = scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"
    if normalized == "staged":
        return _run_git(repo_root, ["diff", "--cached", "--unified=0", "--no-color"])
    if normalized == "all":
        staged = _run_git(repo_root, ["diff", "--cached", "--unified=0", "--no-color"])
        unstaged = _run_git(repo_root, ["diff", "--unified=0", "--no-color"])
        untracked = _synthetic_untracked_diff(repo_root, _untracked_files(repo_root))
        return "\n".join(part for part in (staged, unstaged, untracked) if part.strip())
    if normalized == "compare":
        compare_ref = (base_ref or "HEAD").strip() or "HEAD"
        return _run_git(repo_root, ["diff", f"{compare_ref}...HEAD", "--unified=0", "--no-color"])
    unstaged = _run_git(repo_root, ["diff", "--unified=0", "--no-color"])
    untracked = _synthetic_untracked_diff(repo_root, _untracked_files(repo_root))
    return "\n".join(part for part in (unstaged, untracked) if part.strip())


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


def _parse_changed_lines(diff_text: str) -> dict[str, set[int]]:
    changed: dict[str, set[int]] = {}
    current_file = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            changed.setdefault(current_file, set())
            continue
        if not current_file:
            continue
        match = HUNK_PATTERN.match(line)
        if match is None:
            continue
        start = int(match.group("start"))
        count = int(match.group("count") or "1")
        if count == 0:
            continue
        changed[current_file].update(range(start, start + count))
    return changed


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


def _process_target_priority(symbol: dict[str, object]) -> tuple[int, int, int, int, str]:
    file_path = str(symbol.get("file_path", "") or "").replace("\\", "/").lower()
    name = str(symbol.get("qualified_name") or symbol.get("name") or "")
    tail = name.rsplit(".", 1)[-1].lower()
    span = int(symbol.get("end_line", 0) or 0) - int(symbol.get("start_line", 0) or 0)
    broad_wrapper = int(tail in {"main", "__init__"} or span > 180)
    service_area = int(file_path.startswith("services/") and "detect_changes_service.py" not in file_path)
    graph_area = int("impact" in file_path or "process" in file_path or "route" in file_path or "context" in file_path)
    runtime_kind = int(str(symbol.get("kind", "") or "").lower() in {"function", "method"})
    return (-broad_wrapper, service_area, graph_area, runtime_kind, name)


def _indexed_process_rows(duckdb_store: DuckDBStore, targets: list[dict[str, str]], changed_routes: list[str], limit: int = 12) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for item in targets[:12]:
        target = item["target"]
        aliases = [target, target.rsplit(".", 1)[-1]]
        for alias in aliases:
            for process in duckdb_store.fetch_process_clusters_for_symbol(alias, limit=4):
                name = str(process.get("name", "") or "")
                key = (name, target)
                if not name or key in seen:
                    continue
                seen.add(key)
                route_context = [route for route in changed_routes if route.replace("/", "_").strip("_").lower() in name.lower()]
                step_count = int(process.get("avg_step_count", 0) or process.get("step_count", 0) or 0)
                rows.append({
                    "name": name,
                    "target": target,
                    "entry_symbol": process.get("canonical_entry_symbol", ""),
                    "module": process.get("module_tags", []),
                    "steps": step_count,
                    "step_details": [],
                    "changed_symbol": target,
                    "changed_symbols": [target],
                    "changed_routes": route_context,
                    "risk": "MEDIUM" if step_count >= 4 else "LOW",
                    "risk_reasons": ["indexed process cluster includes changed symbol"],
                })
                if len(rows) >= limit:
                    return rows
    return rows


def _process_change_summary(duckdb_store: DuckDBStore, kuzu_store: KuzuStore, changed_symbols: list[dict[str, object]], changed_routes: list[str], warnings: list[str] | None = None) -> dict[str, object]:
    targets: list[dict[str, str]] = []
    ranked_symbols = sorted(
        [symbol for symbol in changed_symbols if isinstance(symbol, dict)],
        key=_process_target_priority,
        reverse=True,
    )
    for symbol in ranked_symbols[:10]:
        if not isinstance(symbol, dict):
            continue
        target = str(symbol.get("qualified_name") or symbol.get("name") or "")
        if not target:
            continue
        targets.append({
            "target": target,
            "file_path": str(symbol.get("file_path", "") or ""),
            "kind": str(symbol.get("kind", "") or ""),
        })
    seen = set()
    unique_targets = []
    for item in targets:
        key = (item["target"], item["file_path"], item["kind"])
        if key in seen:
            continue
        seen.add(key)
        unique_targets.append(item)
    affected_processes = []
    risk_by_process = []
    indexed_rows = _indexed_process_rows(duckdb_store, unique_targets, changed_routes, limit=12)
    affected_processes.extend(indexed_rows)
    for row in indexed_rows:
        risk_by_process.append({
            "name": row.get("name", ""),
            "risk": row.get("risk", "LOW"),
            "changed_symbol": row.get("changed_symbol", ""),
            "steps": row.get("steps", 0),
        })
    if indexed_rows:
        return {
            "affected_processes": affected_processes[:12],
            "risk_by_process": risk_by_process[:12],
        }
    for item in unique_targets[:3]:
        traced = run_with_timeout(
            lambda item=item: trace_execution_flows(
                duckdb_store,
                kuzu_store,
                target=item["target"],
                file_path=item["file_path"] or None,
                kind=item["kind"] or None,
                max_depth=4,
                max_flows=4,
                changed_symbols=[item["target"]],
            ),
            timeout_seconds=PROCESS_OPERATION_TIMEOUT_SECONDS,
            default={},
            warnings=warnings,
            label=f"Process tracing for {item['target']}",
        )
        if not traced:
            continue
        flows = traced.get("flows", []) if isinstance(traced, dict) else []
        for flow in flows[:4] if isinstance(flows, list) else []:
            if not isinstance(flow, dict):
                continue
            route_context = [route for route in changed_routes if route.replace("/", "_").strip("_").lower() in str(flow.get("name", "")).lower()]
            risk = str(flow.get("risk") or ("HIGH" if int(flow.get("steps", 0) or 0) >= 5 else "MEDIUM" if int(flow.get("steps", 0) or 0) >= 3 else "LOW"))
            process_row = {
                "name": flow.get("name", ""),
                "target": item["target"],
                "entry_symbol": flow.get("entry_symbol", ""),
                "module": flow.get("module", ""),
                "steps": flow.get("steps", 0),
                "step_details": flow.get("step_details", []),
                "changed_symbol": item["target"],
                "changed_symbols": flow.get("changed_symbols", [item["target"]]),
                "changed_routes": route_context,
                "risk": risk,
                "risk_reasons": flow.get("risk_reasons", []),
            }
            affected_processes.append(process_row)
            risk_by_process.append({
                "name": process_row["name"],
                "risk": risk,
                "changed_symbol": item["target"],
                "steps": process_row["steps"],
            })
    return {
        "affected_processes": affected_processes[:12],
        "risk_by_process": risk_by_process[:12],
    }


def _route_change_summary(repo_root: Path, duckdb_store: DuckDBStore, changed_files: list[str], changed_symbols: list[dict[str, object]] | None = None, kuzu_store: KuzuStore | None = None) -> dict[str, object]:
    if not changed_files:
        return {
            "changed_routes": [],
            "affected_consumers": [],
            "changed_response_shapes": [],
            "risk_by_route": [],
            "shape_mismatches": [],
        }
    changed_set = set(changed_files)
    changed_routes = []
    changed_symbols_by_file: dict[str, set[str]] = {}
    for symbol in changed_symbols or []:
        if not isinstance(symbol, dict):
            continue
        file_path = str(symbol.get("file_path", "") or "")
        names = {
            str(symbol.get("name", "") or ""),
            str(symbol.get("qualified_name", "") or "").rsplit(".", 1)[-1],
        }
        changed_symbols_by_file.setdefault(file_path, set()).update(name for name in names if name)
    affected_consumers: dict[str, dict[str, object]] = {}
    changed_response_shapes = []
    risk_by_route = []
    shape_mismatches = []
    candidate_routes: list[str] = []
    for file_path in changed_files:
        suffix = Path(file_path).suffix.lower()
        absolute_path = repo_root / file_path
        if suffix == ".py":
            source = _read_text(absolute_path)
            if not source:
                continue
            for handler in _backend_handlers(source, file_path, ""):
                handler_name = str(handler.get("handler", "") or "")
                changed_names = changed_symbols_by_file.get(file_path, set())
                if changed_names and handler_name not in changed_names:
                    continue
                route = str(handler.get("normalized_route") or handler.get("route") or "")
                if route and route not in candidate_routes:
                    candidate_routes.append(route)
        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            source = _read_text(absolute_path)
            if not source:
                continue
            direct_consumers, direct_wrapper_routes = _direct_frontend_consumers(source, file_path, "", duckdb_store)
            for consumer in direct_consumers:
                route = str(consumer.get("normalized_route") or consumer.get("route") or "")
                if route and route not in candidate_routes:
                    candidate_routes.append(route)
            for route in direct_wrapper_routes.values():
                if route and route not in candidate_routes:
                    candidate_routes.append(route)
    for route_name in candidate_routes[:8]:
        contract = run_with_timeout(
            lambda route_name=route_name: api_impact(repo_root, duckdb_store, route=route_name, kuzu_store=kuzu_store),
            timeout_seconds=ROUTE_OPERATION_TIMEOUT_SECONDS,
            default={},
            label=f"Route impact for {route_name}",
        )
        if not contract:
            continue
        for route_row in contract.get("routes", []) if isinstance(contract, dict) else []:
            if not isinstance(route_row, dict):
                continue
            route_row = {
                **route_row,
                "status": route_row.get("shape_check", {}).get("status", "UNKNOWN") if isinstance(route_row.get("shape_check", {}), dict) else "UNKNOWN",
                "missing_fields": route_row.get("shape_check", {}).get("missing_fields", []) if isinstance(route_row.get("shape_check", {}), dict) else [],
                "nested_missing_fields": route_row.get("shape_check", {}).get("nested_missing_fields", []) if isinstance(route_row.get("shape_check", {}), dict) else [],
                "checked_consumers": route_row.get("shape_check", {}).get("checked_consumers", 0) if isinstance(route_row.get("shape_check", {}), dict) else 0,
            }
            break
        else:
            continue
        if not isinstance(route_row, dict):
            continue
        consumers = route_row.get("consumers", []) if isinstance(route_row.get("consumers", []), list) else []
        graph_contract = route_row.get("graph_contract", {}) if isinstance(route_row.get("graph_contract", {}), dict) else {}
        handler_files = [
            str(handler.get("file_path", ""))
            for handler in route_row.get("handlers", []) if isinstance(handler, dict)
        ] if isinstance(route_row.get("handlers", []), list) else []
        consumer_files = [
            str(consumer.get("file_path", ""))
            for consumer in consumers if isinstance(consumer, dict)
        ]
        handler_touched = False
        for handler in route_row.get("handlers", []) if isinstance(route_row.get("handlers", []), list) else []:
            if not isinstance(handler, dict):
                continue
            handler_file = str(handler.get("file_path", "") or "")
            handler_name = str(handler.get("handler", "") or "")
            if handler_file not in changed_set:
                continue
            changed_names = changed_symbols_by_file.get(handler_file, set())
            if not changed_names or handler_name in changed_names:
                handler_touched = True
                break
        consumer_touched = any(file_path in changed_set for file_path in consumer_files)
        route_touched = handler_touched or consumer_touched
        if not route_touched:
            continue
        route_name = str(route_row.get("route", ""))
        if route_name in changed_routes:
            continue
        changed_routes.append(route_name)
        if handler_touched:
            changed_response_shapes.append({
                "route": route_name,
                "response_shape": route_row.get("response_shape", {}),
                "status": route_row.get("status", "UNKNOWN"),
            })
        for consumer in consumers:
            if not isinstance(consumer, dict):
                continue
            consumer_file = str(consumer.get("file_path", ""))
            if consumer_file:
                field_reads = list(consumer.get("nested_accesses", []) if isinstance(consumer.get("nested_accesses", []), list) else [])
                if graph_contract:
                    for graph_field in graph_contract.get("field_reads", []) if isinstance(graph_contract.get("field_reads", []), list) else []:
                        if graph_field not in field_reads:
                            field_reads.append(graph_field)
                affected_consumers[consumer_file] = {
                    "file": consumer_file,
                    "route": route_name,
                    "function": consumer.get("function", ""),
                    "consumer_type": consumer.get("consumer_type", ""),
                    "field_reads": field_reads,
                }
                if graph_contract:
                    affected_consumers[consumer_file]["graph_contract"] = graph_contract
        risk_by_route.append({
            "route": route_name,
            "risk": route_row.get("risk", "LOW"),
            "status": route_row.get("status", "UNKNOWN"),
            "checked_consumers": route_row.get("checked_consumers", 0),
        })
        if route_row.get("status") == "MISMATCH":
            shape_mismatches.append({
                "route": route_name,
                "missing_fields": route_row.get("missing_fields", []),
                "nested_missing_fields": route_row.get("nested_missing_fields", []),
            })
    return {
        "changed_routes": changed_routes,
        "affected_consumers": list(affected_consumers.values()),
        "changed_response_shapes": changed_response_shapes,
        "risk_by_route": risk_by_route,
        "shape_mismatches": shape_mismatches,
    }


def detect_changes(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    scope: str = "unstaged",
    base_ref: str | None = None,
    diff_text_override: str | None = None,
    git_warning: str | None = None,
) -> dict[str, object]:
    warnings: list[str] = []
    normalized_scope = _normalized_scope(scope)
    diff_text = diff_text_override if diff_text_override is not None else _diff_output(repo_root, scope=normalized_scope, base_ref=base_ref)
    if git_warning:
        warnings.append(git_warning)
    if diff_text_override is None and not diff_text and not _run_git(repo_root, ["rev-parse", "--git-dir"]):
        warnings.append(f"No git repository found at {repo_root}. detect_changes requires a git repo.")
    changed_lines_by_file = _parse_changed_lines(diff_text)
    changed_files = sorted(changed_lines_by_file)
    changed_symbols: list[dict[str, object]] = []
    for file_path in changed_files:
        changed_symbols.extend(_symbols_for_changed_lines(duckdb_store, file_path, changed_lines_by_file[file_path]))
    if len(changed_files) > BROAD_GRAPH_FILE_LIMIT:
        impacted_files = []
        warnings.append(
            f"Graph blast-radius traversal skipped for {len(changed_files)} changed files; narrow the scope or target a file/symbol for full graph impact."
        )
    else:
        impacted_files = sorted(run_with_timeout(
            lambda: kuzu_store.get_impacted_files(changed_files),
            timeout_seconds=GRAPH_OPERATION_TIMEOUT_SECONDS,
            default=set(),
            warnings=warnings,
            label="Graph blast-radius traversal",
        )) if changed_files else []
    impacted_symbols: list[dict[str, object]] = []
    seen_symbols: set[tuple[str, str]] = set()
    for file_path in impacted_files[:25]:
        for symbol in duckdb_store.fetch_symbols_for_file(file_path)[:10]:
            key = (file_path, str(symbol.get("qualified_name", "")))
            if key in seen_symbols:
                continue
            seen_symbols.add(key)
            impacted_symbols.append(
                {
                    "qualified_name": symbol.get("qualified_name", ""),
                    "name": symbol.get("name", ""),
                    "kind": symbol.get("kind", ""),
                    "file_path": file_path,
                }
            )
    file_risks = _risk_by_file(changed_files, changed_symbols, impacted_files)
    route_summary = _route_change_summary(repo_root, duckdb_store, changed_files, changed_symbols, kuzu_store=kuzu_store)
    if len(changed_symbols) > BROAD_PROCESS_SYMBOL_LIMIT or len(changed_files) > BROAD_GRAPH_FILE_LIMIT:
        process_summary = {"affected_processes": [], "risk_by_process": []}
        if changed_symbols:
            warnings.append(
                f"Process tracing skipped for broad diff ({len(changed_symbols)} changed symbols); use trace_processes on a focused target for full flows."
            )
    else:
        process_summary = _process_change_summary(duckdb_store, kuzu_store, changed_symbols, route_summary.get("changed_routes", []), warnings)
    risk = _overall_risk(changed_files, changed_symbols, impacted_files, file_risks)
    if route_summary.get("shape_mismatches") and risk != "CRITICAL":
        risk = "HIGH"
    elif any(item.get("risk") == "HIGH" for item in route_summary.get("risk_by_route", []) if isinstance(item, dict)) and risk == "LOW":
        risk = "MEDIUM"
    if any(item.get("risk") == "HIGH" for item in process_summary.get("risk_by_process", []) if isinstance(item, dict)) and risk not in {"HIGH", "CRITICAL"}:
        risk = "HIGH"
    weighted_risk = _weighted_risk(changed_files, changed_symbols, impacted_files, file_risks, route_summary, process_summary)
    risk_scope = _risk_scope(normalized_scope)
    risk_explanation = _risk_explanation(changed_files, changed_symbols, impacted_files, file_risks)
    if route_summary.get("changed_routes"):
        risk_explanation.append(f"{len(route_summary.get('changed_routes', []))} API routes touched by changed files")
    if route_summary.get("shape_mismatches"):
        risk_explanation.append(f"{len(route_summary.get('shape_mismatches', []))} route shape mismatches detected")
    if process_summary.get("affected_processes"):
        risk_explanation.append(f"{len(process_summary.get('affected_processes', []))} execution flows include changed symbols")
    git_metadata = {
        "repo_root": str(repo_root.resolve()),
        "scope": normalized_scope,
        "base_ref": base_ref or None,
        "diff_command_equivalent": _diff_command_equivalent(normalized_scope, base_ref),
        "changed_files_count": len(changed_files),
    }
    confidence = _confidence(changed_files, changed_symbols, impacted_files, warnings)
    follow_up_tools = _focused_followups(file_risks, changed_symbols, warnings)
    return {
        "repo_root": str(repo_root.resolve()),
        "scope": normalized_scope,
        "base_ref": base_ref or "",
        "git": git_metadata,
        "risk_scope": risk_scope,
        "risk_applies_to": _risk_applies_to(normalized_scope, base_ref),
        "not_limited_to_recent_edits": normalized_scope in {"unstaged", "staged", "all"},
        "risk_explanation": risk_explanation,
        "risk_score": weighted_risk["score"],
        "risk_score_label": weighted_risk["label"],
        "weighted_risk_factors": weighted_risk["factors"],
        "risk_by_file": file_risks,
        "changed_routes": route_summary.get("changed_routes", []),
        "affected_consumers": route_summary.get("affected_consumers", []),
        "changed_response_shapes": route_summary.get("changed_response_shapes", []),
        "risk_by_route": route_summary.get("risk_by_route", []),
        "shape_mismatches": route_summary.get("shape_mismatches", []),
        "affected_processes": process_summary.get("affected_processes", []),
        "risk_by_process": process_summary.get("risk_by_process", []),
        "changed_files": changed_files,
        "changed_symbols": changed_symbols,
        "impacted_files": impacted_files,
        "impacted_symbols": impacted_symbols,
        "risk": risk,
        "confidence": confidence["level"],
        "confidence_explanation": confidence["why"],
        "warnings": warnings,
        "follow_up_tools": follow_up_tools,
        "compact_summary": {
            "target": str(repo_root.resolve()),
            "scope": normalized_scope,
            "risk_scope": risk_scope,
            "changed_file_count": len(changed_files),
            "changed_symbol_count": len(changed_symbols),
            "impacted_file_count": len(impacted_files),
            "risk": risk,
            "risk_score": weighted_risk["score"],
            "risk_score_label": weighted_risk["label"],
            "weighted_risk_factors": weighted_risk["factors"][:6],
            "confidence": confidence["level"],
            "risk_explanation": risk_explanation[:6],
            "top_risk_files": [row.get("file", "") for row in file_risks if row.get("risk") in {"CRITICAL", "HIGH"}][:8],
            "changed_routes": route_summary.get("changed_routes", [])[:8],
            "shape_mismatches": [item.get("route", "") for item in route_summary.get("shape_mismatches", [])][:8],
            "affected_processes": [item.get("name", "") for item in process_summary.get("affected_processes", [])][:8],
            "top_changed_files": changed_files[:8],
            "top_changed_symbols": [item.get("qualified_name") or item.get("name") for item in changed_symbols[:8]],
            "top_impacted_files": impacted_files[:8],
            "follow_up_tools": follow_up_tools,
        },
    }
