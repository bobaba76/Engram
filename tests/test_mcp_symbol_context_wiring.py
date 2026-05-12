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
    assert "subprocess.Popen" in source
    assert "(\"reindex_status\", reindex_status_tool" in source
