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
    ".s": "assembly",
    ".asm": "assembly",
    ".inc": "assembly_include",
    ".cs": "csharp",
    ".java": "java",
    ".csproj": "csharp_project",
    ".sln": "csharp_solution",
    ".vcxproj": "native_project",
    ".mcp": "mplab_project",
    ".mcw": "mplab_workspace",
    ".mptags": "mplab_tags",
    ".scl": "mplab_script",
    ".plt": "mplab_plot",
    ".pas": "object_pascal",
    ".pp": "object_pascal",
    ".dpr": "object_pascal_project",
    ".dpk": "object_pascal_package",
    ".lpr": "object_pascal_project",
    ".lfm": "object_pascal_form",
    ".dfm": "object_pascal_form",
    ".dproj": "object_pascal_project",
    ".groupproj": "object_pascal_project",
    ".lpi": "object_pascal_project",
    ".lpk": "object_pascal_package",
    ".cmake": "native_build",
    ".json": "json",
    ".rb": "ruby",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".dart": "dart",
    ".lua": "lua",
    ".r": "r",
    ".m": "objective_c",
    ".mm": "objective_cpp",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".fs": "fsharp",
    ".fsx": "fsharp",
    ".vb": "vbnet",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".vue": "vue",
    ".svelte": "svelte",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
}

SUPPORTED_FILE_NAMES = {
    "compile_commands.json": "native_build",
    "cmakelists.txt": "native_build",
    "makefile": "native_build",
    "dockerfile": "dockerfile",
    "gemfile": "ruby_project",
    "rakefile": "ruby_project",
    "go.mod": "go_project",
    "cargo.toml": "rust_project",
    "composer.json": "php_project",
    "pubspec.yaml": "dart_project",
    "mix.exs": "elixir_project",
    "package.swift": "swift_project",
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

SAMPLE_BYTES = 20_000
HASH_CHUNK_BYTES = 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024


def _split_env_patterns(name: str) -> tuple[str, ...]:
    raw_value = os.environ.get(name, "")
    return tuple(part.strip() for part in raw_value.split(",") if part.strip())


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(0, value)


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


def _read_sample(path: Path, limit: int = SAMPLE_BYTES) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def scan_repo(repo_root: Path, excluded_dirs: Iterable[str] = (), progress_callback: Callable[[str], None] | None = None) -> list[FileRecord]:
    excluded = {part for part in excluded_dirs if part}
    configured_includes = _split_env_patterns("CODER_SCAN_INCLUDE_PATTERNS")
    configured_excludes = (*_split_env_patterns("CODER_SCAN_EXCLUDE_PATTERNS"), *_load_gitignore_patterns(repo_root))
    max_file_bytes = _env_int("CODER_SCAN_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES)
    records: list[FileRecord] = []
    visited_dirs = 0
    candidate_files = 0
    skipped_large_files = 0
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
            stat = path.stat()
            if max_file_bytes and stat.st_size > max_file_bytes:
                skipped_large_files += 1
                continue
            sample = _read_sample(path)
            if _should_exclude_file(path, sample):
                continue
            records.append(
                FileRecord(
                    path=str(path.relative_to(repo_root)).replace("\\", "/"),
                    language=language,
                    size_bytes=stat.st_size,
                    sha256=_sha256_file(path),
                    modified_time=stat.st_mtime,
                )
            )
        if progress_callback is not None and (visited_dirs == 1 or visited_dirs % 100 == 0):
            progress_callback(f"scan progress: {visited_dirs} directories visited, {candidate_files} files checked, {len(records)} indexable")
    records.sort(key=lambda record: record.path)
    if progress_callback is not None:
        progress_callback(f"scan progress: {visited_dirs} directories visited, {candidate_files} files checked, {len(records)} indexable")
        if skipped_large_files:
            progress_callback(
                f"scan skipped {skipped_large_files} files larger than CODER_SCAN_MAX_FILE_BYTES={max_file_bytes}"
            )
    return records
