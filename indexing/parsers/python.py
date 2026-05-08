from __future__ import annotations

import ast
from pathlib import Path

from indexing.parser_registry import ParserRegistry
from indexing.parsers.common import is_useful_reference
from models.entity_models import SymbolRecord


def _python_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _python_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _python_name(node.func)
    return None


def _python_attribute_accesses(node: ast.AST) -> list[str]:
    accesses: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            name = _python_name(child)
            if name and "." in name:
                accesses.add(name)
    return sorted(accesses)


def _python_base_names(node: ast.ClassDef) -> list[str]:
    bases: list[str] = []
    for base in node.bases:
        name = _python_name(base)
        if name and name not in bases:
            bases.append(name)
    return bases


def _python_symbol_kind(node: ast.AST, parents: list[str]) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    if parents:
        return "method"
    return "function"


def extract_symbols(file_path: Path) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    symbols: list[SymbolRecord] = []
    file_imports: set[str] = set()
    import_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                file_imports.add(alias.name)
                import_aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name:
                file_imports.add(module_name)
            for alias in node.names:
                if module_name:
                    file_imports.add(f"{module_name}.{alias.name}")
                else:
                    file_imports.add(alias.name)
                import_aliases[alias.asname or alias.name] = alias.name

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
                    if is_useful_reference(name, node.name)
                }
            )
            extends = _python_base_names(node) if isinstance(node, ast.ClassDef) else []
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
                        "accesses": _python_attribute_accesses(node),
                        "extends": extends,
                        "implements": [],
                        "parent_chain": parents,
                        "import_aliases": import_aliases,
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


def parse(file_path: Path):
    from indexing.parser_registry import ParseOutcome

    symbols = extract_symbols(file_path)
    return ParseOutcome(symbols, {"parser": "ast", "symbol_count": len(symbols), "language": "python"})


def register(registry: ParserRegistry) -> None:
    registry.register_extension(".py", parse)
