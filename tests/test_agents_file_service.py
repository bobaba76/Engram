from pathlib import Path

from services.agents_file_service import CODER_BLOCK_END, CODER_BLOCK_START, update_agents_file


def test_update_agents_file_creates_coder_block(tmp_path: Path) -> None:
    result = update_agents_file(tmp_path)

    assert result["updated"] is True
    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert CODER_BLOCK_START in content
    assert CODER_BLOCK_END in content
    assert "coder MCP - Primary Code Intelligence" in content
    assert "GitNexus" not in content


def test_update_agents_file_preserves_existing_content_and_replaces_old_block(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "# Human Notes\n\n"
        "<!-- coder:start -->\nold coder text\n<!-- coder:end -->\n\n"
        "<!-- gitnexus:start -->\n# GitNexus\nFallback notes\n<!-- gitnexus:end -->\n",
        encoding="utf-8",
    )

    result = update_agents_file(tmp_path)

    assert result["updated"] is True
    content = agents.read_text(encoding="utf-8")
    assert "# Human Notes" in content
    assert "old coder text" not in content
    assert content.count(CODER_BLOCK_START) == 1
    assert content.count(CODER_BLOCK_END) == 1
    assert "<!-- gitnexus:start -->" in content
    assert "Fallback notes" in content


def test_update_agents_file_can_be_disabled(tmp_path: Path) -> None:
    result = update_agents_file(tmp_path, enabled=False)

    assert result["enabled"] is False
    assert result["updated"] is False
    assert not (tmp_path / "AGENTS.md").exists()
