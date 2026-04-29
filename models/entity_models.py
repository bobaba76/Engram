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
    content_hash: str = ""
    source_hash: str = ""
    parser_name: str = ""
    chunking_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProcessRecord:
    process_id: str
    name: str
    process_type: str
    entry_symbol: str
    terminal_symbol: str
    step_count: int
    step_list: list[dict[str, Any]] = field(default_factory=list)
    module_tags: list[str] = field(default_factory=list)
    community_tags: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProcessClusterRecord:
    cluster_id: str
    name: str
    process_type: str
    canonical_entry_symbol: str
    canonical_terminal_symbol: str
    process_count: int
    avg_step_count: float
    module_tags: list[str] = field(default_factory=list)
    community_tags: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProcessSymbolMembershipRecord:
    cluster_id: str
    process_id: str
    symbol: str
    step_index: int
    role: str


@dataclass(slots=True)
class ProcessRelationshipRecord:
    source_cluster_id: str
    target_cluster_id: str
    relation_type: str
    shared_symbol: str = ""
