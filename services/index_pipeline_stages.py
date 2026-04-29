from __future__ import annotations

import json
from dataclasses import asdict
from typing import Iterable

from models.entity_models import ChunkRecord, FileRecord, SymbolRecord
from storage.duckdb_store import DuckDBStore


def persist_parse_records(
    duckdb: DuckDBStore,
    file_records: Iterable[FileRecord],
    symbols_by_file: dict[str, list[SymbolRecord]],
) -> dict[str, int]:
    file_rows = [asdict(file_record) for file_record in file_records]
    symbol_rows = []
    for file_record in file_records:
        for symbol in symbols_by_file.get(file_record.path, []):
            symbol_rows.append(
                {
                    "file_path": file_record.path,
                    "qualified_name": symbol.qualified_name,
                    "name": symbol.name,
                    "kind": symbol.kind,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "signature": symbol.signature,
                    "metadata_json": json.dumps(symbol.metadata),
                }
            )
    duckdb.upsert_files(file_rows)
    duckdb.insert_symbols(symbol_rows)
    return {"files": len(file_rows), "symbols": len(symbol_rows)}


def persist_chunk_records(duckdb: DuckDBStore, chunks: list[ChunkRecord]) -> int:
    duckdb.insert_chunks([asdict(chunk) for chunk in chunks])
    return len(chunks)
