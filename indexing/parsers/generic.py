from __future__ import annotations

import re
from pathlib import Path

from indexing.parser_registry import ParseOutcome, ParserRegistry
from models.entity_models import SymbolRecord


LANGUAGE_BY_EXTENSION = {
    ".rb": "ruby",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".dart": "dart",
    ".lua": "lua",
    ".r": "r",
    ".m": "objective_c",
    ".mm": "objective_cpp",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".fs": "fsharp",
    ".fsx": "fsharp",
    ".vb": "vbnet",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".vue": "vue",
    ".svelte": "svelte",
}

IMPORT_PATTERNS = (
    re.compile(r"^\s*(?:import|require|include|use|using|package|module)\s+([^;\n]+)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*from\s+([A-Za-z0-9_./:-]+)\s+import\b", re.IGNORECASE | re.MULTILINE),
)

SYMBOL_PATTERNS = (
    ("class", re.compile(r"\b(?:class|interface|trait|struct|enum|object)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("function", re.compile(r"\b(?:func|fn|function|def|sub|proc|procedure|method)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE | re.MULTILINE)),
    ("function", re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\([^\)]*\)\s*(?:\{|do\b|=>)", re.MULTILINE)),
    ("module", re.compile(r"\b(?:module|namespace|package)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE | re.MULTILINE)),
)

CALL_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
REFERENCE_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*\b")

NOISE = {
    "and", "as", "begin", "break", "case", "catch", "class", "const", "continue", "def", "do", "else", "end",
    "enum", "false", "for", "func", "function", "if", "import", "in", "interface", "let", "module", "namespace",
    "new", "nil", "none", "null", "package", "private", "protected", "public", "return", "self", "static", "struct",
    "switch", "this", "trait", "true", "try", "type", "use", "using", "var", "void", "while",
}


def _line_number_for_offset(source: str, offset: int) -> int:
    return source.count("\n", 0, max(offset, 0)) + 1


def _language(file_path: Path) -> str:
    return LANGUAGE_BY_EXTENSION.get(file_path.suffix.lower(), "generic")


def _imports(source: str) -> list[str]:
    values: list[str] = []
    for pattern in IMPORT_PATTERNS:
        for match in pattern.finditer(source):
            raw = str(match.group(1) or "")
            for token in re.split(r"[,\s]+", raw):
                item = token.strip().strip('"\'`(){}')
                if item and item not in values and not item.startswith(("//", "#")):
                    values.append(item)
    return values[:100]


def _calls(source: str, current_name: str) -> list[str]:
    values: list[str] = []
    for match in CALL_PATTERN.finditer(source):
        name = str(match.group(1) or "").strip()
        if not name or name == current_name or name.lower() in NOISE:
            continue
        if name not in values:
            values.append(name)
    return values[:100]


def _references(text: str, current_name: str) -> list[str]:
    values: list[str] = []
    for token in REFERENCE_PATTERN.findall(text):
        if not token or token == current_name or token.lower() in NOISE:
            continue
        if token not in values:
            values.append(token)
    return values[:100]


def parse_generic_file(file_path: Path) -> ParseOutcome:
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    language = _language(file_path)
    imports = _imports(source)
    module = file_path.with_suffix("").as_posix().replace("/", ".").replace("\\", ".")
    symbols: list[SymbolRecord] = []
    seen: set[tuple[str, int, str]] = set()
    for kind, pattern in SYMBOL_PATTERNS:
        for match in pattern.finditer(source):
            name = str(match.group(1) or "").strip()
            if not name or name.lower() in NOISE:
                continue
            line = _line_number_for_offset(source, match.start())
            key = (name, line, kind)
            if key in seen:
                continue
            seen.add(key)
            window = source[match.start():match.start() + 1500]
            symbols.append(
                SymbolRecord(
                    name=name.split(".")[-1],
                    qualified_name=f"{module}.{name}",
                    kind=kind,
                    start_line=line,
                    end_line=line,
                    signature=match.group(0).strip(),
                    metadata={
                        "parser": "generic_regex",
                        "language": language,
                        "imports": imports,
                        "calls": _calls(window, name),
                        "references": _references(window, name),
                    },
                )
            )
    if not symbols and imports:
        symbols.append(
            SymbolRecord(
                name=file_path.stem,
                qualified_name=module,
                kind="module",
                start_line=1,
                end_line=max(1, len(source.splitlines())),
                signature=file_path.name,
                metadata={"parser": "generic_regex", "language": language, "imports": imports, "calls": [], "references": imports},
            )
        )
    return ParseOutcome(symbols, {"parser": "generic_regex", "language": language, "symbol_count": len(symbols), "imports": imports})


def register(registry: ParserRegistry) -> None:
    for extension in LANGUAGE_BY_EXTENSION:
        registry.register_extension(extension, parse_generic_file)
