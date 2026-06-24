from pathlib import Path


def test_get_symbol_context_tool_passes_kuzu_store_to_service() -> None:
    source = Path("mcp_server/tool_handlers.py").read_text(encoding="utf-8")

    assert 'get_symbol_context(duckdb_store=context["duckdb_store"], kuzu_store=session.get_kuzu_store(repo), target=target)' in source


def test_mcp_startup_prewarms_embedding_model() -> None:
    handlers = Path("mcp_server/tool_handlers.py").read_text(encoding="utf-8")
    startup = Path("scripts/run_mcp.py").read_text(encoding="utf-8")

    # Prewarm is triggered both at startup (non-blocking daemon thread) and
    # lazily from semantic_code_search_tool as a fallback.
    assert "prewarm_jina_model" in handlers
    assert "semantic_code_search_tool" in handlers
    assert "prewarm_jina_model" in startup


def test_reindex_project_defaults_to_background_and_registers_status_tool() -> None:
    handlers = Path("mcp_server/tool_handlers.py").read_text(encoding="utf-8")
    session = Path("mcp_server/mcp_session.py").read_text(encoding="utf-8")

    assert "def reindex_project_tool(" in handlers
    assert "def _reindex_job_root(self, job_id: str) -> Path:" in session
    assert "def _reindex_job_state_path(self, job_id: str) -> Path:" in session
    assert "def _persist_reindex_job(self, job: dict[str, Any]) -> None:" in session
    assert "def _load_reindex_job(self, job_id: str) -> dict[str, Any] | None:" in session
    assert "def _read_log_tail(path: Path" in session  # static method, no self
    assert "_persist_reindex_job(self.reindex_jobs[job_id])" in session
    assert "job = self._load_reindex_job(job_id)" in session
    assert 'for key in ("kuzu_store", "duckdb_store", "vector_store")' in session
    assert "subprocess.Popen" in session
    assert "(\"reindex_status\", reindex_status_tool" in handlers


def test_mcp_repo_aware_tools_echo_repo_metadata_and_warn_on_fallback() -> None:
    source = Path("scripts/run_mcp.py").read_text(encoding="utf-8")

    assert "def _make_repo_safe_handler(" in source
    assert "payload.setdefault(\"repo_root\", str(resolved_repo_root))" in source
    assert "payload.setdefault(\"repo_name\", resolved_repo_root.name)" in source
    assert "\"mode\": selection_mode" in source
    assert "No repo argument provided; used default repo" in source
    assert "server.register_tool(tool_name, _make_repo_safe_handler(session, handler), description=description)" in source
    assert "wrapped.__signature__ = signature" in source
