from __future__ import annotations

from collections.abc import Iterable

from models.entity_models import SymbolRecord

try:
    from tree_sitter import Parser
    from tree_sitter_language_pack import get_language
except ImportError:
    Parser = None
    get_language = None


def is_useful_reference(name: str, current_name: str = "", ignored_tokens: Iterable[str] | None = None) -> bool:
    token = str(name or "").strip()
    if not token or token == current_name:
        return False
    if ignored_tokens is not None and token in set(ignored_tokens):
        return False
    if len(token) <= 2 and token.islower():
        return False
    return True


def node_text(source_bytes: bytes, node) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def clean_symbol_name(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        return ""
    if "::" in value:
        value = value.split("::")[-1]
    if "." in value and not value.startswith("."):
        value = value.split(".")[-1]
    return value.strip("*&() ")


def dedupe_symbols(symbols: list[SymbolRecord]) -> list[SymbolRecord]:
    seen: set[tuple[str, int, str]] = set()
    deduped: list[SymbolRecord] = []
    for symbol in sorted(symbols, key=lambda item: (item.start_line, item.end_line, item.qualified_name)):
        key = (symbol.qualified_name, symbol.start_line, symbol.kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(symbol)
    return deduped


def tree_sitter_parser(language_name: str):
    if Parser is None or get_language is None:
        return None
    try:
        parser = Parser()
        language = get_language(language_name)
        if hasattr(parser, "set_language"):
            parser.set_language(language)
        else:
            parser.language = language
        return parser
    except Exception:
        return None
