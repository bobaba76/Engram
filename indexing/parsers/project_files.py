from __future__ import annotations

import re
from pathlib import Path

from indexing.parser_registry import ParserRegistry
from models.entity_models import SymbolRecord


def extract_symbols(file_path: Path) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    name = file_path.stem
    references = []
    if file_path.suffix.lower() == ".csproj":
        references = re.findall(r"<ProjectReference\s+Include=\"([^\"]+)\"", source)
    elif file_path.suffix.lower() == ".sln":
        references = re.findall(r"Project\([^\)]*\)\s*=\s*\"[^\"]+\",\s*\"([^\"]+)\"", source)
    project_kind = "project" if file_path.suffix.lower() == ".csproj" else "solution"
    return [
        SymbolRecord(
            name=name,
            qualified_name=name,
            kind=project_kind,
            start_line=1,
            end_line=max(1, len(source.splitlines())),
            signature=name,
            metadata={
                "parser": "text",
                "language": "csharp_project",
                "imports": sorted(references),
                "calls": [],
                "references": sorted(references),
                "project_references": sorted(references),
            },
        )
    ]


def parse(file_path: Path):
    from indexing.parser_registry import ParseOutcome

    symbols = extract_symbols(file_path)
    return ParseOutcome(symbols, {"parser": "text", "symbol_count": len(symbols), "language": "csharp_project"})


def register(registry: ParserRegistry) -> None:
    for extension in (".csproj", ".sln"):
        registry.register_extension(extension, parse)
