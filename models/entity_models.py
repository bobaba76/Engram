from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FileRecord:
    path: str
    language: str
    size_bytes: int
    sha256: str
    modified_time: float


@dataclass(slots=True)
class SymbolRecord:
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    signature: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChunkRecord:
    chunk_id: str
    file_path: str
    start_line: int
    end_line: int
    chunk_kind: str
    symbol_name: str = ""
    qualified_name: str = ""
    content: str = ""
