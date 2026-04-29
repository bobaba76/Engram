import json


def get_index_status(manifest: dict[str, object]) -> dict[str, object]:
    return {
        "status": manifest.get("status", "missing"),
        "run_id": manifest.get("run_id", ""),
        "counts": manifest.get("counts", {}),
        "versions": manifest.get("versions", {}),
        "manifest": manifest,
    }


def _decode_json_field(value: object, fallback):
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def get_recent_runs(duckdb_store, limit: int = 10) -> dict[str, object]:
    rows = duckdb_store.runs.fetch_recent(limit=limit)
    runs: list[dict[str, object]] = []
    for row in rows:
        runs.append(
            {
                "run_id": row.get("run_id", ""),
                "run_mode": row.get("run_mode", ""),
                "status": row.get("status", ""),
                "file_count": int(row.get("file_count") or 0),
                "symbol_count": int(row.get("symbol_count") or 0),
                "chunk_count": int(row.get("chunk_count") or 0),
                "finding_count": int(row.get("finding_count") or 0),
                "stage_results": _decode_json_field(row.get("stage_results_json"), []),
                "warnings": _decode_json_field(row.get("warnings_json"), []),
                "errors": _decode_json_field(row.get("errors_json"), []),
                "report_paths": _decode_json_field(row.get("report_paths_json"), {}),
                "created_at": row.get("created_at"),
            }
        )
    return {
        "run_count": len(runs),
        "runs": runs,
        "compact_summary": {
            "run_count": len(runs),
            "latest_run_id": runs[0]["run_id"] if runs else "",
            "latest_status": runs[0]["status"] if runs else "missing",
        },
    }


def get_run_metrics(duckdb_store, run_id: str) -> dict[str, object]:
    row = duckdb_store.runs.fetch_by_run_id(run_id)
    if row is None:
        return {"run_id": run_id, "status": "missing"}
    return {
        "run_id": row.get("run_id", ""),
        "run_mode": row.get("run_mode", ""),
        "status": row.get("status", ""),
        "file_count": int(row.get("file_count") or 0),
        "symbol_count": int(row.get("symbol_count") or 0),
        "chunk_count": int(row.get("chunk_count") or 0),
        "finding_count": int(row.get("finding_count") or 0),
        "stage_results": _decode_json_field(row.get("stage_results_json"), []),
        "warnings": _decode_json_field(row.get("warnings_json"), []),
        "errors": _decode_json_field(row.get("errors_json"), []),
        "report_paths": _decode_json_field(row.get("report_paths_json"), {}),
        "created_at": row.get("created_at"),
    }
