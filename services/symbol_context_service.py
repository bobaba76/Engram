from models.entity_models import SymbolRecord
from services.graph_service import get_callers_and_callees
from services.symbol_resolution_service import ambiguity_status, resolve_candidates, symbol_uid_from_target
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore


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


def get_symbol_context(symbols_by_file: dict[str, list[SymbolRecord]] = None, duckdb_store: DuckDBStore = None, kuzu_store: KuzuStore = None, target: str = None) -> dict[str, object]:
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
        target_text = str(target or "").strip()
        synthetic_target = ""
        first_segment = target_text.split(".", 1)[0].removeprefix("field:")
        likely_field_root = first_segment in {"metrics", "chart_data", "branches", "data", "payload", "result", "response"}
        if target_text.startswith("field:"):
            synthetic_target = target_text
        elif "[]" in target_text or (likely_field_root and "." in target_text):
            synthetic_target = f"field:{target_text}"
        elif target_text.startswith("route:"):
            synthetic_target = target_text
        elif target_text.startswith("/"):
            synthetic_target = f"route:{target_text.rstrip('/') or '/'}"
        if synthetic_target and kuzu_store is not None:
            relation = "READS_FIELD" if synthetic_target.startswith("field:") else "FETCHES"
            edges = kuzu_store.edges_for_target(synthetic_target, relation=relation)
            matches = []
            for edge in edges:
                source = str(edge.get("source", "") or "")
                rows = duckdb_store.fetch_symbols_for_target(source, limit=1)
                symbol = rows[0] if rows else {}
                matches.append(
                    {
                        "file": symbol.get("file_path", ""),
                        "symbol": symbol.get("name", source.rsplit(".", 1)[-1]),
                        "qualified_name": source,
                        "kind": symbol.get("kind", ""),
                        "relation": relation,
                    }
                )
            status = "found" if matches else "not_found"
            return {
                "target": target,
                "resolved_graph_target": synthetic_target,
                "status": status,
                "matches": matches,
                "field_readers": matches if relation == "READS_FIELD" else [],
                "route_fetchers": matches if relation == "FETCHES" else [],
                "compact_results": matches,
                "compact_summary": {
                    **_compact_summary(target_text, matches, status),
                    "relation": relation,
                    "reader_count": len(matches) if relation == "READS_FIELD" else 0,
                    "fetcher_count": len(matches) if relation == "FETCHES" else 0,
                },
            }
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
        graph_context = {}
        if kuzu_store is not None and matches:
            graph_context = get_callers_and_callees(kuzu_store, str(matches[0].get("qualified_name") or matches[0].get("symbol") or target))
        summary = _compact_summary(target, matches, status)
        if graph_context:
            graph_summary = graph_context.get("compact_summary", {}) if isinstance(graph_context, dict) else {}
            summary["caller_count"] = graph_summary.get("caller_count", 0)
            summary["callee_count"] = graph_summary.get("callee_count", 0)
            summary["relation_counts"] = graph_summary.get("relation_counts", {})
        return {
            "target": target,
            "status": status,
            "matches": matches,
            "warnings": ["Target resolution is ambiguous; pass file_path or kind to narrow it."] if status == "ambiguous" else [],
            "graph_context": graph_context,
            "categorized_references": graph_context.get("categorized_references", {}) if isinstance(graph_context, dict) else {},
            "relation_counts": graph_context.get("relation_counts", {}) if isinstance(graph_context, dict) else {},
            "compact_results": matches,
            "compact_summary": summary,
        }
    else:
        raise ValueError("Either symbols_by_file or duckdb_store and target must be provided")
