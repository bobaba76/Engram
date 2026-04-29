import hashlib
import re
from pathlib import Path

from models.entity_models import ChunkRecord, SymbolRecord

MAX_CHUNK_LINES = 100
CHUNK_OVERLAP_LINES = 12
MAX_CHUNK_CONTENT_CHARS = 12000
MINIFIED_LINE_LENGTH_THRESHOLD = 2000
COMMENT_PREFIXES = ("#", "//", "/*", "*", '"""', "'''")
CHUNKING_VERSION = "2"


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _line_ranges(start_line: int, end_line: int, max_chunk_lines: int = MAX_CHUNK_LINES, overlap_lines: int = CHUNK_OVERLAP_LINES) -> list[tuple[int, int]]:
    total_lines = max(end_line - start_line + 1, 1)
    if total_lines <= max_chunk_lines:
        return [(start_line, end_line)]
    step = max(max_chunk_lines - overlap_lines, 1)
    ranges: list[tuple[int, int]] = []
    current_start = start_line
    while current_start <= end_line:
        current_end = min(current_start + max_chunk_lines - 1, end_line)
        ranges.append((current_start, current_end))
        if current_end >= end_line:
            break
        current_start += step
    return ranges


def _is_non_core_blob(source_lines: list[str]) -> bool:
    if not source_lines:
        return False
    longest_line = max((len(line) for line in source_lines), default=0)
    return len(source_lines) <= 20 and longest_line >= MINIFIED_LINE_LENGTH_THRESHOLD


def _safe_chunk_content(source_lines: list[str], part_start: int, part_end: int, file_path: str) -> str:
    line_count = max(len(source_lines), 1)
    safe_start = min(max(part_start, 1), line_count)
    safe_end = min(max(part_end, safe_start), line_count)
    selected_lines = source_lines[safe_start - 1:safe_end]
    content = "\n".join(selected_lines)
    if len(content) <= MAX_CHUNK_CONTENT_CHARS:
        return content
    return f"[content omitted: large non-core or minified blob excluded from chunk storage] {file_path}:{safe_start}-{safe_end}"


def _attach_leading_context(source_lines: list[str], start_line: int) -> int:
    if not source_lines:
        return 1
    line_index = min(max(start_line - 2, 0), len(source_lines) - 1)
    while line_index >= 0:
        stripped = source_lines[line_index].strip()
        if not stripped:
            break
        if stripped.startswith(COMMENT_PREFIXES) or stripped.startswith("@"):
            line_index -= 1
            continue
        break
    return line_index + 2


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _split_points_for_range(source_lines: list[str], start_line: int, end_line: int, max_chunk_lines: int) -> list[int]:
    split_points = [start_line]
    current_start = start_line
    for line_number in range(start_line + 1, end_line + 1):
        if line_number - current_start < max_chunk_lines:
            continue
        line = source_lines[line_number - 1] if line_number - 1 < len(source_lines) else ""
        stripped = line.strip()
        previous = source_lines[line_number - 2].strip() if 0 <= line_number - 2 < len(source_lines) else ""
        boundary = (
            not stripped
            or stripped.startswith(("def ", "async def ", "class ", "function ", "export function ", "export class "))
            or re.match(r"^(public|private|protected|internal|static|export|const|let|var)\b", stripped) is not None
            or (_line_indent(line) == 0 and previous.endswith(("}", ";")))
        )
        if boundary:
            split_points.append(line_number)
            current_start = line_number
    return split_points


def _semantic_line_ranges(source_lines: list[str], start_line: int, end_line: int, max_chunk_lines: int = MAX_CHUNK_LINES, overlap_lines: int = CHUNK_OVERLAP_LINES) -> list[tuple[int, int]]:
    total_lines = max(end_line - start_line + 1, 1)
    if total_lines <= max_chunk_lines:
        return [(start_line, end_line)]
    split_points = _split_points_for_range(source_lines, start_line, end_line, max_chunk_lines)
    if len(split_points) <= 1:
        return _line_ranges(start_line, end_line, max_chunk_lines=max_chunk_lines, overlap_lines=overlap_lines)
    ranges: list[tuple[int, int]] = []
    for index, part_start in enumerate(split_points):
        part_end = split_points[index + 1] - 1 if index + 1 < len(split_points) else end_line
        if part_end < part_start:
            continue
        if part_end - part_start + 1 > max_chunk_lines + overlap_lines:
            ranges.extend(_line_ranges(part_start, part_end, max_chunk_lines=max_chunk_lines, overlap_lines=overlap_lines))
        else:
            ranges.append((part_start, part_end))
    return ranges


def _build_chunk_records(
    file_path: str,
    chunk_kind: str,
    symbol_name: str,
    qualified_name: str,
    source_lines: list[str],
    start_line: int,
    end_line: int,
    source_hash: str,
    parser_name: str,
    symbol_metadata: dict[str, object] | None = None,
) -> list[ChunkRecord]:
    records: list[ChunkRecord] = []
    line_count = max(len(source_lines), 1)
    safe_start = min(max(start_line, 1), line_count)
    safe_end = min(max(end_line, safe_start), line_count)
    semantic_start = _attach_leading_context(source_lines, safe_start)
    ranges = _semantic_line_ranges(source_lines, semantic_start, safe_end)
    for part_index, (part_start, part_end) in enumerate(ranges, start=1):
        content = _safe_chunk_content(source_lines, part_start, part_end, file_path)
        content_hash = _content_hash(content)
        identity = qualified_name or symbol_name or file_path
        chunk_id = f"{file_path}:{identity}:{part_start}-{part_end}:v{CHUNKING_VERSION}:{content_hash}"
        records.append(
            ChunkRecord(
                chunk_id=chunk_id,
                file_path=file_path,
                start_line=part_start,
                end_line=part_end,
                chunk_kind=chunk_kind,
                symbol_name=symbol_name,
                qualified_name=qualified_name,
                content=content,
                content_hash=content_hash,
                source_hash=source_hash,
                parser_name=parser_name,
                chunking_version=CHUNKING_VERSION,
                metadata={
                    "identity": identity,
                    "symbol_metadata": symbol_metadata or {},
                },
            )
        )
    return records


def _dedupe_overlapping_symbols(symbols: list[SymbolRecord]) -> list[SymbolRecord]:
    deduped: list[SymbolRecord] = []
    seen: set[tuple[str, int, int, str]] = set()
    for symbol in sorted(symbols, key=lambda item: (item.start_line, item.end_line, item.qualified_name, item.kind)):
        key = (symbol.qualified_name, symbol.start_line, symbol.end_line, symbol.kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(symbol)
    return deduped


def build_chunks(repo_root: Path, file_path: str, symbols: list[SymbolRecord]) -> list[ChunkRecord]:
    source = (repo_root / file_path).read_text(encoding="utf-8", errors="ignore")
    source_lines = source.splitlines()
    source_digest = _source_hash(source)
    if _is_non_core_blob(source_lines):
        return [
            ChunkRecord(
                chunk_id=f"{file_path}:module:v{CHUNKING_VERSION}:{_content_hash(file_path)}",
                file_path=file_path,
                start_line=1,
                end_line=max(len(source_lines), 1),
                chunk_kind="module",
                symbol_name="",
                qualified_name=file_path,
                content=f"[content omitted: large non-core or minified blob excluded from chunk storage] {file_path}",
                content_hash=_content_hash(file_path),
                source_hash=source_digest,
                parser_name="none",
                chunking_version=CHUNKING_VERSION,
                metadata={"identity": file_path, "omitted": True},
            )
        ]
    chunks: list[ChunkRecord] = []
    for symbol in _dedupe_overlapping_symbols(symbols):
        chunks.extend(
            _build_chunk_records(
                file_path=file_path,
                chunk_kind=symbol.kind,
                symbol_name=symbol.name,
                qualified_name=symbol.qualified_name,
                source_lines=source_lines,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                source_hash=source_digest,
                parser_name=str(symbol.metadata.get("parser", "")),
                symbol_metadata=symbol.metadata,
            )
        )
    if not chunks:
        chunks.extend(
            _build_chunk_records(
                file_path=file_path,
                chunk_kind="module",
                symbol_name="",
                qualified_name=file_path,
                source_lines=source_lines,
                start_line=1,
                end_line=max(len(source_lines), 1),
                source_hash=source_digest,
                parser_name="none",
                symbol_metadata={},
            )
        )
    return chunks


def summarize_chunks(chunks: list[ChunkRecord]) -> dict[str, object]:
    kind_counts: dict[str, int] = {}
    content_counts: dict[str, int] = {}
    omitted_content_count = 0
    for chunk in chunks:
        kind_counts[chunk.chunk_kind] = kind_counts.get(chunk.chunk_kind, 0) + 1
        content_counts[chunk.content] = content_counts.get(chunk.content, 0) + 1
        if chunk.content.startswith("[content omitted:"):
            omitted_content_count += 1
    return {
        "chunk_count": len(chunks),
        "module_chunk_count": kind_counts.get("module", 0),
        "omitted_content_chunk_count": omitted_content_count,
        "duplicate_content_chunk_count": sum(count - 1 for count in content_counts.values() if count > 1),
        "chunk_kind_counts": kind_counts,
    }


def diff_chunk_ids(previous_chunks: list[dict[str, object]], current_chunks: list[ChunkRecord]) -> dict[str, set[str]]:
    previous_ids = {str(chunk.get("chunk_id", "")) for chunk in previous_chunks if str(chunk.get("chunk_id", ""))}
    current_ids = {chunk.chunk_id for chunk in current_chunks}
    return {
        "unchanged": previous_ids & current_ids,
        "stale": previous_ids - current_ids,
        "new": current_ids - previous_ids,
    }
