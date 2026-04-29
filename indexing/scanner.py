import hashlib
import fnmatch
import os
from pathlib import Path
from typing import Callable, Iterable

from models.entity_models import FileRecord


SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "typescript",
    ".jsx": "tsx",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".csproj": "csharp_project",
    ".sln": "csharp_solution",
    ".vcxproj": "native_project",
    ".cmake": "native_build",
    ".json": "json",
}

SUPPORTED_FILE_NAMES = {
    "compile_commands.json": "native_build",
    "cmakelists.txt": "native_build",
    "makefile": "native_build",
}

EXCLUDED_FILE_NAMES = {
    "chart.js",
    "chart.min.js",
}

EXCLUDED_PATH_PARTS = {
    "site-packages",
    "public",
    "static",
    "assets",
    "vendor",
    "dist",
    "build",
}


def _split_env_patterns(name: str) -> tuple[str, ...]:
    raw_value = os.environ.get(name, "")
    return tuple(part.strip() for part in raw_value.split(",") if part.strip())


def _load_gitignore_patterns(repo_root: Path) -> list[str]:
    patterns: list[str] = []
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        return patterns
    for line in gitignore.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            continue
        patterns.append(stripped)
    return patterns


def _matches_pattern(path: Path, repo_root: Path, pattern: str) -> bool:
    relative = path.relative_to(repo_root).as_posix()
    normalized = pattern.strip().replace("\\", "/")
    if not normalized:
        return False
    if normalized.endswith("/"):
        prefix = normalized.strip("/")
        return relative == prefix or relative.startswith(f"{prefix}/")
    if normalized.startswith("/"):
        return fnmatch.fnmatch(relative, normalized.lstrip("/"))
    return (
        fnmatch.fnmatch(relative, normalized)
        or fnmatch.fnmatch(path.name, normalized)
        or any(fnmatch.fnmatch(part, normalized) for part in path.parts)
    )


def _is_ignored(path: Path, repo_root: Path, patterns: Iterable[str]) -> bool:
    return any(_matches_pattern(path, repo_root, pattern) for pattern in patterns)


def _looks_minified(path: Path, payload: bytes) -> bool:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if name.endswith(".min.js") or name.endswith(".min.jsx") or name.endswith(".min.ts") or name.endswith(".min.tsx"):
        return True
    if suffix not in {".js", ".jsx", ".ts", ".tsx"}:
        return False
    if len(payload) < 5000:
        return False
    sample = payload[:20000].decode("utf-8", errors="ignore")
    if not sample:
        return False
    line_count = sample.count("\n") + 1
    longest_line = max((len(line) for line in sample.splitlines() or [sample]), default=0)
    return line_count <= 20 and longest_line >= 2000


def _should_exclude_file(path: Path, payload: bytes) -> bool:
    normalized_parts = {part.lower() for part in path.parts}
    if path.name.lower() in EXCLUDED_FILE_NAMES:
        return True
    if EXCLUDED_PATH_PARTS.intersection(normalized_parts) and path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".map"}:
        return True
    return _looks_minified(path, payload)


def scan_repo(repo_root: Path, excluded_dirs: Iterable[str] = (), progress_callback: Callable[[str], None] | None = None) -> list[FileRecord]:
    excluded = {part for part in excluded_dirs if part}
    configured_includes = _split_env_patterns("CODER_SCAN_INCLUDE_PATTERNS")
    configured_excludes = (*_split_env_patterns("CODER_SCAN_EXCLUDE_PATTERNS"), *_load_gitignore_patterns(repo_root))
    records: list[FileRecord] = []
    visited_dirs = 0
    candidate_files = 0
    for root, dir_names, file_names in os.walk(repo_root):
        visited_dirs += 1
        root_path = Path(root)
        if configured_excludes and root_path != repo_root and _is_ignored(root_path, repo_root, configured_excludes):
            dir_names[:] = []
            continue
        dir_names[:] = [
            dir_name
            for dir_name in dir_names
            if dir_name not in excluded
            and dir_name != "__pycache__"
            and not dir_name.startswith(".")
            and not _is_ignored(root_path / dir_name, repo_root, configured_excludes)
        ]
        for file_name in file_names:
            candidate_files += 1
            path = root_path / file_name
            if file_name.startswith("."):
                continue
            if excluded.intersection(path.parts):
                continue
            if configured_excludes and _is_ignored(path, repo_root, configured_excludes):
                continue
            language = SUPPORTED_FILE_NAMES.get(path.name.lower()) or SUPPORTED_EXTENSIONS.get(path.suffix.lower())
            if language is None:
                continue
            if configured_includes and not _is_ignored(path, repo_root, configured_includes):
                continue
            payload = path.read_bytes()
            if _should_exclude_file(path, payload):
                continue
            stat = path.stat()
            records.append(
                FileRecord(
                    path=str(path.relative_to(repo_root)).replace("\\", "/"),
                    language=language,
                    size_bytes=stat.st_size,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    modified_time=stat.st_mtime,
                )
            )
        if progress_callback is not None and (visited_dirs == 1 or visited_dirs % 100 == 0):
            progress_callback(f"scan progress: {visited_dirs} directories visited, {candidate_files} files checked, {len(records)} indexable")
    records.sort(key=lambda record: record.path)
    if progress_callback is not None:
        progress_callback(f"scan progress: {visited_dirs} directories visited, {candidate_files} files checked, {len(records)} indexable")
    return records
