from pathlib import Path

from indexing.parser_registry import DEFAULT_PARSER_REGISTRY
from models.entity_models import SymbolRecord


def extract_symbols(file_path: Path) -> list[SymbolRecord]:
    symbols, _ = extract_symbols_with_status(file_path)
    return symbols


def extract_symbols_with_status(file_path: Path) -> tuple[list[SymbolRecord], dict[str, object]]:
    outcome = DEFAULT_PARSER_REGISTRY.parse(file_path)
    return outcome.symbols, outcome.status


def register_default_parsers() -> None:
    from indexing.parsers import register_all

    register_all(DEFAULT_PARSER_REGISTRY)


register_default_parsers()
