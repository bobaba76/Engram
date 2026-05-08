from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.api_impact_service import api_impact

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


def _unique(values: list[object], limit: int = 8) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def shape_check(repo_root: Path, duckdb_store: DuckDBStore, route: str = "", kuzu_store: KuzuStore | None = None) -> dict[str, object]:
    impact = api_impact(repo_root, duckdb_store, route=route, kuzu_store=kuzu_store)
    rows = []
    for item in impact.get("routes", []):
        if not isinstance(item, dict):
            continue
        shape = item.get("shape_check", {}) if isinstance(item.get("shape_check", {}), dict) else {}
        rows.append(
            {
                "route": item.get("route", ""),
                "status": shape.get("status", "UNKNOWN"),
                "response_shape": item.get("response_shape", {}),
                "consumer_field_reads": item.get("consumer_field_reads", []),
                "missing_fields": shape.get("missing_fields", []),
                "nested_missing_fields": shape.get("nested_missing_fields", []),
                "checked_consumers": shape.get("checked_consumers", 0),
                "risk": item.get("risk", "LOW"),
                "handlers": item.get("handlers", []),
                "consumers": item.get("consumers", []),
                "graph_contract": item.get("graph_contract", {}),
                "blast_radius": item.get("blast_radius", {}),
            }
        )
    mismatches = [row for row in rows if row.get("status") == "MISMATCH"]
    top_files = _unique([
        handler.get("file_path", "")
        for row in rows
        for handler in row.get("handlers", [])
        if isinstance(handler, dict)
    ] + [
        consumer.get("file_path", "")
        for row in rows
        for consumer in row.get("consumers", [])
        if isinstance(consumer, dict)
    ])
    top_symbols = _unique([
        handler.get("handler", "")
        for row in rows
        for handler in row.get("handlers", [])
        if isinstance(handler, dict)
    ] + [
        consumer.get("symbol", "") or consumer.get("function", "")
        for row in rows
        for consumer in row.get("consumers", [])
        if isinstance(consumer, dict)
    ])
    return {
        "repo_root": str(repo_root.resolve()),
        "route": route,
        "routes": rows,
        "total": len(rows),
        "mismatch_count": len(mismatches),
        "status": "MISMATCH" if mismatches else "OK" if rows else "NO_ROUTES",
        "compact_summary": {
            "target": route or str(repo_root.resolve()),
            "total": len(rows),
            "mismatch_count": len(mismatches),
            "status": "MISMATCH" if mismatches else "OK" if rows else "NO_ROUTES",
            "mismatches": [row.get("route", "") for row in mismatches[:8]],
            "top_files": top_files,
            "top_symbols": top_symbols,
        },
    }
