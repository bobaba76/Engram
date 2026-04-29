from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.symbol_resolution_service import ambiguity_status, resolve_candidates, symbol_uid_from_target

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore


def resolve_target(target: str, repo_root: Path) -> str:
    candidate = repo_root / target
    if candidate.exists():
        return str(candidate.relative_to(repo_root)).replace("\\", "/")
    return target


def resolve_tool_target(
    duckdb_store: DuckDBStore,
    repo_root: Path,
    target: str = "",
    file_path: str | None = None,
    kind: str | None = None,
    symbol_uid: str | None = None,
    limit: int = 5,
) -> dict[str, object]:
    normalized_target = resolve_target(str(target or "").strip(), repo_root)
    resolved_symbol_uid = symbol_uid_from_target(normalized_target, symbol_uid)
    lookup_target = normalized_target
    if resolved_symbol_uid and resolved_symbol_uid == lookup_target:
        lookup_target = ""
    candidates = resolve_candidates(
        duckdb_store,
        target=lookup_target,
        file_path=file_path,
        kind=kind,
        symbol_uid_value=resolved_symbol_uid,
        limit=limit,
    )
    matches: list[dict[str, object]] = []
    for item in candidates:
        symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
        matches.append(
            {
                "score": round(float(item.get("score", 0.0) or 0.0), 4),
                "confidence": item.get("confidence", "low"),
                "relevance": item.get("relevance", ""),
                "uid": symbol.get("uid", ""),
                "file_path": symbol.get("file_path", ""),
                "name": symbol.get("name", ""),
                "qualified_name": symbol.get("qualified_name", ""),
                "kind": symbol.get("kind", ""),
                "start_line": symbol.get("start_line"),
                "end_line": symbol.get("end_line"),
            }
        )
    primary = matches[0] if matches else {}
    ambiguous = ambiguity_status(candidates)
    return {
        "target": target,
        "normalized_target": normalized_target,
        "status": "ambiguous" if ambiguous else "found" if matches else "not_found",
        "resolved_target": primary.get("qualified_name") or primary.get("name") or normalized_target,
        "resolved_uid": primary.get("uid") or resolved_symbol_uid or "",
        "matches": matches,
        "compact_results": matches,
        "compact_summary": {
            "target": normalized_target,
            "status": "ambiguous" if ambiguous else "found" if matches else "not_found",
            "match_count": len(matches),
            "resolved_target": primary.get("qualified_name") or primary.get("name") or "",
            "resolved_uid": primary.get("uid") or resolved_symbol_uid or "",
            "warnings": ["Target resolution is ambiguous; pass file_path, kind, or symbol_uid."] if ambiguous else [],
        },
    }
