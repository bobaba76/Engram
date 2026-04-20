from models.entity_models import SymbolRecord
from storage.duckdb_store import DuckDBStore


def get_symbol_context(symbols_by_file: dict[str, list[SymbolRecord]] = None, duckdb_store: DuckDBStore = None, target: str = None) -> dict[str, object]:
    if symbols_by_file is not None:
        matches = []
        for file_path, symbols in symbols_by_file.items():
            for symbol in symbols:
                if symbol.name == target or symbol.qualified_name == target:
                    matches.append({
                        "file": file_path,
                        "symbol": symbol.name,
                        "kind": symbol.kind,
                        "start_line": symbol.start_line,
                        "end_line": symbol.end_line,
                    })
        return {
            "target": target,
            "matches": matches,
        }
    elif duckdb_store is not None and target is not None:
        matches = [
            {
                "file": symbol["file_path"],
                "symbol": symbol["name"],
                "qualified_name": symbol["qualified_name"],
                "kind": symbol["kind"],
                "start_line": symbol["start_line"],
                "end_line": symbol["end_line"],
            }
            for symbol in duckdb_store.fetch_symbols_for_target(target, limit=50)
            if symbol["name"] == target or symbol["qualified_name"] == target
        ]
        return {
            "target": target,
            "matches": matches,
        }
    else:
        raise ValueError("Either symbols_by_file or duckdb_store and target must be provided")
