from pathlib import Path


def test_get_symbol_context_tool_passes_kuzu_store_to_service() -> None:
    source = Path("scripts/run_mcp.py").read_text(encoding="utf-8")

    assert 'get_symbol_context(duckdb_store=context["duckdb_store"], kuzu_store=_get_kuzu_store(repo), target=target)' in source


def test_mcp_startup_keeps_heavy_resources_lazy() -> None:
    source = Path("scripts/run_mcp.py").read_text(encoding="utf-8")
    before_index_status = source.split("def index_status", 1)[0]

    assert "_get_repo_context()" not in before_index_status
    assert "_get_kuzu_store()" not in before_index_status
    assert "prewarm_jina_model(" not in before_index_status


def test_reindex_project_defaults_to_background_and_registers_status_tool() -> None:
    source = Path("scripts/run_mcp.py").read_text(encoding="utf-8")

    assert "def reindex_project_tool(project_root: str = \"\", run_mode: str = INCREMENTAL, background: bool = True)" in source
    assert "def _reindex_job_root(job_id: str) -> Path:" in source
    assert "def _reindex_job_state_path(job_id: str) -> Path:" in source
    assert "def _persist_reindex_job(job: dict[str, Any]) -> None:" in source
    assert "def _load_reindex_job(job_id: str) -> dict[str, Any] | None:" in source
    assert "def _read_log_tail(path: Path" in source
    assert "_persist_reindex_job(reindex_jobs[job_id])" in source
    assert "job = _load_reindex_job(job_id)" in source
    assert 'for key in ("kuzu_store", "duckdb_store", "vector_store")' in source
    assert "subprocess.Popen" in source
    assert "(\"reindex_status\", reindex_status_tool" in source


def test_mcp_repo_aware_tools_echo_repo_metadata_and_warn_on_fallback() -> None:
    source = Path("scripts/run_mcp.py").read_text(encoding="utf-8")

    assert "def _add_repo_metadata(payload: Any, handler: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:" in source
    assert "payload.setdefault(\"repo_root\", str(resolved_repo_root))" in source
    assert "payload.setdefault(\"repo_name\", resolved_repo_root.name)" in source
    assert "\"mode\": selection_mode" in source
    assert "No repo argument provided; used selected repo" in source
    assert "server.register_tool(tool_name, _repo_safe_handler(handler), description=description)" in source
    assert "wrapped.__signature__ = signature" in source
