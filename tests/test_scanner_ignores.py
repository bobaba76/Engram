from pathlib import Path

from indexing.scanner import scan_repo


def test_scan_repo_respects_gitignore_directory(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored_dir/\n", encoding="utf-8")
    ignored = tmp_path / "ignored_dir"
    included = tmp_path / "included"
    ignored.mkdir()
    included.mkdir()
    (ignored / "hidden.py").write_text("print('hidden')\n", encoding="utf-8")
    (included / "visible.py").write_text("print('visible')\n", encoding="utf-8")

    records = scan_repo(tmp_path)

    assert [record.path for record in records] == ["included/visible.py"]
