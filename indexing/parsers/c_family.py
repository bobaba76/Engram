from __future__ import annotations

import re
from pathlib import Path

from indexing.clang_extractor import clang_available, clang_runtime_status, extract_clang_symbols
from indexing.native_build_context import expand_object_like_macros, extract_macro_definitions, load_native_build_context, resolve_include_targets
from indexing.parser_registry import ParserRegistry
from indexing.parsers.common import clean_symbol_name, dedupe_symbols, is_useful_reference, node_text, tree_sitter_parser
from indexing.tree_cache import parse_with_cache
from models.entity_models import SymbolRecord


C_INCLUDE_PATTERN = re.compile(r"^\s*#include\s+[<\"](?P<module>[^>\"]+)[>\"]", re.MULTILINE)
C_DEFINE_PATTERN = re.compile(r"^\s*#define\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b(?P<body>.*)$", re.MULTILINE)
C_REFERENCE_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
C_FUNCTION_PATTERN = re.compile(r"^\s*(?:__declspec\s*\([^)]+\)\s+|__attribute__\s*\(\([^)]*\)\)\s+|[A-Z][A-Z0-9_]*(?:_API|_EXPORTS?|_PUBLIC)\s+|static\s+|inline\s+|extern\s+|const\s+|volatile\s+|unsigned\s+|signed\s+|long\s+|short\s+|struct\s+[A-Za-z_][A-Za-z0-9_]*\s+|enum\s+[A-Za-z_][A-Za-z0-9_]*\s+|union\s+[A-Za-z_][A-Za-z0-9_]*\s+|[A-Za-z_][A-Za-z0-9_\*\s]+\s+)+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*\{", re.MULTILINE)
C_FUNCTION_DECL_PATTERN = re.compile(r"^\s*(?:__declspec\s*\([^)]+\)\s+|__attribute__\s*\(\([^)]*\)\)\s+|[A-Z][A-Z0-9_]*(?:_API|_EXPORTS?|_PUBLIC)\s+|extern\s+|static\s+|inline\s+|const\s+|volatile\s+|unsigned\s+|signed\s+|long\s+|short\s+|struct\s+[A-Za-z_][A-Za-z0-9_]*\s+|enum\s+[A-Za-z_][A-Za-z0-9_]*\s+|union\s+[A-Za-z_][A-Za-z0-9_]*\s+|[A-Za-z_][A-Za-z0-9_\*\s]+\s+)+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*;", re.MULTILINE)
C_TYPE_PATTERN = re.compile(r"^\s*(?:typedef\s+)?(?:struct|enum|union|class)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
C_TYPEDEF_ALIAS_PATTERN = re.compile(r"^\s*typedef\s+(?:[^;]*?\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;", re.MULTILINE)
C_ENUM_BLOCK_PATTERN = re.compile(r"enum\s+(?P<enum_name>[A-Za-z_][A-Za-z0-9_]*)?\s*\{(?P<body>.*?)\}\s*(?P<alias>[A-Za-z_][A-Za-z0-9_]*)?\s*;", re.DOTALL)
C_ENUM_CONSTANT_PATTERN = re.compile(r"\b(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b\s*(?:=\s*[^,}]+)?(?:,|$)")
EXPORT_MARKER_PATTERN = re.compile(r"\b(__declspec\s*\(\s*dllexport\s*\)|__attribute__\s*\(\(\s*visibility\s*\(\s*['\"]default['\"]\s*\)\s*\)\)|[A-Z][A-Z0-9_]*(?:_API|_EXPORTS?|_PUBLIC))\b")
LAYOUT_FIELD_PATTERN = re.compile(r"^\s*(?!typedef\b)(?:const\s+|volatile\s+|unsigned\s+|signed\s+|long\s+|short\s+|struct\s+[A-Za-z_][A-Za-z0-9_]*\s+|enum\s+[A-Za-z_][A-Za-z0-9_]*\s+|union\s+[A-Za-z_][A-Za-z0-9_]*\s+|[A-Za-z_][A-Za-z0-9_<>\*\s]+\s+)+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\]]+\])?\s*(?::\s*\d+)?;", re.MULTILINE)

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


def _line_number_for_offset(source: str, offset: int) -> int:
    return source.count("\n", 0, max(offset, 0)) + 1


def _canonical_symbol_token(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        return ""
    value = value.replace("->", ".")
    value = value.replace("::", ".")
    return value.strip()


def _function_signature_preview(body_text: str) -> str:
    match = re.search(r"\((?P<args>[^\)]*)\)", body_text)
    if not match:
        return "()"
    args = re.sub(r"\s+", " ", match.group("args").strip())
    return f"({args})"


def _translation_unit_name(file_path: Path) -> str:
    suffixes = "".join(file_path.suffixes)
    name = file_path.name[:-len(suffixes)] if suffixes else file_path.stem
    return name or file_path.stem


def _associated_source_candidates(file_path: Path) -> list[str]:
    stem = _translation_unit_name(file_path)
    parent = file_path.parent
    if file_path.suffix.lower() in {".h", ".hpp", ".hh", ".hxx"}:
        suffixes = [".c", ".cpp", ".cc", ".cxx"]
    else:
        suffixes = [".h", ".hpp", ".hh", ".hxx"]
    return [str((parent / f"{stem}{suffix}").as_posix()) for suffix in suffixes]


def _c_qualified_name(file_path: Path, name: str, body_text: str) -> tuple[str, str]:
    canonical_name = _canonical_symbol_token(name)
    translation_unit = _translation_unit_name(file_path)
    signature_suffix = _function_signature_preview(body_text) if "(" in body_text else ""
    qualified_name = canonical_name
    if signature_suffix and canonical_name:
        qualified_name = f"{canonical_name}{signature_suffix}"
    symbol_key = canonical_name.split(".")[-1] if canonical_name else name
    fallback_signature = f"{translation_unit}::{symbol_key}{signature_suffix}" if symbol_key else qualified_name
    return qualified_name or name, fallback_signature or qualified_name or name


def _c_calls_and_references(body_text: str, current_name: str) -> tuple[list[str], list[str]]:
    references = sorted({clean_symbol_name(token) for token in C_REFERENCE_PATTERN.findall(body_text) if is_useful_reference(clean_symbol_name(token), current_name, GENERIC_REFERENCE_TOKENS)})
    calls = sorted({clean_symbol_name(match.group(1)) for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_:>]*)\s*\(", body_text) if is_useful_reference(clean_symbol_name(match.group(1)), current_name, GENERIC_REFERENCE_TOKENS)})
    return calls, references


def _c_symbol_metadata(file_path: Path, language_name: str, imports: list[str], calls: list[str], references: list[str], *, is_definition: bool = False, is_declaration: bool = False, parser_name: str = "", node_type: str = "") -> dict[str, object]:
    return {
        "parser": parser_name,
        "language": language_name,
        "node_type": node_type,
        "imports": imports,
        "calls": calls,
        "references": references,
        "is_definition": is_definition,
        "is_declaration": is_declaration,
        "translation_unit": _translation_unit_name(file_path),
        "file_role": "header" if file_path.suffix.lower() in {".h", ".hpp", ".hh", ".hxx"} else "source",
        "source_associations": _associated_source_candidates(file_path),
    }


def _native_export_markers(text: str) -> list[str]:
    markers: list[str] = []
    for match in EXPORT_MARKER_PATTERN.finditer(text):
        marker = re.sub(r"\s+", " ", match.group(1)).strip()
        if marker and marker not in markers:
            markers.append(marker)
    return markers


def _native_abi_surface_kind(symbol_kind: str, node_type: str, file_path: Path, is_exported: bool) -> str:
    if not (is_exported or file_path.suffix.lower() in {".h", ".hpp", ".hh", ".hxx"}):
        return ""
    if symbol_kind in {"type", "typedef", "class"}:
        return "layout"
    if symbol_kind == "macro":
        return "macro"
    if symbol_kind == "constant":
        return "enum"
    if symbol_kind in {"function", "method"}:
        return "exported_function" if is_exported else "public_function"
    return ""


def _apply_native_surface_metadata(metadata: dict[str, object], text: str, symbol_kind: str, file_path: Path) -> dict[str, object]:
    export_markers = _native_export_markers(text)
    if export_markers:
        metadata["export_markers"] = export_markers
        metadata["is_exported"] = True
    abi_kind = _native_abi_surface_kind(symbol_kind, str(metadata.get("node_type", "")), file_path, bool(metadata.get("is_exported")))
    if abi_kind:
        metadata["abi_surface"] = abi_kind
    if abi_kind == "layout":
        layout_fields = _native_layout_fields(text)
        if layout_fields:
            metadata["layout_fields"] = layout_fields
    return metadata


def _native_layout_fields(text: str) -> list[str]:
    body_match = re.search(r"\{(?P<body>[\s\S]*?)\}", text)
    if body_match is None:
        return []
    fields: list[str] = []
    for match in LAYOUT_FIELD_PATTERN.finditer(body_match.group("body")):
        name = str(match.group("name") or "").strip()
        if name and name not in fields:
            fields.append(name)
    return fields[:50]


def _c_family_symbol_kind(name: str, node_type: str, language_hint: str) -> str:
    if node_type in {"preproc_def", "macro_definition"}:
        return "macro"
    if node_type in {"class_specifier", "class_declaration"}:
        return "class"
    if node_type in {"struct_specifier", "enum_specifier", "union_specifier"}:
        return "type"
    if node_type in {"type_definition", "typedef"}:
        return "typedef"
    if node_type in {"enumerator", "enum_constant"}:
        return "constant"
    if node_type in {"namespace_definition", "namespace_declaration"}:
        return "namespace"
    if node_type in {"field_declaration", "property_declaration"}:
        return "field"
    if node_type in {"method_declaration", "constructor_declaration", "destructor_declaration", "function_definition", "function_declarator", "declaration"}:
        return "method" if language_hint == "csharp" and name[:1].isupper() is False else "function"
    return "type"


def _append_c_macro_symbols(source: str, imports: list[str], symbols: list[SymbolRecord], language_name: str, file_path: Path) -> None:
    for match in C_DEFINE_PATTERN.finditer(source):
        name = match.group("name")
        if not name:
            continue
        body = match.group("body") or ""
        line_number = _line_number_for_offset(source, match.start())
        _, references = _c_calls_and_references(body, name)
        metadata = {"parser": "regex_macro", "language": language_name, "imports": imports, "calls": [], "references": references, "node_type": "macro_definition"}
        _apply_native_surface_metadata(metadata, body, "macro", file_path)
        symbols.append(
            SymbolRecord(
                name=name,
                qualified_name=name,
                kind="macro",
                start_line=line_number,
                end_line=line_number,
                signature=name,
                metadata=metadata,
            )
        )


def _append_c_typedef_and_enum_symbols(source: str, imports: list[str], symbols: list[SymbolRecord], language_name: str, file_path: Path, build_context: dict[str, object]) -> None:
    for match in C_TYPEDEF_ALIAS_PATTERN.finditer(source):
        name = match.group("name")
        if not name:
            continue
        line_number = _line_number_for_offset(source, match.start())
        metadata = {"parser": "regex_typedef", "language": language_name, "imports": imports, "calls": [], "references": [], "build_context": build_context, "node_type": "typedef"}
        _apply_native_surface_metadata(metadata, match.group(0), "typedef", file_path)
        symbols.append(
            SymbolRecord(
                name=name,
                qualified_name=name,
                kind="typedef",
                start_line=line_number,
                end_line=line_number,
                signature=name,
                metadata=metadata,
            )
        )
    for match in C_ENUM_BLOCK_PATTERN.finditer(source):
        enum_name = match.group("enum_name") or match.group("alias") or ""
        body = match.group("body") or ""
        base_line = _line_number_for_offset(source, match.start())
        if enum_name:
            metadata = {"parser": "regex_enum", "language": language_name, "imports": imports, "calls": [], "references": [], "build_context": build_context, "node_type": "enum"}
            _apply_native_surface_metadata(metadata, match.group(0), "type", file_path)
            symbols.append(
                SymbolRecord(
                    name=enum_name,
                    qualified_name=enum_name,
                    kind="type",
                    start_line=base_line,
                    end_line=_line_number_for_offset(source, match.end()),
                    signature=enum_name,
                    metadata=metadata,
                )
            )
        for enumerator_match in C_ENUM_CONSTANT_PATTERN.finditer(body):
            constant_name = enumerator_match.group("name")
            if not constant_name:
                continue
            line_number = base_line + body[:enumerator_match.start()].count("\n")
            metadata = {"parser": "regex_enum", "language": language_name, "imports": imports, "calls": [], "references": [], "build_context": build_context, "node_type": "enum_constant", "abi_surface": "enum" if file_path.suffix.lower() in {".h", ".hpp", ".hh", ".hxx"} else ""}
            symbols.append(
                SymbolRecord(
                    name=constant_name,
                    qualified_name=f"{enum_name}.{constant_name}" if enum_name else constant_name,
                    kind="constant",
                    start_line=line_number,
                    end_line=line_number,
                    signature=constant_name,
                    metadata=metadata,
                )
            )


def extract_symbols_with_status(file_path: Path) -> tuple[list[SymbolRecord], dict[str, object]]:
    language_name = "cpp" if file_path.suffix.lower() in {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"} else "c"
    clang_status = clang_runtime_status()
    build_context = load_native_build_context(str(file_path))
    if clang_available():
        parsed = extract_clang_symbols(file_path)
        if parsed:
            return parsed, {"parser": "clang", "symbol_count": len(parsed), "language": language_name, "clang": clang_status, "build_context": build_context}
    parser = tree_sitter_parser(language_name)
    if parser is not None:
        parsed = _extract_symbols_tree_sitter(file_path, parser, language_name)
        if parsed:
            return parsed, {"parser": "tree_sitter", "symbol_count": len(parsed), "language": language_name, "clang": clang_status, "build_context": build_context}
    parsed = _extract_symbols_regex(file_path, language_name)
    return parsed, {"parser": "regex", "symbol_count": len(parsed), "language": language_name, "clang": clang_status, "build_context": build_context}


def extract_symbols(file_path: Path) -> list[SymbolRecord]:
    symbols, _ = extract_symbols_with_status(file_path)
    return symbols


def _extract_symbols_tree_sitter(file_path: Path, parser, language_name: str) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    build_context = load_native_build_context(str(file_path))
    macros = extract_macro_definitions(source, build_context)
    source_bytes = source.encode("utf-8")
    tree = parse_with_cache(file_path, language_name, parser, source_bytes)
    root = tree.root_node
    symbols: list[SymbolRecord] = []
    imports = resolve_include_targets(str(file_path), sorted({match.group("module") for match in C_INCLUDE_PATTERN.finditer(source)}), build_context)

    def walk(node) -> None:
        interesting = {
            "function_definition",
            "function_declarator",
            "declaration",
            "struct_specifier",
            "enum_specifier",
            "union_specifier",
            "class_specifier",
            "namespace_definition",
        }
        if node.type in interesting:
            name_node = node.child_by_field_name("name")
            if name_node is None and node.type == "function_definition":
                for child in node.children:
                    nested_name = child.child_by_field_name("declarator") if hasattr(child, "child_by_field_name") else None
                    if nested_name is not None:
                        name_node = nested_name.child_by_field_name("declarator") or nested_name.child_by_field_name("name") or nested_name
                        break
            if name_node is not None:
                name = clean_symbol_name(node_text(source_bytes, name_node))
                if name:
                    body_text = node_text(source_bytes, node)
                    expanded_text = expand_object_like_macros(body_text, macros)
                    calls, references = _c_calls_and_references(expanded_text, name)
                    is_definition = node.type == "function_definition"
                    is_declaration = node.type in {"function_declarator", "declaration"} and not is_definition and body_text.strip().endswith(";")
                    qualified_name, signature = _c_qualified_name(file_path, name, body_text)
                    symbol_kind = _c_family_symbol_kind(name, node.type, language_name)
                    metadata = _c_symbol_metadata(file_path, language_name, imports, calls, references, is_definition=is_definition, is_declaration=is_declaration, parser_name="tree_sitter", node_type=node.type)
                    metadata["build_context"] = build_context
                    _apply_native_surface_metadata(metadata, body_text, symbol_kind, file_path)
                    symbols.append(
                        SymbolRecord(
                            name=name,
                            qualified_name=qualified_name,
                            kind=symbol_kind,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            signature=signature,
                            metadata=metadata,
                        )
                    )
        for child in node.children:
            walk(child)

    walk(root)
    existing_names = {symbol.name for symbol in symbols}
    for match in C_FUNCTION_DECL_PATTERN.finditer(source):
        name = match.group("name")
        if not name or name in existing_names:
            continue
        line_number = _line_number_for_offset(source, match.start())
        declaration_text = match.group(0)
        qualified_name, signature = _c_qualified_name(file_path, name, declaration_text)
        metadata = _c_symbol_metadata(file_path, language_name, imports, [], [], is_declaration=True, parser_name="regex_declaration_supplement", node_type="function_declaration")
        metadata["build_context"] = build_context
        _apply_native_surface_metadata(metadata, declaration_text, "function", file_path)
        symbols.append(SymbolRecord(name=name, qualified_name=qualified_name, kind="function", start_line=line_number, end_line=line_number, signature=signature, metadata=metadata))
    _append_c_macro_symbols(source, imports, symbols, language_name, file_path)
    _append_c_typedef_and_enum_symbols(source, imports, symbols, language_name, file_path, build_context)
    return dedupe_symbols(symbols)


def _extract_symbols_regex(file_path: Path, language_name: str) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    build_context = load_native_build_context(str(file_path))
    macros = extract_macro_definitions(source, build_context)
    symbols: list[SymbolRecord] = []
    imports = resolve_include_targets(str(file_path), sorted({match.group("module") for match in C_INCLUDE_PATTERN.finditer(source)}), build_context)
    for line_number, line in enumerate(source.splitlines(), start=1):
        type_match = C_TYPE_PATTERN.search(line)
        if type_match is not None:
            name = type_match.group("name")
            qualified_name, signature = _c_qualified_name(file_path, name, line)
            metadata = _c_symbol_metadata(file_path, language_name, imports, [], [], parser_name="regex_fallback", node_type="type")
            metadata["build_context"] = build_context
            _apply_native_surface_metadata(metadata, line, "type", file_path)
            symbols.append(SymbolRecord(name=name, qualified_name=qualified_name, kind="type", start_line=line_number, end_line=line_number, signature=signature, metadata=metadata))
            continue
        func_match = C_FUNCTION_PATTERN.search(line)
        if func_match is not None:
            name = func_match.group("name")
            expanded_line = expand_object_like_macros(line, macros)
            calls, references = _c_calls_and_references(expanded_line, name)
            qualified_name, signature = _c_qualified_name(file_path, name, line)
            metadata = _c_symbol_metadata(file_path, language_name, imports, calls, references, is_definition=True, parser_name="regex_fallback", node_type="function_definition")
            metadata["build_context"] = build_context
            _apply_native_surface_metadata(metadata, line, "function", file_path)
            symbols.append(SymbolRecord(name=name, qualified_name=qualified_name, kind="function", start_line=line_number, end_line=line_number, signature=signature, metadata=metadata))
            continue
        decl_match = C_FUNCTION_DECL_PATTERN.search(line)
        if decl_match is not None:
            name = decl_match.group("name")
            qualified_name, signature = _c_qualified_name(file_path, name, line)
            metadata = _c_symbol_metadata(file_path, language_name, imports, [], [], is_declaration=True, parser_name="regex_fallback", node_type="function_declaration")
            metadata["build_context"] = build_context
            _apply_native_surface_metadata(metadata, line, "function", file_path)
            symbols.append(SymbolRecord(name=name, qualified_name=qualified_name, kind="function", start_line=line_number, end_line=line_number, signature=signature, metadata=metadata))
    _append_c_macro_symbols(source, imports, symbols, language_name, file_path)
    _append_c_typedef_and_enum_symbols(source, imports, symbols, language_name, file_path, build_context)
    return dedupe_symbols(symbols)


def parse(file_path: Path):
    from indexing.parser_registry import ParseOutcome

    symbols, status = extract_symbols_with_status(file_path)
    return ParseOutcome(symbols, status)


def register(registry: ParserRegistry) -> None:
    for extension in (".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"):
        registry.register_extension(extension, parse)
