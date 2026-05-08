from __future__ import annotations

import re
from pathlib import Path

from indexing.parser_registry import ParserRegistry
from indexing.parsers.common import is_useful_reference, node_text, tree_sitter_parser
from indexing.tree_cache import parse_with_cache
from models.entity_models import SymbolRecord
from services.route_parsing import consumer_keys, frontend_route_usages, normalize_route


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
TS_DEFAULT_EXPORT_PATTERN = re.compile(r"export\s+default\s+(?:function|class)?\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)?")
TS_IMPORT_CLAUSE_PATTERN = re.compile(r"^\s*import\s+(?P<clause>[^\n]+?)\s+from\s+['\"](?P<module>[^'\"]+)['\"]", re.MULTILINE)
TS_REEXPORT_NAMED_PATTERN = re.compile(r"^\s*export\s+\{(?P<clause>[^}]+)\}\s+from\s+['\"](?P<module>[^'\"]+)['\"]", re.MULTILINE)
TS_REEXPORT_STAR_PATTERN = re.compile(r"^\s*export\s+\*\s+from\s+['\"](?P<module>[^'\"]+)['\"]", re.MULTILINE)
TS_NAMESPACE_REEXPORT_PATTERN = re.compile(r"^\s*export\s+\*\s+as\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s+from\s+['\"](?P<module>[^'\"]+)['\"]", re.MULTILINE)

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
}


def _property_accesses(source: str, current_name: str = "") -> list[str]:
    accesses: set[str] = set()
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)((?:\.[A-Za-z_][A-Za-z0-9_]*)+)", source):
        base = match.group(1)
        if not is_useful_reference(base, current_name, GENERIC_REFERENCE_TOKENS):
            continue
        parts = [base, *[part for part in match.group(2).split(".") if part]]
        for index in range(2, len(parts) + 1):
            accesses.add(".".join(parts[:index]))
    return sorted(accesses)


def _inheritance_metadata(source: str, name: str, kind: str) -> dict[str, list[str]]:
    prefix = "interface" if kind == "interface" else "class"
    pattern = re.compile(
        rf"\b{prefix}\s+{re.escape(name)}(?:\s+extends\s+(?P<extends>[^{{]+?))?(?:\s+implements\s+(?P<implements>[^{{]+?))?\s*{{",
        re.MULTILINE,
    )
    match = pattern.search(source)
    if match is None:
        return {"extends": [], "implements": []}

    def split_names(value: str | None) -> list[str]:
        names: list[str] = []
        for item in str(value or "").split(","):
            token = item.strip().split("<", 1)[0].strip()
            if token and is_useful_reference(token, name, GENERIC_REFERENCE_TOKENS):
                names.append(token)
        return names

    extends = split_names(match.group("extends"))
    implements = split_names(match.group("implements")) if kind == "class" else []
    return {"extends": extends, "implements": implements}


def _api_contract_metadata(source: str) -> dict[str, object]:
    routes: list[str] = []
    for usage in frontend_route_usages(source, language="tsx"):
        route = normalize_route(str(usage.get("route", "") or ""))
        if route and route not in routes:
            routes.append(route)
    flat_reads, nested_reads = consumer_keys(source)
    field_reads = []
    for value in [*flat_reads, *nested_reads]:
        text = str(value or "").strip()
        if text and text not in field_reads:
            field_reads.append(text)
    return {"fetches": routes, "field_reads": field_reads}


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


def _module_name(file_path: Path) -> str:
    normalized = file_path.with_suffix("")
    if normalized.is_absolute():
        parts = [part for part in normalized.parts if part not in {normalized.anchor, "", "/", "\\"}]
        trimmed = parts[-2:] if len(parts) >= 2 else parts[-1:]
        return ".".join(trimmed)
    return normalized.as_posix().replace("/", ".")


def _qualified_name(module_name: str, parent_name: str, name: str) -> str:
    normalized_parent = parent_name
    if normalized_parent and module_name.endswith(f".{normalized_parent}"):
        normalized_parent = ""
    if normalized_parent:
        return f"{module_name}.{normalized_parent}.{name}"
    return f"{module_name}.{name}"


def _node_export_flags(node, source_bytes: bytes) -> dict[str, object]:
    text = node_text(source_bytes, node)
    is_exported = "export" in text[:80]
    is_default = "export default" in text[:120]
    return {"exported": is_exported, "default_export": is_default}


def _module_import_terms(module_value: str) -> list[str]:
    module_text = str(module_value or "").strip()
    if not module_text:
        return []
    values: list[str] = [module_text]
    tail = module_text.split("/")[-1]
    if tail and tail not in values:
        values.append(tail)
    stem = tail.rsplit(".", 1)[0] if "." in tail else tail
    if stem and stem not in values:
        values.append(stem)
    return values


def _normalized_path_text(path: Path) -> str:
    return path.as_posix().replace("//", "/")


def _resolved_module_paths(file_path: Path, module_value: str) -> list[str]:
    module_text = str(module_value or "").strip()
    if not module_text.startswith("."):
        return []
    base = (file_path.parent / module_text)
    candidates: list[Path] = []
    if base.suffix.lower() in {".ts", ".tsx", ".js", ".jsx"}:
        candidates.append(base)
    else:
        for extension in (".ts", ".tsx", ".js", ".jsx"):
            candidates.append(base.with_suffix(extension))
        for index_name in ("index.ts", "index.tsx", "index.js", "index.jsx"):
            candidates.append(base / index_name)
    normalized: list[str] = []
    for candidate in candidates:
        value = _normalized_path_text(candidate)
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _reexport_statements(source: str) -> list[dict[str, object]]:
    statements: list[dict[str, object]] = []
    for match in TS_NAMESPACE_REEXPORT_PATTERN.finditer(source):
        alias = str(match.group("alias") or "").strip()
        statements.append({"module": str(match.group("module") or "").strip(), "exported_names": [alias] if alias else [], "aliases": {alias: "__namespace__"} if alias else {}, "export_all": False, "namespace_export": True})
    for match in TS_REEXPORT_NAMED_PATTERN.finditer(source):
        clause = str(match.group("clause") or "")
        exported_names: list[str] = []
        aliases: dict[str, str] = {}
        for item in clause.split(","):
            token = str(item or "").strip()
            if not token:
                continue
            if " as " in token:
                original, alias = [part.strip() for part in token.split(" as ", 1)]
                if original and alias:
                    exported_names.append(alias)
                    aliases[alias] = original
            else:
                exported_names.append(token)
                aliases[token] = token
        statements.append({"module": str(match.group("module") or "").strip(), "exported_names": exported_names, "aliases": aliases, "export_all": False, "namespace_export": False})
    for match in TS_REEXPORT_STAR_PATTERN.finditer(source):
        statements.append({"module": str(match.group("module") or "").strip(), "exported_names": [], "aliases": {}, "export_all": True, "namespace_export": False})
    return statements


def _import_terms(source: str) -> list[str]:
    values: list[str] = []

    def add_value(value: str) -> None:
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)

    for match in TS_IMPORT_PATTERN.finditer(source):
        for value in _module_import_terms(match.group("module")):
            add_value(value)
    for match in TS_REQUIRE_PATTERN.finditer(source):
        for value in _module_import_terms(match.group("module")):
            add_value(value)
    for match in TS_IMPORT_CLAUSE_PATTERN.finditer(source):
        clause = str(match.group("clause") or "").strip()
        normalized_clause = clause.replace("{", " ").replace("}", " ").replace(",", " ")
        for token in normalized_clause.split():
            if token == "as":
                continue
            if is_useful_reference(token, ignored_tokens=GENERIC_REFERENCE_TOKENS):
                add_value(token)
    for statement in _reexport_statements(source):
        module_value = str(statement.get("module") or "")
        for value in _module_import_terms(module_value):
            add_value(value)
        for exported_name in statement.get("exported_names", []):
            if is_useful_reference(str(exported_name), ignored_tokens=GENERIC_REFERENCE_TOKENS):
                add_value(str(exported_name))
    return values


def _import_aliases(source: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for match in TS_IMPORT_CLAUSE_PATTERN.finditer(source):
        clause = str(match.group("clause") or "").strip()
        namespace_match = re.match(r"\*\s+as\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)$", clause)
        if namespace_match is not None:
            alias = str(namespace_match.group("alias") or "").strip()
            if alias:
                aliases[alias] = "__namespace__"
            continue
        namespace_suffix_match = re.search(r"(?:^|,)\s*\*\s+as\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)$", clause)
        if namespace_suffix_match is not None:
            alias = str(namespace_suffix_match.group("alias") or "").strip()
            if alias:
                aliases[alias] = "__namespace__"
        named_match = re.search(r"\{(?P<named>[^}]+)\}", clause)
        if named_match is not None:
            for item in str(named_match.group("named") or "").split(","):
                token = str(item or "").strip()
                if not token:
                    continue
                if " as " in token:
                    original, alias = [part.strip() for part in token.split(" as ", 1)]
                    if original and alias:
                        aliases[alias] = original
                elif is_useful_reference(token, ignored_tokens=GENERIC_REFERENCE_TOKENS):
                    aliases[token] = token
        default_clause = clause.split("{", 1)[0].strip().rstrip(",")
        if "," in default_clause:
            default_clause = default_clause.split(",", 1)[0].strip()
        if default_clause and is_useful_reference(default_clause, ignored_tokens=GENERIC_REFERENCE_TOKENS):
            aliases.setdefault(default_clause, "default")
    for statement in _reexport_statements(source):
        reexport_aliases = statement.get("aliases", {})
        if isinstance(reexport_aliases, dict):
            for alias, original in reexport_aliases.items():
                alias_text = str(alias or "").strip()
                original_text = str(original or "").strip()
                if alias_text and original_text:
                    aliases.setdefault(alias_text, original_text)
    return aliases


def _exported_names(symbols: list[SymbolRecord], reexport_statements: list[dict[str, object]]) -> list[str]:
    names: list[str] = []
    for symbol in symbols:
        if bool(symbol.metadata.get("exported")) or bool(symbol.metadata.get("default_export")):
            if symbol.name not in names:
                names.append(symbol.name)
    for statement in reexport_statements:
        for exported_name in statement.get("exported_names", []):
            name = str(exported_name or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def _source_associations(file_path: Path, source: str) -> list[str]:
    associations: list[str] = []
    module_values = [str(match.group("module") or "").strip() for match in TS_IMPORT_PATTERN.finditer(source)]
    module_values.extend(str(match.group("module") or "").strip() for match in TS_REQUIRE_PATTERN.finditer(source))
    module_values.extend(str(statement.get("module") or "").strip() for statement in _reexport_statements(source))
    for module_value in module_values:
        for resolved in _resolved_module_paths(file_path, module_value):
            if resolved not in associations:
                associations.append(resolved)
    return associations


def _append_reexport_module_symbol(
    symbols: list[SymbolRecord],
    file_path: Path,
    module_name: str,
    imports: list[str],
    import_aliases: dict[str, str],
    source_associations: list[str],
    reexport_statements: list[dict[str, object]],
    total_lines: int,
) -> None:
    exported_names = _exported_names(symbols, reexport_statements)
    if not reexport_statements and not exported_names:
        return
    if any(symbol.name == "exports" and symbol.kind == "module" for symbol in symbols):
        return
    symbols.append(
        SymbolRecord(
            name="exports",
            qualified_name=_qualified_name(module_name, "", "exports"),
            kind="module",
            start_line=1,
            end_line=max(total_lines, 1),
            signature="exports",
            metadata={
                "parser": "regex_fallback",
                "language": "typescript",
                "node_type": "reexport_module",
                "imports": imports,
                "calls": [],
                "references": [],
                "accesses": [],
                "fetches": [],
                "field_reads": [],
                "module": module_name,
                "parent": "",
                "import_aliases": import_aliases,
                "source_associations": source_associations,
                "re_exports": reexport_statements,
                "export_names": exported_names,
                "exported": True,
                "default_export": False,
            },
        )
    )


def _record_symbol(
    symbols: list[SymbolRecord],
    source_bytes: bytes,
    module_name: str,
    name: str,
    node,
    kind: str,
    imports: list[str],
    parent_name: str = "",
    extra_metadata: dict[str, object] | None = None,
) -> None:
    body_text = node_text(source_bytes, node)
    namespace_accesses = {
        f"{match.group(1)}.{match.group(2)}"
        for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", body_text)
        if is_useful_reference(match.group(1), name, GENERIC_REFERENCE_TOKENS)
        and is_useful_reference(match.group(2), name, GENERIC_REFERENCE_TOKENS)
    }
    calls = sorted(
        {
            match.group(1)
            for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", body_text)
            if is_useful_reference(match.group(1), name, GENERIC_REFERENCE_TOKENS)
        }
        | namespace_accesses
    )
    references = sorted(
        {
            identifier
            for identifier in TS_IDENTIFIER_PATTERN.findall(body_text)
            if is_useful_reference(identifier, name, GENERIC_REFERENCE_TOKENS)
        }
        | namespace_accesses
    )
    metadata = {
        "parser": "tree_sitter",
        "language": "typescript",
        "node_type": node.type,
        "imports": imports,
        "calls": calls,
        "references": references,
        "accesses": _property_accesses(body_text, name),
        **_api_contract_metadata(body_text),
        **_inheritance_metadata(body_text, name, kind),
        "module": module_name,
        "parent": parent_name,
        **_node_export_flags(node, source_bytes),
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    symbols.append(
        SymbolRecord(
            name=name,
            qualified_name=_qualified_name(module_name, parent_name, name),
            kind=kind,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            signature=name,
            metadata=metadata,
        )
    )


def extract_symbols(file_path: Path) -> list[SymbolRecord]:
    parsed = _extract_symbols_tree_sitter(file_path)
    if parsed:
        return parsed
    return _extract_symbols_regex(file_path)


def _extract_symbols_tree_sitter(file_path: Path) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8")
    source_bytes = source.encode("utf-8")
    language_name = "tsx" if file_path.suffix.lower() in {".tsx", ".jsx"} else "typescript"
    parser = tree_sitter_parser(language_name)
    if parser is None:
        return []
    tree = parse_with_cache(file_path, language_name, parser, source_bytes)
    root = tree.root_node
    symbols: list[SymbolRecord] = []
    imports = _import_terms(source)
    import_aliases = _import_aliases(source)
    source_associations = _source_associations(file_path, source)
    reexport_statements = _reexport_statements(source)
    module_name = _module_name(file_path)

    def walk(node, parent_name: str = "") -> None:
        if node.type in {"function_declaration", "class_declaration", "method_definition", "lexical_declaration", "variable_declarator", "interface_declaration", "type_alias_declaration"}:
            name_node = node.child_by_field_name("name")
            if name_node is None and node.type == "lexical_declaration":
                for child in node.children:
                    walk(child, parent_name=parent_name)
                return
            if name_node is not None:
                name = node_text(source_bytes, name_node)
                kind = _typescript_symbol_kind(name, node.type)
                active_parent = parent_name
                if node.type == "method_definition":
                    _record_symbol(symbols, source_bytes, module_name, name, node, kind, imports, parent_name=parent_name, extra_metadata={"import_aliases": import_aliases, "source_associations": source_associations, "re_exports": reexport_statements})
                else:
                    _record_symbol(symbols, source_bytes, module_name, name, node, kind, imports, parent_name=parent_name, extra_metadata={"import_aliases": import_aliases, "source_associations": source_associations, "re_exports": reexport_statements})
                    if node.type == "class_declaration":
                        active_parent = name
                for child in node.children:
                    walk(child, parent_name=active_parent)
                return
        if node.type in {"export_statement", "statement_block", "class_body", "program"}:
            for child in node.children:
                walk(child, parent_name=parent_name)
            return
        for child in node.children:
            walk(child, parent_name=parent_name)

    walk(root)
    default_export_match = TS_DEFAULT_EXPORT_PATTERN.search(source)
    if default_export_match is not None:
        name = default_export_match.group("name") or "default_export"
        if not any(symbol.name == name and bool(symbol.metadata.get("default_export")) for symbol in symbols):
            line_number = source[: default_export_match.start()].count("\n") + 1
            symbols.append(
                SymbolRecord(
                    name=name,
                    qualified_name=_qualified_name(module_name, "", name),
                    kind=_typescript_symbol_kind(name, "default_export"),
                    start_line=line_number,
                    end_line=line_number,
                    signature=name,
                    metadata={
                        "parser": "regex_fallback",
                        "language": "typescript",
                        "node_type": "default_export",
                        "imports": imports,
                        "calls": [],
                        "references": [],
                        "accesses": [],
                        "fetches": [],
                        "field_reads": [],
                        "module": module_name,
                        "parent": "",
                        "import_aliases": import_aliases,
                        "source_associations": source_associations,
                        "re_exports": reexport_statements,
                        "exported": True,
                        "default_export": True,
                    },
                )
            )
    _append_reexport_module_symbol(
        symbols,
        file_path,
        module_name,
        imports,
        import_aliases,
        source_associations,
        reexport_statements,
        len(source.splitlines()),
    )
    return symbols


def _extract_symbols_regex(file_path: Path) -> list[SymbolRecord]:
    source = file_path.read_text(encoding="utf-8")
    symbols: list[SymbolRecord] = []
    imports = _import_terms(source)
    import_aliases = _import_aliases(source)
    source_associations = _source_associations(file_path, source)
    reexport_statements = _reexport_statements(source)
    module_name = _module_name(file_path)
    for line_number, line in enumerate(source.splitlines(), start=1):
        interface_match = TS_INTERFACE_PATTERN.search(line)
        if interface_match is not None:
            name = interface_match.group("name")
            symbols.append(
                SymbolRecord(
                    name=name,
                    qualified_name=_qualified_name(module_name, "", name),
                    kind="interface",
                    start_line=line_number,
                    end_line=line_number,
                    signature=name,
                    metadata={"parser": "regex_fallback", "language": "typescript", "imports": imports, "calls": [], "references": [], "accesses": _property_accesses(line, name), **_api_contract_metadata(line), **_inheritance_metadata(line, name, "interface"), "module": module_name, "parent": "", "import_aliases": import_aliases, "source_associations": source_associations, "re_exports": reexport_statements, "exported": "export" in line, "default_export": "export default" in line},
                )
            )
            continue
        type_match = TS_TYPE_PATTERN.search(line)
        if type_match is not None:
            name = type_match.group("name")
            symbols.append(
                SymbolRecord(
                    name=name,
                    qualified_name=_qualified_name(module_name, "", name),
                    kind="interface",
                    start_line=line_number,
                    end_line=line_number,
                    signature=name,
                    metadata={"parser": "regex_fallback", "language": "typescript", "imports": imports, "calls": [], "references": [], "accesses": _property_accesses(line, name), **_api_contract_metadata(line), "extends": [], "implements": [], "module": module_name, "parent": "", "import_aliases": import_aliases, "exported": "export" in line, "default_export": "export default" in line},
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
                qualified_name=_qualified_name(module_name, "", name),
                kind=_typescript_symbol_kind(name, "regex_fallback"),
                start_line=line_number,
                end_line=line_number,
                signature=name,
                metadata={"parser": "regex_fallback", "language": "typescript", "imports": imports, "calls": [], "references": [], "accesses": _property_accesses(line, name), **_api_contract_metadata(line), "extends": [], "implements": [], "module": module_name, "parent": "", "import_aliases": import_aliases, "source_associations": source_associations, "re_exports": reexport_statements, "exported": "export" in line, "default_export": "export default" in line},
            )
        )
    _append_reexport_module_symbol(
        symbols,
        file_path,
        module_name,
        imports,
        import_aliases,
        source_associations,
        reexport_statements,
        len(source.splitlines()),
    )
    return symbols


def parse(file_path: Path):
    from indexing.parser_registry import ParseOutcome

    symbols = extract_symbols(file_path)
    parser_name = str(symbols[0].metadata.get("parser", "regex_fallback") if symbols else "regex_fallback")
    return ParseOutcome(symbols, {"parser": parser_name, "symbol_count": len(symbols), "language": "typescript"})


def register(registry: ParserRegistry) -> None:
    for extension in (".ts", ".tsx", ".js", ".jsx"):
        registry.register_extension(extension, parse)
