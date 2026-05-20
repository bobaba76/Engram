from pathlib import Path

import pytest

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


def test_scan_repo_streams_hash_without_reading_whole_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "main.py"
    source.write_text("print('visible')\n", encoding="utf-8")

    def fail_read_bytes(self: Path) -> bytes:
        raise AssertionError("scan_repo should not read full file payloads")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    records = scan_repo(tmp_path)

    assert [record.path for record in records] == ["main.py"]
    assert records[0].sha256


def test_scan_repo_skips_files_larger_than_configured_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    small = tmp_path / "small.py"
    large = tmp_path / "large.py"
    small.write_text("print('small')\n", encoding="utf-8")
    large.write_text("x = '" + ("a" * 128) + "'\n", encoding="utf-8")
    monkeypatch.setenv("CODER_SCAN_MAX_FILE_BYTES", "32")

    progress: list[str] = []
    records = scan_repo(tmp_path, progress_callback=progress.append)

    assert [record.path for record in records] == ["small.py"]
    assert any("scan skipped 1 files larger than CODER_SCAN_MAX_FILE_BYTES=32" in message for message in progress)
