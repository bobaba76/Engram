import ast
import re
from pathlib import Path

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
    suffix = file_path.suffix.lower()
    if suffix == ".py":
        return _extract_python_symbols(file_path)
    if suffix in {".ts", ".tsx", ".js", ".jsx"}:
        return _extract_typescript_symbols(file_path)
    return []


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
                    if name and name != node.name
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
                        if match.group(1) != name
                    }
                )
                references = sorted(
                    {
                        identifier
                        for identifier in TS_IDENTIFIER_PATTERN.findall(body_text)
                        if identifier != name and identifier not in {"function", "class", "const", "let", "var", "return", "if", "else", "for", "while", "switch", "case", "import", "from", "export", "new"}
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
