from models.entity_models import SymbolRecord
from services.symbol_resolution_service import ambiguity_status, resolve_candidates, symbol_uid_from_target
from storage.duckdb_store import DuckDBStore


def _compact_summary(target: str, matches: list[dict[str, object]], status: str) -> dict[str, object]:
    return {
        "target": target,
        "status": status,
        "match_count": len(matches),
        "top_files": [str(item.get("file") or item.get("file_path") or "") for item in matches[:8] if str(item.get("file") or item.get("file_path") or "").strip()],
        "top_symbols": [
            str(item.get("qualified_name") or item.get("symbol") or item.get("name") or "")
            for item in matches[:8]
            if str(item.get("qualified_name") or item.get("symbol") or item.get("name") or "").strip()
        ],
    }


def get_symbol_context(symbols_by_file: dict[str, list[SymbolRecord]] = None, duckdb_store: DuckDBStore = None, target: str = None) -> dict[str, object]:
    if symbols_by_file is not None:
        matches = []
        for file_path, symbols in symbols_by_file.items():
            for symbol in symbols:
                if symbol.name == target or symbol.qualified_name == target:
                    matches.append({
                        "file": file_path,
                        "symbol": symbol.name,
                        "kind": symbol.kind,
                        "start_line": symbol.start_line,
                        "end_line": symbol.end_line,
                    })
        return {
            "target": target,
            "status": "found" if matches else "not_found",
            "matches": matches,
            "compact_results": matches,
            "compact_summary": _compact_summary(target or "", matches, "found" if matches else "not_found"),
        }
    elif duckdb_store is not None and target is not None:
        resolved_symbol_uid = symbol_uid_from_target(target)
        lookup_target = str(target or "").strip()
        if resolved_symbol_uid and resolved_symbol_uid == lookup_target:
            lookup_target = ""
        matches = []
        for item in resolve_candidates(
            duckdb_store,
            target=lookup_target,
            symbol_uid_value=resolved_symbol_uid,
            limit=12,
        ):
            symbol = item.get("symbol", {}) if isinstance(item, dict) else {}
            matches.append(
                {
                    "file": symbol.get("file_path", ""),
                    "symbol": symbol.get("name", ""),
                    "qualified_name": symbol.get("qualified_name", ""),
                    "kind": symbol.get("kind", ""),
                    "start_line": symbol.get("start_line"),
                    "end_line": symbol.get("end_line"),
                    "confidence": item.get("confidence", "low"),
                    "score": round(float(item.get("score", 0.0) or 0.0), 4),
                    "relevance": item.get("relevance", ""),
                }
            )
        status = "ambiguous" if ambiguity_status(matches) else "found" if matches else "not_found"
        return {
            "target": target,
            "status": status,
            "matches": matches,
            "warnings": ["Target resolution is ambiguous; pass file_path or kind to narrow it."] if status == "ambiguous" else [],
            "compact_results": matches,
            "compact_summary": _compact_summary(target, matches, status),
        }
    else:
        raise ValueError("Either symbols_by_file or duckdb_store and target must be provided")
