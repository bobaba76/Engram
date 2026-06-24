from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.run_modes import INCREMENTAL
from config.settings import DEFAULT_SCAN_EXCLUDED_DIRS
from indexing.scanner import SUPPORTED_EXTENSIONS, SUPPORTED_FILE_NAMES, _is_ignored, _load_gitignore_patterns, _split_env_patterns

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    FileSystemEventHandler = None
    Observer = None


@dataclass(slots=True)
class RealtimeIndexStats:
    watched_root: str
    poll_interval_seconds: float
    debounce_seconds: float
    known_files: int = 0
    pending_changes: int = 0
    reindex_count: int = 0
    last_reindex_return_code: int | None = None
    last_reindex_at: float | None = None
    last_change_at: float | None = None
    last_error: str = ""
    changed_paths: list[str] = field(default_factory=list)
    watcher_backend: str = "polling"


def _default_log(message: str) -> None:
    print(f"[realtime-index] {message}", flush=True)


class PollingRealtimeIndexer:
    def __init__(
        self,
        repo_root: Path,
        coder_root: Path,
        poll_interval_seconds: float = 2.0,
        debounce_seconds: float = 1.0,
        status_interval_seconds: float = 30.0,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.coder_root = coder_root.resolve()
        self.poll_interval_seconds = max(float(poll_interval_seconds), 0.25)
        self.debounce_seconds = max(float(debounce_seconds), 0.25)
        self.status_interval_seconds = max(float(status_interval_seconds), 5.0)
        self.log = log_callback or _default_log
        self._known: dict[str, int] = {}
        self._pending: set[str] = set()
        self._last_change_at: float | None = None
        self._indexing = False
        self._last_status_at = 0.0
        self._excluded_dirs = set(DEFAULT_SCAN_EXCLUDED_DIRS)
        self._configured_excludes = (*_split_env_patterns("CODER_SCAN_EXCLUDE_PATTERNS"), *_load_gitignore_patterns(self.repo_root))
        self._configured_includes = _split_env_patterns("CODER_SCAN_INCLUDE_PATTERNS")
        self.stats = RealtimeIndexStats(
            watched_root=str(self.repo_root),
            poll_interval_seconds=self.poll_interval_seconds,
            debounce_seconds=self.debounce_seconds,
        )

    def _relative_path(self, path: Path) -> str | None:
        try:
            return str(path.resolve().relative_to(self.repo_root)).replace("\\", "/")
        except (OSError, ValueError):
            return None

    def _is_watchable_path(self, path: Path) -> bool:
        relative = self._relative_path(path)
        if not relative:
            return False
        parts = Path(relative).parts
        if any(part in self._excluded_dirs or part == "__pycache__" or part.startswith(".") for part in parts):
            return False
        if self._configured_excludes and _is_ignored(path, self.repo_root, self._configured_excludes):
            return False
        name = path.name.lower()
        if name.endswith((".tmp", ".temp", ".swp", ".lock", ".log")):
            return False
        if path.is_file():
            language = SUPPORTED_FILE_NAMES.get(path.name.lower()) or SUPPORTED_EXTENSIONS.get(path.suffix.lower())
            if language is None:
                return False
            if self._configured_includes and not _is_ignored(path, self.repo_root, self._configured_includes):
                return False
        return True

    def snapshot(self) -> dict[str, int]:
        files: dict[str, int] = {}
        for path in self.repo_root.rglob("*"):
            if not path.is_file():
                continue
            if not self._is_watchable_path(path):
                continue
            try:
                relative = self._relative_path(path)
                if relative:
                    files[relative] = path.stat().st_mtime_ns
            except OSError:
                continue
        return files

    def _queue_relative(self, relative_text: str) -> None:
        if not relative_text:
            return
        self._pending.add(relative_text)
        self._last_change_at = time.time()
        self.stats.last_change_at = self._last_change_at
        self.stats.changed_paths = sorted(self._pending)[-25:]
        self.stats.pending_changes = len(self._pending)

    def scan_once(self) -> list[str]:
        current = self.snapshot()
        changed = sorted(
            path
            for path, mtime in current.items()
            if self._known.get(path) != mtime
        )
        deleted = sorted(path for path in self._known if path not in current)
        self._known = current
        touched = changed + deleted
        if touched:
            for path in touched:
                self._queue_relative(path)
        self.stats.known_files = len(self._known)
        self.stats.pending_changes = len(self._pending)
        return touched

    def maybe_reindex(self) -> bool:
        if not self._pending or self._last_change_at is None:
            return False
        if self._indexing:
            return False
        if time.time() - self._last_change_at < self.debounce_seconds:
            return False
        pending_snapshot = sorted(self._pending)
        command = [
            sys.executable,
            str(self.coder_root / "scripts" / "run_index.py"),
            str(self.repo_root),
            INCREMENTAL,
        ]
        self._indexing = True
        self.log(f"indexing {len(pending_snapshot)} changed paths after {self.debounce_seconds:g}s debounce")
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.coder_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                stdin=subprocess.DEVNULL,
            )
            self.stats.reindex_count += 1
            self.stats.last_reindex_return_code = completed.returncode
            self.stats.last_reindex_at = time.time()
            self.stats.last_error = completed.stderr[-2000:] if completed.returncode else ""
            if completed.returncode:
                self.log(f"incremental index failed with code {completed.returncode}")
            else:
                self.log("incremental index completed")
            self._pending.difference_update(pending_snapshot)
            self.stats.pending_changes = len(self._pending)
            self.stats.changed_paths = sorted(self._pending)[-25:]
        finally:
            self._indexing = False
        return True

    def maybe_log_status(self) -> None:
        now = time.time()
        if now - self._last_status_at < self.status_interval_seconds:
            return
        self._last_status_at = now
        self.log(
            f"watching {self.stats.known_files} files, pending={self.stats.pending_changes}, "
            f"runs={self.stats.reindex_count}, backend={self.stats.watcher_backend}"
        )

    def run_forever(self) -> None:
        self._known = self.snapshot()
        self.stats.known_files = len(self._known)
        self.log(f"initial snapshot: {self.stats.known_files} indexable files")
        while True:
            self.scan_once()
            self.maybe_reindex()
            self.maybe_log_status()
            time.sleep(self.poll_interval_seconds)


class WatchdogRealtimeIndexer(PollingRealtimeIndexer):
    def _queue_path(self, path: str) -> None:
        try:
            relative = Path(path).resolve().relative_to(self.repo_root)
        except ValueError:
            return
        relative_text = str(relative).replace("\\", "/")
        absolute = self.repo_root / relative
        if absolute.exists() and not self._is_watchable_path(absolute):
            return
        if not absolute.exists() and any(part in self._excluded_dirs or part == "__pycache__" or part.startswith(".") for part in relative.parts):
            return
        self._queue_relative(relative_text)

    def run_forever(self) -> None:
        if Observer is None or FileSystemEventHandler is None:
            self.stats.watcher_backend = "polling"
            self.log("watchdog not available; using polling fallback")
            super().run_forever()
            return

        indexer = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event) -> None:
                if not event.is_directory:
                    indexer._queue_path(event.src_path)

            def on_modified(self, event) -> None:
                if not event.is_directory:
                    indexer._queue_path(event.src_path)

            def on_deleted(self, event) -> None:
                if not event.is_directory:
                    indexer._queue_path(event.src_path)

            def on_moved(self, event) -> None:
                if not event.is_directory:
                    indexer._queue_path(event.src_path)
                    indexer._queue_path(event.dest_path)

        self._known = self.snapshot()
        self.stats.known_files = len(self._known)
        self.stats.watcher_backend = "watchdog"
        observer = Observer()
        observer.schedule(Handler(), str(self.repo_root), recursive=True)
        observer.start()
        self.log(f"initial snapshot: {self.stats.known_files} indexable files")
        self.log("watchdog backend active")
        try:
            while True:
                self.maybe_reindex()
                self.maybe_log_status()
                time.sleep(self.poll_interval_seconds)
        finally:
            observer.stop()
            observer.join()
