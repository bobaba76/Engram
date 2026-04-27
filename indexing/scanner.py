import hashlib
from pathlib import Path
from typing import Iterable

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


def scan_repo(repo_root: Path, excluded_dirs: Iterable[str] = ()) -> list[FileRecord]:
    excluded = {part for part in excluded_dirs if part}
    records: list[FileRecord] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if excluded.intersection(path.parts):
            continue
        if ".venv" in path.parts or "__pycache__" in path.parts or path.parts[-1].startswith("."):
            continue
        language = SUPPORTED_FILE_NAMES.get(path.name.lower()) or SUPPORTED_EXTENSIONS.get(path.suffix.lower())
        if language is None:
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
    records.sort(key=lambda record: record.path)
    return records
