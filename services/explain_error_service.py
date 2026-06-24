"""Explain an error by parsing a stack trace and returning relevant code context.

Given a Python or TypeScript/JavaScript stack trace, extracts file paths, line numbers,
and function names, then resolves them to indexed symbols and returns:
- Symbol metadata for each frame
- Source snippets around each frame
- Caller chains for the erroring function
- Data flow context if applicable
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from services.graph_edge_utils import edges_for_target_limited
from services.source_retrieval_service import _direct_file_snippet
from services.symbol_resolution_service import resolve_candidates

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


# Python traceback pattern: File "path", line N, in function
_PY_FRAME = re.compile(r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\S+)')
# JS/TS pattern: at function (path:N:col) or at path:N:col
_JS_FRAME = re.compile(r'at\s+(.+?)\s+\((.+?):(\d+)(?::\d+)?\)')
# JS/TS pattern without function: at path:N:col
_JS_FRAME_BARE = re.compile(r'at\s+(.+?):(\d+)(?::\d+)?')


def _parse_python_traceback(text: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for match in _PY_FRAME.finditer(text):
        frames.append({
            "file_path": match.group(1).replace("\\", "/"),
            "line_number": int(match.group(2)),
            "function": match.group(3),
            "language": "python",
        })
    return frames


def _parse_js_traceback(text: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for match in _JS_FRAME.finditer(text):
        frames.append({
            "file_path": match.group(2).replace("\\", "/"),
            "line_number": int(match.group(3)),
            "function": match.group(1),
            "language": "typescript",
        })
    for match in _JS_FRAME_BARE.finditer(text):
        fp = match.group(1).replace("\\", "/")
        if any(fp.endswith(ext) for ext in (".ts", ".tsx", ".js", ".jsx")):
            frames.append({
                "file_path": fp,
                "line_number": int(match.group(2)),
                "function": "",
                "language": "typescript",
            })
    return frames


def _detect_language(text: str) -> str:
    if "Traceback" in text or _PY_FRAME.search(text):
        return "python"
    if _JS_FRAME.search(text) or _JS_FRAME_BARE.search(text):
        return "typescript"
    return "unknown"


def _parse_traceback(text: str) -> list[dict[str, object]]:
    lang = _detect_language(text)
    if lang == "python":
        return _parse_python_traceback(text)
    if lang == "typescript":
        return _parse_js_traceback(text)
    return []


def _extract_error_message(text: str) -> str:
    lines = text.strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("File ") and not stripped.startswith("at "):
            if not re.match(r'^[~^]+\s*$', stripped) and len(stripped) > 3:
                return stripped
    return ""


def _normalize_file_path(file_path: str, repo_root: Path) -> str:
    normalized = file_path.replace("\\", "/")
    repo_root_str = str(repo_root).replace("\\", "/")
    if normalized.startswith(repo_root_str + "/"):
        return normalized[len(repo_root_str) + 1:]
    if normalized.startswith("./"):
        return normalized[2:]
    return normalized


def _resolve_frame_symbol(
    duckdb_store: DuckDBStore,
    file_path: str,
    function: str,
    line_number: int,
) -> dict[str, object] | None:
    if not function:
        return None
    candidates = resolve_candidates(duckdb_store, target=function, limit=5)
    for candidate in candidates:
        symbol = candidate.get("symbol", {}) if isinstance(candidate, dict) else {}
        sym_file = str(symbol.get("file_path", "") or "").replace("\\", "/")
        if sym_file and sym_file.endswith(file_path.split("/")[-1]):
            start = int(symbol.get("start_line") or 0)
            end = int(symbol.get("end_line") or 0)
            if start <= line_number <= end or (start == 0 and end == 0):
                return {
                    "qualified_name": symbol.get("qualified_name", ""),
                    "name": symbol.get("name", ""),
                    "kind": symbol.get("kind", ""),
                    "file_path": sym_file,
                    "start_line": start,
                    "end_line": end,
                    "signature": symbol.get("signature", ""),
                }
    if candidates:
        symbol = candidates[0].get("symbol", {}) if isinstance(candidates[0], dict) else {}
        return {
            "qualified_name": symbol.get("qualified_name", ""),
            "name": symbol.get("name", ""),
            "kind": symbol.get("kind", ""),
            "file_path": str(symbol.get("file_path", "") or ""),
            "start_line": symbol.get("start_line"),
            "end_line": symbol.get("end_line"),
            "signature": symbol.get("signature", ""),
        }
    return None


def _get_source_snippet(repo_root: Path, file_path: str, line_number: int, context: int = 5) -> dict[str, object] | None:
    full_path = (repo_root / file_path).resolve()
    try:
        full_path.relative_to(repo_root.resolve())
    except ValueError:
        return None
    if not full_path.exists() or not full_path.is_file():
        return None
    try:
        lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if not lines:
        return None
    start = max(1, line_number - context)
    end = min(len(lines), line_number + context)
    content = "\n".join(lines[start - 1 : end])
    return {
        "file_path": file_path,
        "start_line": start,
        "end_line": end,
        "content": content,
        "error_line": line_number,
    }


def explain_error(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    stack_trace: str,
    repo_root: Path | None = None,
) -> dict[str, object]:
    raw_frames = _parse_traceback(stack_trace)
    error_message = _extract_error_message(stack_trace)
    language = _detect_language(stack_trace)

    if not raw_frames:
        return {
            "status": "parse_failed",
            "error_message": error_message,
            "language": language,
            "frames": [],
            "compact_summary": {
                "status": "parse_failed",
                "error_message": error_message,
                "language": language,
            },
            "summary_text": f"Could not parse stack trace. Detected language: {language}. Error: {error_message}",
        }

    frames: list[dict[str, object]] = []
    resolved_symbols: list[str] = []

    for raw_frame in raw_frames:
        file_path = raw_frame["file_path"]
        function = raw_frame["function"]
        line_number = raw_frame["line_number"]

        normalized_path = _normalize_file_path(file_path, repo_root) if repo_root else file_path

        frame: dict[str, object] = {
            "file_path": normalized_path,
            "line_number": line_number,
            "function": function,
            "language": raw_frame.get("language", language),
        }

        symbol_info = _resolve_frame_symbol(duckdb_store, normalized_path, function, line_number)
        if symbol_info:
            frame["symbol"] = symbol_info
            qn = str(symbol_info.get("qualified_name", "") or "").strip()
            if qn:
                resolved_symbols.append(qn)

        if repo_root:
            snippet = _get_source_snippet(repo_root, normalized_path, line_number)
            if snippet:
                frame["source_snippet"] = snippet

        frames.append(frame)

    error_frame = frames[-1] if frames else None
    callers: list[dict[str, object]] = []
    if error_frame and resolved_symbols:
        error_symbol = resolved_symbols[-1]
        caller_edges = edges_for_target_limited(kuzu_store, error_symbol, relation="CALLS", limit=10)
        callers = [
            {
                "caller": str(edge.get("source", "")),
                "relation": str(edge.get("relation", "")),
            }
            for edge in caller_edges
            if str(edge.get("source", ""))
        ]

    top_files = list(dict.fromkeys(
        str(frame.get("file_path", "") or "")
        for frame in frames
        if frame.get("file_path")
    ))

    return {
        "status": "ok",
        "error_message": error_message,
        "language": language,
        "frame_count": len(frames),
        "frames": frames,
        "error_frame": error_frame,
        "error_symbol": resolved_symbols[-1] if resolved_symbols else "",
        "callers_of_error_symbol": callers,
        "resolved_symbols": resolved_symbols,
        "compact_summary": {
            "status": "ok",
            "error_message": error_message,
            "language": language,
            "frame_count": len(frames),
            "error_function": str(error_frame.get("function", "")) if error_frame else "",
            "error_file": str(error_frame.get("file_path", "")) if error_frame else "",
            "error_line": error_frame.get("line_number") if error_frame else None,
            "error_symbol": resolved_symbols[-1] if resolved_symbols else "",
            "caller_count": len(callers),
            "top_files": top_files[:5],
        },
        "summary_text": f"Error in {error_frame.get('function', 'unknown')} at {error_frame.get('file_path', '?')}:{error_frame.get('line_number', '?')} — {error_message}" if error_frame else f"Error: {error_message}",
    }
