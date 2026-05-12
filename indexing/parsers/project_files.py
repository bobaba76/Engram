from __future__ import annotations

import re
from pathlib import Path

from indexing.parser_registry import ParserRegistry
from models.entity_models import SymbolRecord


def extract_symbols(file_path: Path) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    name = file_path.stem
    references = []
    language = "csharp_project"
    if file_path.suffix.lower() == ".csproj":
        references = re.findall(r"<ProjectReference\s+Include=\"([^\"]+)\"", source)
    elif file_path.suffix.lower() == ".sln":
        references = re.findall(r"Project\([^\)]*\)\s*=\s*\"[^\"]+\",\s*\"([^\"]+)\"", source)
    elif file_path.suffix.lower() in {".dproj", ".groupproj", ".lpi", ".lpk"}:
        language = "object_pascal_project"
        references = [
            *re.findall(r"(?:<MainSource>|<Filename[^>]*>|<UnitName[^>]*>|<FileName[^>]*>)([^<]+)", source, flags=re.IGNORECASE),
            *re.findall(r"\b(?:MainSource|Filename|FileName)\s*=\s*\"([^\"]+)\"", source, flags=re.IGNORECASE),
            *re.findall(r"\b(?:uses|contains)\s+([^;]+);", source, flags=re.IGNORECASE),
        ]
    suffix = file_path.suffix.lower()
    project_kind = "solution" if suffix in {".sln", ".groupproj"} else "project"
    if suffix in {".dpk", ".lpk"}:
        project_kind = "package"
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
                "language": language,
                "imports": sorted(references),
                "calls": [],
                "references": sorted(references),
                "project_references": sorted(references),
                "project_ownership_surface": language == "object_pascal_project",
            },
        )
    ]


def parse(file_path: Path):
    from indexing.parser_registry import ParseOutcome

    symbols = extract_symbols(file_path)
    language = symbols[0].metadata.get("language", "project") if symbols else "project"
    return ParseOutcome(symbols, {"parser": "text", "symbol_count": len(symbols), "language": language})


def register(registry: ParserRegistry) -> None:
    for extension in (".csproj", ".sln", ".dproj", ".groupproj", ".lpi", ".lpk"):
        registry.register_extension(extension, parse)
