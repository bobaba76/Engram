from pathlib import Path
from models.entity_models import ChunkRecord, SymbolRecord

MAX_CHUNK_LINES = 120
CHUNK_OVERLAP_LINES = 20
MAX_CHUNK_CONTENT_CHARS = 12000
MINIFIED_LINE_LENGTH_THRESHOLD = 2000


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
    selected_lines = source_lines[part_start - 1:part_end]
    content = "\n".join(selected_lines)
    if len(content) <= MAX_CHUNK_CONTENT_CHARS:
        return content
    return f"[content omitted: large non-core or minified blob excluded from chunk storage] {file_path}:{part_start}-{part_end}"


def _build_chunk_records(file_path: str, chunk_id_prefix: str, chunk_kind: str, symbol_name: str, qualified_name: str, source_lines: list[str], start_line: int, end_line: int) -> list[ChunkRecord]:
    records: list[ChunkRecord] = []
    ranges = _line_ranges(start_line, end_line)
    for part_index, (part_start, part_end) in enumerate(ranges, start=1):
        content = _safe_chunk_content(source_lines, part_start, part_end, file_path)
        chunk_id = chunk_id_prefix if len(ranges) == 1 else f"{chunk_id_prefix}:part{part_index}"
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
            )
        )
    return records


def build_chunks(repo_root: Path, file_path: str, symbols: list[SymbolRecord]) -> list[ChunkRecord]:
    source_lines = (repo_root / file_path).read_text(encoding="utf-8").splitlines()
    if _is_non_core_blob(source_lines):
        return [
            ChunkRecord(
                chunk_id=f"{file_path}:module",
                file_path=file_path,
                start_line=1,
                end_line=max(len(source_lines), 1),
                chunk_kind="module",
                symbol_name="",
                qualified_name=file_path,
                content=f"[content omitted: large non-core or minified blob excluded from chunk storage] {file_path}",
            )
        ]
    chunks: list[ChunkRecord] = []
    for index, symbol in enumerate(symbols, start=1):
        chunks.extend(
            _build_chunk_records(
                file_path=file_path,
                chunk_id_prefix=f"{file_path}:{index}",
                chunk_kind=symbol.kind,
                symbol_name=symbol.name,
                qualified_name=symbol.qualified_name,
                source_lines=source_lines,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
            )
        )
    if not chunks:
        chunks.extend(
            _build_chunk_records(
                file_path=file_path,
                chunk_id_prefix=f"{file_path}:module",
                chunk_kind="module",
                symbol_name="",
                qualified_name=file_path,
                source_lines=source_lines,
                start_line=1,
                end_line=max(len(source_lines), 1),
            )
        )
    return chunks
