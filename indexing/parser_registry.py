from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from models.entity_models import SymbolRecord


@dataclass(slots=True)
class ParseOutcome:
    symbols: list[SymbolRecord]
    status: dict[str, object]


ParserFn = Callable[[Path], ParseOutcome]


class ParserRegistry:
    def __init__(self) -> None:
        self._extension_parsers: dict[str, ParserFn] = {}
        self._filename_parsers: dict[str, ParserFn] = {}

    def register_extension(self, extension: str, parser: ParserFn) -> None:
        normalized = extension.strip().lower()
        if normalized and not normalized.startswith("."):
            normalized = f".{normalized}"
        if normalized:
            self._extension_parsers[normalized] = parser

    def register_filename(self, filename: str, parser: ParserFn) -> None:
        normalized = filename.strip().lower()
        if normalized:
            self._filename_parsers[normalized] = parser

    def parser_for(self, file_path: Path) -> ParserFn | None:
        return self._filename_parsers.get(file_path.name.lower()) or self._extension_parsers.get(file_path.suffix.lower())

    def describe(self) -> dict[str, list[str]]:
        return {
            "extensions": sorted(self._extension_parsers),
            "filenames": sorted(self._filename_parsers),
        }

    def parse(self, file_path: Path) -> ParseOutcome:
        parser = self.parser_for(file_path)
        if parser is None:
            return ParseOutcome([], {"parser": "none", "symbol_count": 0, "language": "unknown"})
        return parser(file_path)


DEFAULT_PARSER_REGISTRY = ParserRegistry()
