import ast
import re
from pathlib import Path

from indexing.clang_extractor import clang_available, clang_runtime_status, extract_clang_symbols
from indexing.native_build_context import expand_object_like_macros, extract_macro_definitions, load_native_build_context, resolve_include_targets
from models.entity_models import SymbolRecord

try:
    from tree_sitter import Parser
    from tree_sitter_language_pack import get_language
except ImportError:
    Parser = None
    get_language = None


TS_FUNCTION_PATTERN = re.compile(
    r"(?:function\s+(?P<name1>[A-Za-z_][A-Za-z0-9_]*)"
    r"|const\s+(?P<name2>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:\(|async\s*\(|(?:async\s+)?[A-Za-z_][A-Za-z0-9_<>:,\s]*=>)"
    r"|export\s+function\s+(?P<name3>[A-Za-z_][A-Za-z0-9_]*)"
    r"|export\s+const\s+(?P<name4>[A-Za-z_][A-Za-z0-9_]*)\s*=)"
)
TS_IMPORT_PATTERN = re.compile(r"^\s*import\s+(?:[^\n]*?from\s+)?['\"](?P<module>[^'\"]+)['\"]", re.MULTILINE)
TS_REQUIRE_PATTERN = re.compile(r"require\(['\"](?P<module>[^'\"]+)['\"]\)")
TS_IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
TS_INTERFACE_PATTERN = re.compile(r"(?:export\s+)?interface\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
TS_TYPE_PATTERN = re.compile(r"(?:export\s+)?type\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=")
C_INCLUDE_PATTERN = re.compile(r"^\s*#include\s+[<\"](?P<module>[^>\"]+)[>\"]", re.MULTILINE)
C_DEFINE_PATTERN = re.compile(r"^\s*#define\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b(?P<body>.*)$", re.MULTILINE)
C_REFERENCE_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
C_FUNCTION_PATTERN = re.compile(r"^\s*(?:static\s+|inline\s+|extern\s+|const\s+|volatile\s+|unsigned\s+|signed\s+|long\s+|short\s+|struct\s+[A-Za-z_][A-Za-z0-9_]*\s+|enum\s+[A-Za-z_][A-Za-z0-9_]*\s+|union\s+[A-Za-z_][A-Za-z0-9_]*\s+|[A-Za-z_][A-Za-z0-9_\*\s]+\s+)+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*\{", re.MULTILINE)
C_FUNCTION_DECL_PATTERN = re.compile(r"^\s*(?:extern\s+|static\s+|inline\s+|const\s+|volatile\s+|unsigned\s+|signed\s+|long\s+|short\s+|struct\s+[A-Za-z_][A-Za-z0-9_]*\s+|enum\s+[A-Za-z_][A-Za-z0-9_]*\s+|union\s+[A-Za-z_][A-Za-z0-9_]*\s+|[A-Za-z_][A-Za-z0-9_\*\s]+\s+)+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*;", re.MULTILINE)
C_TYPE_PATTERN = re.compile(r"^\s*(?:typedef\s+)?(?:struct|enum|union|class)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
C_TYPEDEF_ALIAS_PATTERN = re.compile(r"^\s*typedef\s+(?:[^;]*?\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;", re.MULTILINE)
C_ENUM_BLOCK_PATTERN = re.compile(r"enum\s+(?P<enum_name>[A-Za-z_][A-Za-z0-9_]*)?\s*\{(?P<body>.*?)\}\s*(?P<alias>[A-Za-z_][A-Za-z0-9_]*)?\s*;", re.DOTALL)
C_ENUM_CONSTANT_PATTERN = re.compile(r"\b(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b\s*(?:=\s*[^,}]+)?(?:,|$)")
CS_IMPORT_PATTERN = re.compile(r"^\s*using\s+(?P<module>[A-Za-z_][A-Za-z0-9_\.]*)\s*;", re.MULTILINE)
CS_NAMESPACE_PATTERN = re.compile(r"^\s*namespace\s+(?P<name>[A-Za-z_][A-Za-z0-9_\.]*)", re.MULTILINE)
CS_REFERENCE_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
CS_MEMBER_PATTERN = re.compile(r"^\s*(?:public|private|protected|internal)?\s*(?:static\s+|virtual\s+|override\s+|async\s+|partial\s+|sealed\s+|abstract\s+)*(?:class|interface|record|struct|enum|delegate|[A-Za-z_][A-Za-z0-9_<>,\[\]\?\s]*\s+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:|\{|where|$)", re.MULTILINE)

GENERIC_REFERENCE_TOKENS = {
    "arguments",
    "Array",
    "Boolean",
    "className",
    "console",
    "const",
    "default",
    "document",
    "else",
    "event",
    "export",
    "false",
    "for",
    "function",
    "if",
    "import",
    "interface",
    "JSON",
    "let",
    "Math",
    "new",
    "null",
    "return",
    "string",
    "switch",
    "true",
    "type",
    "undefined",
    "var",
    "window",
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


def _is_useful_reference(name: str, current_name: str = "") -> bool:
    token = str(name or "").strip()
    if not token or token == current_name:
        return False
    if token in GENERIC_REFERENCE_TOKENS:
        return False
    if len(token) <= 2 and token.islower():
        return False
    return True


def _node_text(source_bytes: bytes, node) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _typescript_symbol_kind(name: str, node_type: str) -> str:
    if node_type in {"class_declaration"}:
        return "class"
    if node_type in {"interface_declaration", "type_alias_declaration"}:
        return "interface"
    if name.startswith("use"):
        return "hook"
    if name[:1].isupper():
        return "component"
    return "function"


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


def _line_number_for_offset(source: str, offset: int) -> int:
    return source.count("\n", 0, max(offset, 0)) + 1


def _clean_symbol_name(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        return ""
    if "::" in value:
        value = value.split("::")[-1]
    if "." in value and not value.startswith("."):
        value = value.split(".")[-1]
    return value.strip("*&() ")


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
    references = sorted({_clean_symbol_name(token) for token in C_REFERENCE_PATTERN.findall(body_text) if _is_useful_reference(_clean_symbol_name(token), current_name)})
    calls = sorted({_clean_symbol_name(match.group(1)) for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_:>]*)\s*\(", body_text) if _is_useful_reference(_clean_symbol_name(match.group(1)), current_name)})
    return calls, references


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


def _csharp_calls_and_references(body_text: str, current_name: str) -> tuple[list[str], list[str]]:
    references = sorted({_clean_symbol_name(token) for token in CS_REFERENCE_PATTERN.findall(body_text) if _is_useful_reference(_clean_symbol_name(token), current_name)})
    calls = sorted({_clean_symbol_name(match.group(1)) for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_\.]*)\s*\(", body_text) if _is_useful_reference(_clean_symbol_name(match.group(1)), current_name)})
    return calls, references


def _append_c_macro_symbols(source: str, imports: list[str], symbols: list[SymbolRecord], language_name: str) -> None:
    for match in C_DEFINE_PATTERN.finditer(source):
        name = match.group("name")
        if not name:
            continue
        body = match.group("body") or ""
        line_number = _line_number_for_offset(source, match.start())
        _, references = _c_calls_and_references(body, name)
        symbols.append(
            SymbolRecord(
                name=name,
                qualified_name=name,
                kind="macro",
                start_line=line_number,
                end_line=line_number,
                signature=name,
                metadata={"parser": "regex_macro", "language": language_name, "imports": imports, "calls": [], "references": references},
            )
        )


def _append_c_typedef_and_enum_symbols(source: str, imports: list[str], symbols: list[SymbolRecord], language_name: str) -> None:
    for match in C_TYPEDEF_ALIAS_PATTERN.finditer(source):
        name = match.group("name")
        if not name:
            continue
        line_number = _line_number_for_offset(source, match.start())
        symbols.append(
            SymbolRecord(
                name=name,
                qualified_name=name,
                kind="typedef",
                start_line=line_number,
                end_line=line_number,
                signature=name,
                metadata={"parser": "regex_typedef", "language": language_name, "imports": imports, "calls": [], "references": []},
            )
        )
    for match in C_ENUM_BLOCK_PATTERN.finditer(source):
        enum_name = match.group("enum_name") or match.group("alias") or ""
        body = match.group("body") or ""
        base_line = _line_number_for_offset(source, match.start())
        if enum_name:
            symbols.append(
                SymbolRecord(
                    name=enum_name,
                    qualified_name=enum_name,
                    kind="type",
                    start_line=base_line,
                    end_line=_line_number_for_offset(source, match.end()),
                    signature=enum_name,
                    metadata={"parser": "regex_enum", "language": language_name, "imports": imports, "calls": [], "references": []},
                )
            )
        for enumerator_match in C_ENUM_CONSTANT_PATTERN.finditer(body):
            constant_name = enumerator_match.group("name")
            if not constant_name:
                continue
            line_number = base_line + body[:enumerator_match.start()].count("\n")
            symbols.append(
                SymbolRecord(
                    name=constant_name,
                    qualified_name=f"{enum_name}.{constant_name}" if enum_name else constant_name,
                    kind="constant",
                    start_line=line_number,
                    end_line=line_number,
                    signature=constant_name,
                    metadata={"parser": "regex_enum", "language": language_name, "imports": imports, "calls": [], "references": []},
                )
            )


def _python_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _python_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _python_name(node.func)
    return None


def _python_symbol_kind(node: ast.AST, parents: list[str]) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    if parents:
        return "method"
    return "function"


def extract_symbols(file_path: Path) -> list[SymbolRecord]:
    symbols, _ = extract_symbols_with_status(file_path)
    return symbols


def extract_symbols_with_status(file_path: Path) -> tuple[list[SymbolRecord], dict[str, object]]:
    suffix = file_path.suffix.lower()
    if suffix == ".py":
        symbols = _extract_python_symbols(file_path)
        return symbols, {"parser": "ast", "symbol_count": len(symbols), "language": "python"}
    if suffix in {".ts", ".tsx", ".js", ".jsx"}:
        symbols = _extract_typescript_symbols(file_path)
        parser_name = str(symbols[0].metadata.get("parser", "regex_fallback") if symbols else "regex_fallback")
        return symbols, {"parser": parser_name, "symbol_count": len(symbols), "language": "typescript"}
    if suffix in {".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"}:
        return _extract_c_family_symbols_with_status(file_path)
    if suffix == ".cs":
        symbols = _extract_csharp_symbols(file_path)
        parser_name = str(symbols[0].metadata.get("parser", "regex_fallback") if symbols else "regex_fallback")
        return symbols, {"parser": parser_name, "symbol_count": len(symbols), "language": "csharp"}
    if suffix in {".csproj", ".sln"}:
        symbols = _extract_project_file_symbols(file_path)
        return symbols, {"parser": "text", "symbol_count": len(symbols), "language": "csharp_project"}
    return [], {"parser": "none", "symbol_count": 0, "language": "unknown"}


def _extract_c_family_symbols_with_status(file_path: Path) -> tuple[list[SymbolRecord], dict[str, object]]:
    language_name = "cpp" if file_path.suffix.lower() in {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"} else "c"
    clang_status = clang_runtime_status()
    if clang_available():
        parsed = extract_clang_symbols(file_path)
        if parsed:
            return parsed, {"parser": "clang", "symbol_count": len(parsed), "language": language_name, "clang": clang_status}
    parser = _tree_sitter_parser(language_name)
    if parser is not None:
        parsed = _extract_c_family_symbols_tree_sitter(file_path, parser, language_name)
        if parsed:
            return parsed, {"parser": "tree_sitter", "symbol_count": len(parsed), "language": language_name, "clang": clang_status}
    parsed = _extract_c_family_symbols_regex(file_path, language_name)
    return parsed, {"parser": "regex", "symbol_count": len(parsed), "language": language_name, "clang": clang_status}


def _extract_python_symbols(file_path: Path) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    symbols: list[SymbolRecord] = []
    file_imports: set[str] = set()
    file_references: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                file_imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name:
                file_imports.add(module_name)
            for alias in node.names:
                if module_name:
                    file_imports.add(f"{module_name}.{alias.name}")
                else:
                    file_imports.add(alias.name)
        elif isinstance(node, ast.Name):
            file_references.add(node.id)

    def visit(node: ast.AST, parents: list[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            qualified_name = ".".join([*parents, node.name]) if parents else node.name
            end_line = getattr(node, "end_lineno", node.lineno)
            calls = sorted(
                {
                    name
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    for name in [_python_name(child.func)]
                    if name
                }
            )
            references = sorted(
                {
                    name
                    for child in ast.walk(node)
                    if isinstance(child, ast.Name)
                    for name in [child.id]
                    if _is_useful_reference(name, node.name)
                }
            )
            symbols.append(
                SymbolRecord(
                    name=node.name,
                    qualified_name=qualified_name,
                    kind=_python_symbol_kind(node, parents),
                    start_line=node.lineno,
                    end_line=end_line,
                    signature=qualified_name,
                    metadata={
                        "parser": "ast",
                        "imports": sorted(file_imports),
                        "calls": calls,
                        "references": references,
                        "parent_chain": parents,
                    },
                )
            )
            next_parents = [*parents, node.name]
        else:
            next_parents = parents
        for child in ast.iter_child_nodes(node):
            visit(child, next_parents)

    visit(tree, [])
    symbols.sort(key=lambda symbol: (symbol.start_line, symbol.name))
    return symbols


def _tree_sitter_parser(language_name: str):
    if Parser is None or get_language is None:
        return None
    parser = Parser()
    language = get_language(language_name)
    if hasattr(parser, "set_language"):
        parser.set_language(language)
    else:
        parser.language = language
    return parser


def _extract_c_family_symbols(file_path: Path) -> list[SymbolRecord]:
    symbols, _ = _extract_c_family_symbols_with_status(file_path)
    return symbols


def _extract_c_family_symbols_tree_sitter(file_path: Path, parser, language_name: str) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    build_context = load_native_build_context(str(file_path))
    macros = extract_macro_definitions(source, build_context)
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
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
                name = _clean_symbol_name(_node_text(source_bytes, name_node))
                if name:
                    body_text = _node_text(source_bytes, node)
                    expanded_text = expand_object_like_macros(body_text, macros)
                    calls, references = _c_calls_and_references(expanded_text, name)
                    is_definition = node.type == "function_definition"
                    is_declaration = node.type in {"function_declarator", "declaration"} and not is_definition and body_text.strip().endswith(";")
                    qualified_name, signature = _c_qualified_name(file_path, name, body_text)
                    metadata = _c_symbol_metadata(file_path, language_name, imports, calls, references, is_definition=is_definition, is_declaration=is_declaration, parser_name="tree_sitter", node_type=node.type)
                    metadata["build_context"] = build_context
                    symbols.append(
                        SymbolRecord(
                            name=name,
                            qualified_name=qualified_name,
                            kind=_c_family_symbol_kind(name, node.type, language_name),
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            signature=signature,
                            metadata=metadata,
                        )
                    )
        for child in node.children:
            walk(child)

    walk(root)
    _append_c_macro_symbols(source, imports, symbols, language_name)
    _append_c_typedef_and_enum_symbols(source, imports, symbols, language_name)
    return _dedupe_symbols(symbols)


def _extract_c_family_symbols_regex(file_path: Path, language_name: str) -> list[SymbolRecord]:
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
            symbols.append(SymbolRecord(name=name, qualified_name=qualified_name, kind="function", start_line=line_number, end_line=line_number, signature=signature, metadata=metadata))
            continue
        decl_match = C_FUNCTION_DECL_PATTERN.search(line)
        if decl_match is not None:
            name = decl_match.group("name")
            qualified_name, signature = _c_qualified_name(file_path, name, line)
            metadata = _c_symbol_metadata(file_path, language_name, imports, [], [], is_declaration=True, parser_name="regex_fallback", node_type="function_declaration")
            metadata["build_context"] = build_context
            symbols.append(SymbolRecord(name=name, qualified_name=qualified_name, kind="function", start_line=line_number, end_line=line_number, signature=signature, metadata=metadata))
    _append_c_macro_symbols(source, imports, symbols, language_name)
    _append_c_typedef_and_enum_symbols(source, imports, symbols, language_name)
    return _dedupe_symbols(symbols)


def _extract_csharp_symbols(file_path: Path) -> list[SymbolRecord]:
    parser = _tree_sitter_parser("c_sharp")
    if parser is not None:
        parsed = _extract_csharp_symbols_tree_sitter(file_path, parser)
        if parsed:
            return parsed
    return _extract_csharp_symbols_regex(file_path)


def _extract_csharp_symbols_tree_sitter(file_path: Path, parser) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
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
                name = _node_text(source_bytes, name_node).strip()
                qualified_name = ".".join([*parents, name]) if parents else name
                body_text = _node_text(source_bytes, node)
                calls, references = _csharp_calls_and_references(body_text, name)
                symbols.append(SymbolRecord(name=name, qualified_name=qualified_name, kind=_csharp_symbol_kind(name, node.type), start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1, signature=qualified_name, metadata={"parser": "tree_sitter", "language": "csharp", "node_type": node.type, "imports": imports, "calls": calls, "references": references, "parent_chain": parents, "namespace": ".".join(parents[:1]) if parents else ""}))
                if node.type in {"namespace_declaration", "file_scoped_namespace_declaration", "class_declaration", "interface_declaration", "record_declaration", "struct_declaration", "enum_declaration"}:
                    next_parents = [*parents, name]
        for child in node.children:
            walk(child, next_parents)

    walk(root, [])
    return _dedupe_symbols(symbols)


def _extract_csharp_symbols_regex(file_path: Path) -> list[SymbolRecord]:
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
        symbols.append(SymbolRecord(name=name, qualified_name=qualified_name, kind=kind, start_line=line_number, end_line=line_number, signature=qualified_name, metadata={"parser": "regex_fallback", "language": "csharp", "imports": imports, "calls": [], "references": [], "namespace": namespace_name}))
    return _dedupe_symbols(symbols)


def _extract_project_file_symbols(file_path: Path) -> list[SymbolRecord]:
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
            metadata={"parser": "text", "language": "csharp_project", "imports": sorted(references), "calls": [], "references": sorted(references), "project_references": sorted(references)},
        )
    ]


def _dedupe_symbols(symbols: list[SymbolRecord]) -> list[SymbolRecord]:
    seen: set[tuple[str, int, str]] = set()
    deduped: list[SymbolRecord] = []
    for symbol in sorted(symbols, key=lambda item: (item.start_line, item.end_line, item.qualified_name)):
        key = (symbol.qualified_name, symbol.start_line, symbol.kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(symbol)
    return deduped


def _extract_typescript_symbols(file_path: Path) -> list[SymbolRecord]:
    if Parser is not None and get_language is not None:
        parsed = _extract_typescript_symbols_tree_sitter(file_path)
        if parsed:
            return parsed
    return _extract_typescript_symbols_regex(file_path)


def _extract_typescript_symbols_tree_sitter(file_path: Path) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8")
    source_bytes = source.encode("utf-8")
    language_name = "tsx" if file_path.suffix.lower() in {".tsx", ".jsx"} else "typescript"
    parser = Parser()
    language = get_language(language_name)
    if hasattr(parser, "set_language"):
        parser.set_language(language)
    else:
        parser.language = language
    tree = parser.parse(source_bytes)
    root = tree.root_node
    symbols: list[SymbolRecord] = []
    imports = sorted({match.group("module") for match in TS_IMPORT_PATTERN.finditer(source)} | {match.group("module") for match in TS_REQUIRE_PATTERN.finditer(source)})

    def walk(node) -> None:
        if node.type in {"function_declaration", "class_declaration", "method_definition", "lexical_declaration", "variable_declarator", "interface_declaration", "type_alias_declaration"}:
            name_node = node.child_by_field_name("name")
            if name_node is None and node.type == "lexical_declaration":
                for child in node.children:
                    walk(child)
                return
            if name_node is not None:
                name = _node_text(source_bytes, name_node)
                body_text = _node_text(source_bytes, node)
                calls = sorted(
                    {
                        match.group(1)
                        for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", body_text)
                        if _is_useful_reference(match.group(1), name)
                    }
                )
                references = sorted(
                    {
                        identifier
                        for identifier in TS_IDENTIFIER_PATTERN.findall(body_text)
                        if _is_useful_reference(identifier, name)
                    }
                )
                kind = _typescript_symbol_kind(name, node.type)
                symbols.append(
                    SymbolRecord(
                        name=name,
                        qualified_name=name,
                        kind=kind,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=name,
                        metadata={
                            "parser": "tree_sitter",
                            "node_type": node.type,
                            "imports": imports,
                            "calls": calls,
                            "references": references,
                        },
                    )
                )
        for child in node.children:
            walk(child)

    walk(root)
    return symbols


def _extract_typescript_symbols_regex(file_path: Path) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8")
    symbols: list[SymbolRecord] = []
    imports = sorted({match.group("module") for match in TS_IMPORT_PATTERN.finditer(source)} | {match.group("module") for match in TS_REQUIRE_PATTERN.finditer(source)})
    for line_number, line in enumerate(source.splitlines(), start=1):
        interface_match = TS_INTERFACE_PATTERN.search(line)
        if interface_match is not None:
            name = interface_match.group("name")
            symbols.append(
                SymbolRecord(
                    name=name,
                    qualified_name=name,
                    kind="interface",
                    start_line=line_number,
                    end_line=line_number,
                    signature=name,
                    metadata={"parser": "regex_fallback", "imports": imports, "calls": [], "references": []},
                )
            )
            continue
        type_match = TS_TYPE_PATTERN.search(line)
        if type_match is not None:
            name = type_match.group("name")
            symbols.append(
                SymbolRecord(
                    name=name,
                    qualified_name=name,
                    kind="interface",
                    start_line=line_number,
                    end_line=line_number,
                    signature=name,
                    metadata={"parser": "regex_fallback", "imports": imports, "calls": [], "references": []},
                )
            )
            continue
        match = TS_FUNCTION_PATTERN.search(line)
        if match is None:
            continue
        name = match.group("name1") or match.group("name2") or match.group("name3") or match.group("name4") or "anonymous"
        symbols.append(
            SymbolRecord(
                name=name,
                qualified_name=name,
                kind=_typescript_symbol_kind(name, "regex_fallback"),
                start_line=line_number,
                end_line=line_number,
                signature=name,
                metadata={"parser": "regex_fallback", "imports": imports, "calls": [], "references": []},
            )
        )
    return symbols
