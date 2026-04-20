from models.entity_models import FileRecord, SymbolRecord
from storage.kuzu_store import KuzuStore


def build_graph(kuzu_store: KuzuStore, files: list[FileRecord], symbols_by_file: dict[str, list[SymbolRecord]]) -> None:
    symbols_by_name: dict[str, str] = {}
    for symbols in symbols_by_file.values():
        for symbol in symbols:
            symbols_by_name.setdefault(symbol.name, symbol.qualified_name)
            symbols_by_name.setdefault(symbol.qualified_name, symbol.qualified_name)
    for file_record in files:
        kuzu_store.ensure_file(file_record.path)
        for symbol in symbols_by_file.get(file_record.path, []):
            kuzu_store.ensure_symbol(symbol.qualified_name, file_record.path, symbol.kind, symbol.start_line, symbol.end_line)
            kuzu_store.add_edge(file_record.path, "DEFINES", symbol.qualified_name)
    for file_record in files:
        for symbol in symbols_by_file.get(file_record.path, []):
            for relation, metadata_key in (("IMPORTS", "imports"), ("CALLS", "calls"), ("REFERENCES", "references")):
                for raw_target in symbol.metadata.get(metadata_key, []):
                    target = symbols_by_name.get(raw_target)
                    if target is None or target == symbol.qualified_name:
                        continue
                    kuzu_store.add_edge(symbol.qualified_name, relation, target)
