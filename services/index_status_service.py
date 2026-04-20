def get_index_status(manifest: dict[str, object]) -> dict[str, object]:
    return {
        "status": manifest.get("status", "missing"),
        "run_id": manifest.get("run_id", ""),
        "repo_root": manifest.get("repo_root", ""),
        "project_root": manifest.get("project_root", ""),
        "data_dir": manifest.get("data_dir", ""),
        "embedding_runtime": manifest.get("embedding_runtime", {}),
        "mcp_resolved_repo_root": manifest.get("mcp_resolved_repo_root", ""),
        "mcp_resolution_source": manifest.get("mcp_resolution_source", ""),
        "counts": manifest.get("counts", {}),
        "versions": manifest.get("versions", {}),
    }
