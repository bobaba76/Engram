from __future__ import annotations

import re
from pathlib import Path

from indexing.parser_registry import ParserRegistry
from indexing.parsers.common import clean_symbol_name, dedupe_symbols, is_useful_reference, node_text, tree_sitter_parser
from indexing.tree_cache import parse_with_cache
from models.entity_models import SymbolRecord


CS_IMPORT_PATTERN = re.compile(r"^\s*using\s+(?P<module>[A-Za-z_][A-Za-z0-9_\.]*)\s*;", re.MULTILINE)
CS_NAMESPACE_PATTERN = re.compile(r"^\s*namespace\s+(?P<name>[A-Za-z_][A-Za-z0-9_\.]*)", re.MULTILINE)
CS_REFERENCE_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
CS_MEMBER_PATTERN = re.compile(r"^\s*(?:public|private|protected|internal)?\s*(?:static\s+|virtual\s+|override\s+|async\s+|partial\s+|sealed\s+|abstract\s+)*(?:class|interface|record|struct|enum|delegate|[A-Za-z_][A-Za-z0-9_<>,\[\]\?\s]*\s+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:|\{|where|$)", re.MULTILINE)

GENERIC_REFERENCE_TOKENS = {
    "bool",
    "byte",
    "char",
    "class",
    "double",
    "else",
    "enum",
    "extern",
    "float",
    "include",
    "int",
    "interface",
    "long",
    "namespace",
    "private",
    "protected",
    "public",
    "record",
    "short",
    "static",
    "string",
    "struct",
    "typedef",
    "union",
    "using",
    "void",
}


def _csharp_symbol_kind(name: str, node_type: str) -> str:
    if node_type in {"class_declaration", "record_declaration"}:
        return "class"
    if node_type in {"interface_declaration"}:
        return "interface"
    if node_type in {"struct_declaration", "enum_declaration"}:
        return "type"
    if node_type in {"namespace_declaration", "file_scoped_namespace_declaration"}:
        return "namespace"
    if node_type in {"property_declaration", "field_declaration"}:
        return "field"
    return "method"


def _csharp_calls_and_references(body_text: str, current_name: str) -> tuple[list[str], list[str]]:
    references = sorted({clean_symbol_name(token) for token in CS_REFERENCE_PATTERN.findall(body_text) if is_useful_reference(clean_symbol_name(token), current_name, GENERIC_REFERENCE_TOKENS)})
    calls = sorted({clean_symbol_name(match.group(1)) for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_\.]*)\s*\(", body_text) if is_useful_reference(clean_symbol_name(match.group(1)), current_name, GENERIC_REFERENCE_TOKENS)})
    return calls, references


def extract_symbols(file_path: Path) -> list[SymbolRecord]:
    parser = tree_sitter_parser("c_sharp")
    if parser is not None:
        parsed = _extract_symbols_tree_sitter(file_path, parser)
        if parsed:
            return parsed
    return _extract_symbols_regex(file_path)


def _extract_symbols_tree_sitter(file_path: Path, parser) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    source_bytes = source.encode("utf-8")
    tree = parse_with_cache(file_path, "csharp", parser, source_bytes)
    root = tree.root_node
    imports = sorted({match.group("module") for match in CS_IMPORT_PATTERN.finditer(source)})
    symbols: list[SymbolRecord] = []

    def walk(node, parents: list[str]) -> None:
        interesting = {
            "namespace_declaration",
            "file_scoped_namespace_declaration",
            "class_declaration",
            "interface_declaration",
            "record_declaration",
            "struct_declaration",
            "enum_declaration",
            "method_declaration",
            "constructor_declaration",
            "destructor_declaration",
            "property_declaration",
            "field_declaration",
        }
        next_parents = parents
        if node.type in interesting:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = node_text(source_bytes, name_node).strip()
                qualified_name = ".".join([*parents, name]) if parents else name
                body_text = node_text(source_bytes, node)
                calls, references = _csharp_calls_and_references(body_text, name)
                symbols.append(
                    SymbolRecord(
                        name=name,
                        qualified_name=qualified_name,
                        kind=_csharp_symbol_kind(name, node.type),
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=qualified_name,
                        metadata={
                            "parser": "tree_sitter",
                            "language": "csharp",
                            "node_type": node.type,
                            "imports": imports,
                            "calls": calls,
                            "references": references,
                            "parent_chain": parents,
                            "namespace": ".".join(parents[:1]) if parents else "",
                        },
                    )
                )
                if node.type in {"namespace_declaration", "file_scoped_namespace_declaration", "class_declaration", "interface_declaration", "record_declaration", "struct_declaration", "enum_declaration"}:
                    next_parents = [*parents, name]
        for child in node.children:
            walk(child, next_parents)

    walk(root, [])
    return dedupe_symbols(symbols)


def _extract_symbols_regex(file_path: Path) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    imports = sorted({match.group("module") for match in CS_IMPORT_PATTERN.finditer(source)})
    namespace_match = CS_NAMESPACE_PATTERN.search(source)
    namespace_name = namespace_match.group("name") if namespace_match else ""
    symbols: list[SymbolRecord] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        match = CS_MEMBER_PATTERN.search(line)
        if match is None:
            continue
        name = match.group("name")
        kind = "class" if " class " in f" {line} " or line.strip().startswith("class ") else "method"
        if any(token in line for token in [" interface ", "interface "]):
            kind = "interface"
        elif any(token in line for token in [" struct ", "enum ", " record "]):
            kind = "type" if kind != "class" else kind
        qualified_name = f"{namespace_name}.{name}" if namespace_name else name
        symbols.append(
            SymbolRecord(
                name=name,
                qualified_name=qualified_name,
                kind=kind,
                start_line=line_number,
                end_line=line_number,
                signature=qualified_name,
                metadata={
                    "parser": "regex_fallback",
                    "language": "csharp",
                    "imports": imports,
                    "calls": [],
                    "references": [],
                    "namespace": namespace_name,
                },
            )
        )
    return dedupe_symbols(symbols)


def parse(file_path: Path):
    from indexing.parser_registry import ParseOutcome

    symbols = extract_symbols(file_path)
    parser_name = str(symbols[0].metadata.get("parser", "regex_fallback") if symbols else "regex_fallback")
    return ParseOutcome(symbols, {"parser": parser_name, "symbol_count": len(symbols), "language": "csharp"})


def register(registry: ParserRegistry) -> None:
    registry.register_extension(".cs", parse)
