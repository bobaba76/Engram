from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.symbol_resolution_service import resolve_candidates, symbol_uid_from_target

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _direct_file_snippet(repo_root: Path | None, symbol: dict[str, object], context_lines: int = 8) -> dict[str, object] | None:
    if repo_root is None:
        return None
    file_path = str(symbol.get("file_path", "") or "").strip()
    if not file_path:
        return None
    candidate = (repo_root / file_path).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    start_line = max(1, _safe_int(symbol.get("start_line"), 1))
    end_line = max(start_line, _safe_int(symbol.get("end_line"), start_line))
    try:
        source_lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if not source_lines:
        return None
    snippet_start = max(1, start_line - context_lines)
    snippet_end = min(len(source_lines), end_line + context_lines)
    content = "\n".join(source_lines[snippet_start - 1 : snippet_end])
    return {
        "file_path": file_path,
        "target": symbol.get("qualified_name") or symbol.get("name") or file_path,
        "chunk_kind": "direct_source",
        "start_line": snippet_start,
        "end_line": snippet_end,
        "content": content,
        "preview": "\n".join(content.splitlines()[:12]),
        "retrieval_source": "direct_file_fallback",
    }


def get_source_context(duckdb_store: DuckDBStore, target: str, limit: int = 5, repo_root: Path | None = None) -> dict[str, object]:
    resolved_symbol_uid = symbol_uid_from_target(target)
    lookup_target = str(target or "").strip()
    if resolved_symbol_uid and resolved_symbol_uid == lookup_target:
        lookup_target = ""
    resolved_candidates = resolve_candidates(duckdb_store, target=lookup_target, symbol_uid_value=resolved_symbol_uid, limit=max(limit * 3, 15))
    symbol_matches = []
    for item in resolved_candidates:
        symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
        symbol_matches.append(
            {
                "file_path": symbol.get("file_path", ""),
                "name": symbol.get("name", ""),
                "qualified_name": symbol.get("qualified_name", ""),
                "kind": symbol.get("kind", ""),
                "start_line": symbol.get("start_line"),
                "end_line": symbol.get("end_line"),
            }
        )

    results = []
    for symbol in symbol_matches[:limit]:
        file_path = str(symbol.get("file_path", "") or "").strip()
        start_line = symbol.get("start_line")
        end_line = symbol.get("end_line")
        results = duckdb_store.chunks.fetch_for_file_range(file_path, start_line=start_line, end_line=end_line, limit=limit)
        if results:
            break
    if not results:
        fallback_targets: list[str] = []
        for symbol in symbol_matches[:limit]:
            qualified_name = str(symbol.get("qualified_name", "") or "").strip()
            file_path = str(symbol.get("file_path", "") or "").strip()
            name = str(symbol.get("name", "") or "").strip()
            for value in (qualified_name, file_path, name):
                if value and value not in fallback_targets:
                    fallback_targets.append(value)
        for fallback_target in fallback_targets:
            results = duckdb_store.chunks.fetch_for_target(fallback_target, limit=limit)
            if results:
                break
    if not results:
        results = duckdb_store.chunks.fetch_for_target(lookup_target or target, limit=limit)

    snippet_results = [
        {
            "file_path": chunk["file_path"],
            "target": chunk.get("qualified_name") or chunk.get("symbol_name") or chunk["file_path"],
            "chunk_kind": chunk.get("chunk_kind"),
            "start_line": chunk.get("start_line"),
            "end_line": chunk.get("end_line"),
            "content": chunk.get("content", ""),
            "preview": "\n".join(chunk.get("content", "").splitlines()[:12]),
            "retrieval_source": "chunk_index",
        }
        for chunk in results
    ]
    if not snippet_results:
        for symbol in symbol_matches[:limit]:
            fallback = _direct_file_snippet(repo_root, symbol)
            if fallback:
                snippet_results.append(fallback)
                break
    return {
        "target": target,
        "symbol_matches": symbol_matches[:limit],
        "results": results,
        "snippet_results": snippet_results,
        "compact_results": [
            {
                "file": chunk["file_path"],
                "target": chunk.get("qualified_name") or chunk.get("symbol_name") or chunk["file_path"],
                "lines": [chunk.get("start_line"), chunk.get("end_line")],
                "chunk_kind": chunk.get("chunk_kind"),
                "retrieval_source": "chunk_index",
            }
            for chunk in results
        ]
        or [
            {
                "file": snippet["file_path"],
                "target": snippet.get("target") or snippet["file_path"],
                "lines": [snippet.get("start_line"), snippet.get("end_line")],
                "chunk_kind": snippet.get("chunk_kind"),
                "retrieval_source": snippet.get("retrieval_source"),
            }
            for snippet in snippet_results
        ],
    }
