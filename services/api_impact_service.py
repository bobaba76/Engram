from __future__ import annotations

from pathlib import Path

from storage.duckdb_store import DuckDBStore
from services.route_map_service import route_map


def api_impact(repo_root: Path, duckdb_store: DuckDBStore, route: str = "") -> dict[str, object]:
    mapping = route_map(repo_root, duckdb_store, route=route)
    rows = []
    for item in mapping.get("routes", []):
        handlers = item.get("handlers", []) if isinstance(item, dict) else []
        consumers = item.get("consumers", []) if isinstance(item, dict) else []
        response_keys = sorted({key for handler in handlers for key in handler.get("response_keys", []) if key})
        consumer_keys = sorted({key for consumer in consumers for key in consumer.get("accessed_keys", []) if key})
        nested_consumer_paths = sorted({path for consumer in consumers for path in consumer.get("nested_accesses", []) if path})
        missing = [key for key in consumer_keys if key not in response_keys]
        nested_missing = [path for path in nested_consumer_paths if path.split(".", 1)[0] not in response_keys]
        rows.append(
            {
                "route": item.get("route", ""),
                "handlers": handlers,
                "consumers": consumers,
                "response_keys": response_keys,
                "consumer_keys": consumer_keys,
                "nested_consumer_paths": nested_consumer_paths,
                "mismatch": bool(missing),
                "missing_keys": missing,
                "nested_mismatch": bool(nested_missing),
                "nested_missing_paths": nested_missing,
                "risk": "HIGH" if len(consumers) >= 5 or missing or nested_missing else "MEDIUM" if consumers else "LOW",
            }
        )
    return {
        "repo_root": str(repo_root.resolve()),
        "route": route,
        "routes": rows,
        "total": len(rows),
        "compact_summary": {
            "target": route or str(repo_root.resolve()),
            "total": len(rows),
            "top_routes": [row.get("route", "") for row in rows[:8]],
            "mismatches": [row.get("route", "") for row in rows if row.get("mismatch")][:8],
        },
    }
