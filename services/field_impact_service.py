from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.api_impact_service import api_impact

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


def _normalize_field(field: str) -> str:
    return str(field or "").strip().removeprefix("field:")


def _field_matches(candidate: str, requested: str) -> bool:
    candidate_field = _normalize_field(candidate)
    requested_field = _normalize_field(requested)
    return bool(candidate_field and requested_field) and (
        candidate_field == requested_field
        or candidate_field.endswith("." + requested_field)
        or requested_field.endswith("." + candidate_field)
    )


def _unique(values: list[object], limit: int = 12) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def _unique_readers(values: list[object], limit: int = 12) -> list[str]:
    seen: list[str] = []
    tails: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        tail = text.rsplit(".", 1)[-1]
        if not text or text in seen or tail in tails:
            continue
        seen.append(text)
        tails.add(tail)
        if len(seen) >= limit:
            break
    return seen


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def field_impact(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    field: str,
    route: str = "",
    kuzu_store: KuzuStore | None = None,
) -> dict[str, object]:
    requested_field = _normalize_field(field)
    impact = api_impact(repo_root, duckdb_store, route=route, kuzu_store=kuzu_store)
    rows: list[dict[str, object]] = []
    for route_row in impact.get("routes", []) if isinstance(impact, dict) else []:
        if not isinstance(route_row, dict):
            continue
        graph_contract = route_row.get("graph_contract", {}) if isinstance(route_row.get("graph_contract", {}), dict) else {}
        shape = route_row.get("shape_check", {}) if isinstance(route_row.get("shape_check", {}), dict) else {}
        consumer_matches = []
        for consumer in route_row.get("consumers", []) if isinstance(route_row.get("consumers", []), list) else []:
            if not isinstance(consumer, dict):
                continue
            reads = [*_as_list(consumer.get("accessed_keys", [])), *_as_list(consumer.get("nested_accesses", []))]
            matched_reads = [str(read) for read in reads if _field_matches(str(read), requested_field)]
            if matched_reads:
                consumer_matches.append(
                    {
                        "file_path": consumer.get("file_path", ""),
                        "function": consumer.get("function", ""),
                        "symbol": consumer.get("symbol", ""),
                        "consumer_type": consumer.get("consumer_type", ""),
                        "matched_reads": _unique(matched_reads),
                    }
                )
        graph_readers = [
            reader
            for reader in graph_contract.get("field_readers", []) if isinstance(graph_contract.get("field_readers", []), list)
            if isinstance(reader, dict) and _field_matches(str(reader.get("field", "")), requested_field)
        ]
        missing = [str(item) for item in [*_as_list(shape.get("missing_fields", [])), *_as_list(shape.get("nested_missing_fields", []))] if _field_matches(str(item), requested_field)]
        if not consumer_matches and not graph_readers and not missing:
            continue
        readers = _unique_readers([
            reader.get("symbol", "")
            for reader in graph_readers
            if isinstance(reader, dict)
        ] + [
            item.get("symbol", "") or item.get("function", "")
            for item in consumer_matches
            if isinstance(item, dict)
        ])
        files = _unique([
            item.get("file_path", "")
            for item in consumer_matches
            if isinstance(item, dict)
        ] + [
            reader.get("file_path", "")
            for reader in graph_readers
            if isinstance(reader, dict)
        ])
        rows.append(
            {
                "route": route_row.get("route", ""),
                "field": requested_field,
                "readers": readers,
                "files": files,
                "consumer_matches": consumer_matches,
                "graph_readers": graph_readers,
                "shape_status": shape.get("status", "UNKNOWN"),
                "missing_from_response": _unique(missing),
                "risk": "HIGH" if missing else "MEDIUM" if readers else "LOW",
                "summary": f"{requested_field} is read by {', '.join(readers) if readers else 'no detected consumers'} on {route_row.get('route', '')}.",
            }
        )
    return {
        "repo_root": str(repo_root.resolve()),
        "route": route,
        "field": requested_field,
        "matches": rows,
        "total": len(rows),
        "risk": "HIGH" if any(row.get("risk") == "HIGH" for row in rows) else "MEDIUM" if rows else "LOW",
        "warnings": [] if rows else [f"No consumers or response-shape issues found for field {requested_field}."],
        "compact_summary": {
            "target": f"{route or '*'}:{requested_field}",
            "match_count": len(rows),
            "routes": _unique([row.get("route", "") for row in rows]),
            "top_files": _unique([file_path for row in rows for file_path in row.get("files", []) if isinstance(row, dict)]),
            "top_symbols": _unique_readers([reader for row in rows for reader in row.get("readers", []) if isinstance(row, dict)]),
            "missing_from_response": _unique([item for row in rows for item in row.get("missing_from_response", []) if isinstance(row, dict)]),
            "risk": "HIGH" if any(row.get("risk") == "HIGH" for row in rows) else "MEDIUM" if rows else "LOW",
        },
    }
