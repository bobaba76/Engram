from pathlib import Path

from services.realtime_index_service import WatchdogRealtimeIndexer


def test_realtime_snapshot_uses_scanner_style_filters(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("console.log('no')\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not indexable\n", encoding="utf-8")

    indexer = WatchdogRealtimeIndexer(tmp_path, tmp_path, log_callback=lambda message: None)

    assert indexer.snapshot() == {"src/app.py": (tmp_path / "src" / "app.py").stat().st_mtime_ns}


def test_realtime_queue_tracks_pending_paths(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "app.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    indexer = WatchdogRealtimeIndexer(tmp_path, tmp_path, log_callback=lambda message: None)

    indexer._queue_path(str(source))

    assert indexer.stats.pending_changes == 1
    assert indexer.stats.changed_paths == ["src/app.py"]
