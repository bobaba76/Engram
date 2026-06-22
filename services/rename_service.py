from __future__ import annotations

import logging
import re
from pathlib import Path

from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore
from services.symbol_resolution_service import ambiguity_status, resolve_candidates

logger = logging.getLogger(__name__)


WORD_TEMPLATE = r"(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])"
IDENTIFIER_CONTEXT_TEMPLATE = r"(?P<prefix>(?:const\s+|let\s+|var\s+|function\s+|class\s+|interface\s+|type\s+|export\s+default\s+|export\s+const\s+|export\s+function\s+|import\s+|element=\{{<|<|</))(?P<name>{name})(?P<suffix>(?:\s|\(|=|\{{|>|/|\}}|,|;|:))"
COMMENT_PREFIXES = ("//", "/*", "*", "*/")


def _looks_like_comment(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(prefix) for prefix in COMMENT_PREFIXES)


def _replace_identifier_contexts(line: str, symbol_name: str, new_name: str) -> str | None:
    pattern = re.compile(IDENTIFIER_CONTEXT_TEMPLATE.format(name=re.escape(symbol_name)))

    def _replacer(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{new_name}{match.group('suffix')}"

    replaced = pattern.sub(_replacer, line)
    return replaced if replaced != line else None


def _confidence_class(line: str) -> str:
    lowered = line.strip()
    if lowered.startswith(("const ", "let ", "var ", "function ", "class ", "interface ", "type ")):
        return "declaration"
    if lowered.startswith(("export default ", "export const ", "export function ", "import ")):
        return "import_export"
    if "<" in lowered and "/>" in lowered:
        return "jsx_usage"
    return "code_reference"


def _text_search_preview(repo_root: Path, symbol_name: str, new_name: str, file_paths: list[str]) -> list[dict[str, object]]:
    edits: list[dict[str, object]] = []
    pattern = re.compile(WORD_TEMPLATE.format(name=re.escape(symbol_name)))
    for file_path in sorted(set(file_paths)):
        absolute_path = repo_root / file_path
        try:
            source = absolute_path.read_text(encoding="utf-8")
        except Exception:
            logger.warning("rename_service: failed to read file %s", file_path, exc_info=True)
            continue
        lines = source.splitlines()
        for line_number, line in enumerate(lines, start=1):
            if not pattern.search(line):
                continue
            if _looks_like_comment(line):
                continue
            replaced = _replace_identifier_contexts(line, symbol_name, new_name)
            if replaced is None:
                continue
            edits.append(
                {
                    "file_path": file_path,
                    "line": line_number,
                    "old_text": line,
                    "new_text": replaced,
                    "confidence": "graph" if file_path in file_paths[:1] else "text_search",
                    "confidence_class": _confidence_class(line),
                }
            )
    return edits


def preview_rename(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    symbol_name: str,
    new_name: str,
    file_path: str | None = None,
    symbol_uid: str | None = None,
) -> dict[str, object]:
    candidates = resolve_candidates(duckdb_store, target=symbol_name, file_path=file_path, symbol_uid_value=symbol_uid, limit=5)
    if not candidates:
        return {
            "symbol_name": symbol_name,
            "new_name": new_name,
            "status": "not_found",
            "edits": [],
            "compact_summary": {
                "target": symbol_name,
                "status": "not_found",
                "edit_count": 0,
            },
        }
    primary = candidates[0]
    symbol = primary.get("symbol", {}) if isinstance(primary, dict) else {}
    resolved_target = str(symbol.get("qualified_name") or symbol.get("name") or symbol_name)
    ambiguous = ambiguity_status(candidates)
    related_files = {str(symbol.get("file_path", ""))}
    for edge in kuzu_store.edges_for_target(resolved_target):
        source_name = str(edge.get("source", ""))
        matches = duckdb_store.fetch_symbols_for_target(source_name, limit=1)
        if matches:
            related_files.add(str(matches[0].get("file_path", "")))
    for edge in kuzu_store.edges_for_source(resolved_target):
        target_name = str(edge.get("target", ""))
        matches = duckdb_store.fetch_symbols_for_target(target_name, limit=1)
        if matches:
            related_files.add(str(matches[0].get("file_path", "")))
    edits = _text_search_preview(repo_root, str(symbol.get("name") or symbol_name), new_name, [file for file in related_files if file])
    for edit in edits:
        if edit.get("file_path") == symbol.get("file_path", "") and edit.get("confidence_class") == "code_reference":
            edit["confidence_class"] = "graph_local"
    return {
        "symbol_name": symbol_name,
        "new_name": new_name,
        "status": "ambiguous" if ambiguous else "found",
        "resolved_target": resolved_target,
        "resolved_uid": symbol.get("uid", ""),
        "candidate_matches": [
            {
                "qualified_name": item.get("symbol", {}).get("qualified_name", ""),
                "file_path": item.get("symbol", {}).get("file_path", ""),
                "kind": item.get("symbol", {}).get("kind", ""),
                "uid": item.get("symbol", {}).get("uid", ""),
                "score": item.get("score", 0.0),
                "confidence": item.get("confidence", "low"),
            }
            for item in candidates
        ],
        "edits": edits,
        "compact_summary": {
            "target": resolved_target,
            "status": "ambiguous" if ambiguous else "found",
            "edit_count": len(edits),
            "files": sorted({edit["file_path"] for edit in edits})[:8],
            "warnings": ["Rename target is ambiguous; pass file_path to narrow it."] if ambiguous else [],
        },
    }
