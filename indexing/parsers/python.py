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


def _format_annotation(node: ast.AST | None) -> str:
    """Format a type annotation node as a string."""
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _format_annotation(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        base = _format_annotation(node.value)
        slc = _format_annotation(node.slice)
        return f"{base}[{slc}]" if base else f"[{slc}]"
    if isinstance(node, ast.Tuple):
        parts = [_format_annotation(elt) for elt in node.elts]
        return ", ".join(p for p in parts if p)
    if isinstance(node, ast.Constant):
        return repr(node.value) if node.value is not None else "None"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _format_annotation(node.left)
        right = _format_annotation(node.right)
        return f"{left} | {right}" if left and right else left or right
    if isinstance(node, ast.List):
        parts = [_format_annotation(elt) for elt in node.elts]
        return f"[{', '.join(parts)}]"
    if isinstance(node, ast.Dict):
        keys = [_format_annotation(k) for k in node.keys]
        vals = [_format_annotation(v) for v in node.values]
        return f"{{{', '.join(f'{k}: {v}' for k, v in zip(keys, vals) if k and v)}}}"
    return ""


def _extract_type_hints(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, object]:
    """Extract type hints from a function definition.

    Returns a dict with:
    - params: list of {name, type, default} for each parameter
    - return_type: the return annotation
    - signature_with_types: a formatted signature string
    """
    params: list[dict[str, str]] = []
    args = node.args

    def _process_arg(arg: ast.arg, default: ast.AST | None = None) -> dict[str, str]:
        return {
            "name": arg.arg,
            "type": _format_annotation(arg.annotation),
            "default": _format_annotation(default) if default else "",
        }

    defaults = list(args.defaults)
    pos_defaults_offset = len(args.args) - len(defaults)

    for i, arg in enumerate(args.args):
        default = defaults[i - pos_defaults_offset] if i >= pos_defaults_offset else None
        params.append(_process_arg(arg, default))

    if args.vararg:
        params.append({
            "name": f"*{args.vararg.arg}",
            "type": _format_annotation(args.vararg.annotation),
            "default": "",
        })

    for i, arg in enumerate(args.kwonlyargs):
        default = args.kw_defaults[i] if i < len(args.kw_defaults) else None
        params.append(_process_arg(arg, default))

    if args.kwarg:
        params.append({
            "name": f"**{args.kwarg.arg}",
            "type": _format_annotation(args.kwarg.annotation),
            "default": "",
        })

    return_type = _format_annotation(node.returns) if node.returns else ""

    param_strs = []
    for p in params:
        s = p["name"]
        if p["type"]:
            s += f": {p['type']}"
        if p["default"]:
            s += f" = {p['default']}"
        param_strs.append(s)

    signature_with_types = f"({', '.join(param_strs)})"
    if return_type:
        signature_with_types += f" -> {return_type}"

    return {
        "params": params,
        "return_type": return_type,
        "signature_with_types": signature_with_types,
    }


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
            type_hints = _extract_type_hints(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else {}
            typed_sig = str(type_hints.get("signature_with_types", "")) if type_hints else ""
            symbols.append(
                SymbolRecord(
                    name=node.name,
                    qualified_name=qualified_name,
                    kind=_python_symbol_kind(node, parents),
                    start_line=node.lineno,
                    end_line=end_line,
                    signature=typed_sig or qualified_name,
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
                        "type_hints": type_hints,
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
