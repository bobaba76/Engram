from __future__ import annotations

import re
import subprocess
from pathlib import Path

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore


HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@", re.MULTILINE)


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
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _diff_output(repo_root: Path, scope: str, base_ref: str | None = None) -> str:
    normalized = scope if scope in {"unstaged", "staged", "all", "compare"} else "unstaged"
    if normalized == "staged":
        return _run_git(repo_root, ["diff", "--cached", "--unified=0", "--no-color"])
    if normalized == "all":
        staged = _run_git(repo_root, ["diff", "--cached", "--unified=0", "--no-color"])
        unstaged = _run_git(repo_root, ["diff", "--unified=0", "--no-color"])
        return "\n".join(part for part in (staged, unstaged) if part.strip())
    if normalized == "compare":
        compare_ref = (base_ref or "HEAD").strip() or "HEAD"
        return _run_git(repo_root, ["diff", f"{compare_ref}...HEAD", "--unified=0", "--no-color"])
    return _run_git(repo_root, ["diff", "--unified=0", "--no-color"])


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
            symbols.append(
                {
                    "qualified_name": symbol.get("qualified_name", ""),
                    "name": symbol.get("name", ""),
                    "kind": symbol.get("kind", ""),
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                }
            )
    return symbols


def detect_changes(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    scope: str = "unstaged",
    base_ref: str | None = None,
) -> dict[str, object]:
    warnings: list[str] = []
    diff_text = _diff_output(repo_root, scope=scope, base_ref=base_ref)
    if not diff_text and not _run_git(repo_root, ["rev-parse", "--git-dir"]):
        warnings.append(f"No git repository found at {repo_root}. detect_changes requires a git repo.")
    changed_lines_by_file = _parse_changed_lines(diff_text)
    changed_files = sorted(changed_lines_by_file)
    changed_symbols: list[dict[str, object]] = []
    for file_path in changed_files:
        changed_symbols.extend(_symbols_for_changed_lines(duckdb_store, file_path, changed_lines_by_file[file_path]))
    impacted_files = sorted(kuzu_store.get_impacted_files(changed_files)) if changed_files else []
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
    risk = "LOW"
    if len(changed_symbols) >= 8 or len(impacted_files) >= 12:
        risk = "HIGH"
    elif len(changed_symbols) >= 3 or len(impacted_files) >= 5:
        risk = "MEDIUM"
    return {
        "repo_root": str(repo_root.resolve()),
        "scope": scope,
        "base_ref": base_ref or "",
        "changed_files": changed_files,
        "changed_symbols": changed_symbols,
        "impacted_files": impacted_files,
        "impacted_symbols": impacted_symbols,
        "risk": risk,
        "warnings": warnings,
        "compact_summary": {
            "target": str(repo_root.resolve()),
            "scope": scope,
            "changed_file_count": len(changed_files),
            "changed_symbol_count": len(changed_symbols),
            "impacted_file_count": len(impacted_files),
            "risk": risk,
            "top_changed_files": changed_files[:8],
            "top_changed_symbols": [item.get("qualified_name") or item.get("name") for item in changed_symbols[:8]],
            "top_impacted_files": impacted_files[:8],
        },
    }
