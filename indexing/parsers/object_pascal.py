from __future__ import annotations

import re
from pathlib import Path

from indexing.parser_registry import ParseOutcome, ParserRegistry
from models.entity_models import SymbolRecord


USES_PATTERN = re.compile(r"\buses\s+(?P<body>.*?);", re.IGNORECASE | re.DOTALL)
INCLUDE_PATTERN = re.compile(r"\{\$\s*(?:I|INCLUDE)\s+(?P<path>[^}]+)\}", re.IGNORECASE)
CONDITIONAL_PATTERN = re.compile(r"\{\$\s*(?P<directive>IFDEF|IFNDEF|IFOPT|DEFINE|UNDEF)\s+(?P<symbol>[^}]+)\}", re.IGNORECASE)
UNIT_PATTERN = re.compile(r"^\s*(unit|program|library|package)\s+(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\s*;", re.IGNORECASE | re.MULTILINE)
TYPE_PATTERN = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<kind>class|record|interface|object)\s*(?:\((?P<ancestors>[^)]*)\))?", re.IGNORECASE | re.MULTILINE)
PROC_PATTERN = re.compile(r"^\s*(?P<kind>class\s+)?(?P<routine>procedure|function|constructor|destructor)\s+(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\s*(?P<signature>\([^;]*\))?", re.IGNORECASE | re.MULTILINE)
PROPERTY_PATTERN = re.compile(r"^\s*property\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE | re.MULTILINE)
FORM_OBJECT_PATTERN = re.compile(r"^\s*(?:object|inherited|inline)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<class>[A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE | re.MULTILINE)
FORM_BLOCK_PATTERN = re.compile(r"^(?P<indent>\s*)(?P<keyword>object|inherited|inline)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<class>[A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
FORM_EVENT_PATTERN = re.compile(r"^\s*(?P<event>On[A-Za-z0-9_]+)\s*=\s*(?P<handler>[A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE | re.MULTILINE)
FORM_PROPERTY_PATTERN = re.compile(r"^\s*(?P<property>DataSource|DataField|Action|PopupMenu|Images|ImageList|Menu|Parent|Controller|Provider|Dataset)\s*=\s*(?P<value>[^\r\n]+)", re.IGNORECASE | re.MULTILINE)
CALL_PATTERN = re.compile(r"\b(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\s*\(")
REFERENCE_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*\b")

KEYWORDS = {
    "and", "array", "as", "begin", "case", "class", "const", "constructor", "destructor", "div", "do", "downto",
    "else", "end", "except", "exports", "file", "finalization", "finally", "for", "function", "if", "implementation",
    "in", "inherited", "initialization", "inline", "interface", "is", "label", "library", "mod", "nil", "not", "object",
    "of", "or", "packed", "procedure", "program", "property", "raise", "record", "repeat", "resourcestring", "set",
    "shl", "shr", "string", "then", "threadvar", "to", "try", "type", "unit", "until", "uses", "var", "while", "with", "xor",
}


def _pascal_source_associations(file_path: Path) -> list[str]:
    stem = file_path.stem
    parent = file_path.parent
    suffix = file_path.suffix.lower()
    if suffix in {".pas", ".pp"}:
        return [str((parent / f"{stem}.dfm").as_posix()), str((parent / f"{stem}.lfm").as_posix())]
    if suffix in {".dfm", ".lfm"}:
        return [str((parent / f"{stem}.pas").as_posix()), str((parent / f"{stem}.pp").as_posix())]
    return []


def _line_number_for_offset(source: str, offset: int) -> int:
    return source.count("\n", 0, max(offset, 0)) + 1


def _module_name(source: str, file_path: Path) -> str:
    match = UNIT_PATTERN.search(source)
    if match:
        return str(match.group("name") or file_path.stem).strip()
    return file_path.stem


def _uses(source: str) -> list[str]:
    imports: list[str] = []
    for match in USES_PATTERN.finditer(source):
        body = re.sub(r"\{.*?\}|\(\*.*?\*\)|//.*?$", "", match.group("body"), flags=re.DOTALL | re.MULTILINE)
        for token in body.split(","):
            unit = token.strip().split()[0] if token.strip() else ""
            unit = unit.strip("'\"")
            if unit and unit not in imports:
                imports.append(unit)
    return imports


def _pascal_includes(source: str) -> list[str]:
    includes: list[str] = []
    for match in INCLUDE_PATTERN.finditer(source):
        value = str(match.group("path") or "").strip().strip("'\"")
        if value and value not in includes:
            includes.append(value)
    return includes


def _pascal_conditionals(source: str) -> list[dict[str, str]]:
    conditionals: list[dict[str, str]] = []
    for match in CONDITIONAL_PATTERN.finditer(source):
        directive = str(match.group("directive") or "").upper()
        symbol = str(match.group("symbol") or "").strip()
        if directive and symbol:
            conditionals.append({"directive": directive, "symbol": symbol})
    return conditionals


def _section_uses(source: str) -> dict[str, list[str]]:
    lowered = source.lower()
    interface_index = lowered.find("interface")
    implementation_index = lowered.find("implementation")
    if interface_index < 0:
        return {"interface": [], "implementation": _uses(source)}
    interface_source = source[interface_index:implementation_index if implementation_index >= 0 else len(source)]
    implementation_source = source[implementation_index:] if implementation_index >= 0 else ""
    return {
        "interface": _uses(interface_source),
        "implementation": _uses(implementation_source),
    }


def _references(text: str, current_name: str) -> list[str]:
    values = []
    for token in REFERENCE_PATTERN.findall(text):
        normalized = token.strip()
        if not normalized or normalized.lower() in KEYWORDS or normalized == current_name:
            continue
        if normalized not in values:
            values.append(normalized)
    return values[:100]


def _calls(text: str, current_name: str) -> list[str]:
    values = []
    for match in CALL_PATTERN.finditer(text):
        name = str(match.group("name") or "").strip()
        if not name or name.lower() in KEYWORDS or name == current_name:
            continue
        if name not in values:
            values.append(name)
    return values[:100]


def _section_for_offset(source: str, offset: int) -> str:
    prefix = source[:offset].lower()
    interface_index = prefix.rfind("interface")
    implementation_index = prefix.rfind("implementation")
    if implementation_index > interface_index:
        return "implementation"
    if interface_index >= 0:
        return "interface"
    return "project"


def _routine_kind(routine: str) -> str:
    lowered = routine.lower()
    if lowered in {"constructor", "destructor"}:
        return lowered
    return "function" if lowered == "function" else "procedure"


def _type_relationships(type_kind: str, ancestors: str) -> tuple[list[str], list[str]]:
    if type_kind.lower() != "class":
        return [], []
    values = [item.strip() for item in str(ancestors or "").split(",") if item.strip()]
    if not values:
        return [], []
    return values[:1], values[1:]


def _pascal_class_parent(source: str, offset: int, module: str) -> str:
    prior_types = list(TYPE_PATTERN.finditer(source[:offset]))
    if not prior_types:
        return ""
    prior_implementations = [match for match in prior_types if _section_for_offset(source, match.start()) == "implementation"]
    parent_match = (prior_implementations or prior_types)[-1]
    parent = str(parent_match.group("name") or "").strip()
    return f"{module}.{parent}" if parent else ""


def parse_object_pascal_file(file_path: Path) -> ParseOutcome:
    if file_path.suffix.lower() in {".dfm", ".lfm"}:
        return parse_object_pascal_form_file(file_path)
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    module = _module_name(source, file_path)
    uses_by_section = _section_uses(source)
    interface_uses = uses_by_section["interface"]
    implementation_uses = uses_by_section["implementation"]
    imports = []
    for unit in [*interface_uses, *implementation_uses]:
        if unit not in imports:
            imports.append(unit)
    source_associations = _pascal_source_associations(file_path)
    public_dependency_surface = bool(interface_uses)
    include_files = _pascal_includes(source)
    compiler_conditionals = _pascal_conditionals(source)
    conditional_symbols = sorted({item["symbol"] for item in compiler_conditionals})
    symbols: list[SymbolRecord] = []

    unit_match = UNIT_PATTERN.search(source)
    if unit_match:
        declaration = unit_match.group(1).lower()
        symbols.append(
            SymbolRecord(
                name=module,
                qualified_name=module,
                kind=declaration,
                start_line=_line_number_for_offset(source, unit_match.start()),
                end_line=_line_number_for_offset(source, unit_match.end()),
                signature=f"{declaration} {module}",
                metadata={"parser": "object_pascal_regex", "language": "object_pascal", "imports": imports, "interface_uses": interface_uses, "implementation_uses": implementation_uses, "include_files": include_files, "compiler_conditionals": compiler_conditionals, "conditional_symbols": conditional_symbols, "public_dependency_surface": public_dependency_surface, "calls": [], "references": imports, "source_associations": source_associations},
            )
        )

    for match in TYPE_PATTERN.finditer(source):
        name = str(match.group("name") or "").strip()
        type_kind = str(match.group("kind") or "type").lower()
        extends, implements = _type_relationships(type_kind, str(match.group("ancestors") or ""))
        if not name:
            continue
        symbols.append(
            SymbolRecord(
                name=name,
                qualified_name=f"{module}.{name}",
                kind="class" if type_kind == "class" else "type",
                start_line=_line_number_for_offset(source, match.start()),
                end_line=_line_number_for_offset(source, match.end()),
                signature=match.group(0).strip(),
                metadata={"parser": "object_pascal_regex", "language": "object_pascal", "imports": imports, "interface_uses": interface_uses, "implementation_uses": implementation_uses, "include_files": include_files, "compiler_conditionals": compiler_conditionals, "conditional_symbols": conditional_symbols, "public_dependency_surface": public_dependency_surface, "calls": [], "references": _references(match.group(0), name), "extends": extends, "implements": implements, "section": _section_for_offset(source, match.start()), "node_type": type_kind, "source_associations": source_associations},
            )
        )

    for match in PROC_PATTERN.finditer(source):
        raw_name = str(match.group("name") or "").strip()
        if not raw_name:
            continue
        simple_name = raw_name.split(".")[-1]
        parent = raw_name.rsplit(".", 1)[0] if "." in raw_name else ""
        declaration_parent = _pascal_class_parent(source, match.start(), module) if not parent and _section_for_offset(source, match.start()) == "interface" else ""
        qualified_parent = f"{module}.{parent}" if parent else ""
        effective_parent = qualified_parent or declaration_parent
        section = _section_for_offset(source, match.start())
        span_end = source.find(";", match.end())
        preview = source[match.start(): span_end + 1 if span_end >= 0 else match.end()]
        declaration_key = f"{effective_parent}.{simple_name}" if effective_parent else f"{module}.{simple_name}"
        symbols.append(
            SymbolRecord(
                name=simple_name,
                qualified_name=f"{module}.{raw_name}",
                kind=_routine_kind(str(match.group("routine") or "procedure")),
                start_line=_line_number_for_offset(source, match.start()),
                end_line=_line_number_for_offset(source, span_end if span_end >= 0 else match.end()),
                signature=preview.strip(),
                metadata={"parser": "object_pascal_regex", "language": "object_pascal", "imports": imports, "interface_uses": interface_uses, "implementation_uses": implementation_uses, "include_files": include_files, "compiler_conditionals": compiler_conditionals, "conditional_symbols": conditional_symbols, "public_dependency_surface": public_dependency_surface, "calls": _calls(source[match.end():match.end() + 1200], simple_name), "references": _references(preview, simple_name), "section": section, "is_declaration": section == "interface", "is_definition": section == "implementation", "parent": effective_parent, "declaration_key": declaration_key, "source_associations": source_associations},
            )
        )

    for match in PROPERTY_PATTERN.finditer(source):
        name = str(match.group("name") or "").strip()
        if not name:
            continue
        parent_match = list(TYPE_PATTERN.finditer(source[:match.start()]))
        parent = parent_match[-1].group("name") if parent_match else ""
        symbols.append(
            SymbolRecord(
                name=name,
                qualified_name=f"{module}.{name}",
                kind="property",
                start_line=_line_number_for_offset(source, match.start()),
                end_line=_line_number_for_offset(source, match.end()),
                signature=match.group(0).strip(),
                metadata={"parser": "object_pascal_regex", "language": "object_pascal", "imports": imports, "interface_uses": interface_uses, "implementation_uses": implementation_uses, "include_files": include_files, "compiler_conditionals": compiler_conditionals, "conditional_symbols": conditional_symbols, "public_dependency_surface": public_dependency_surface, "calls": [], "references": [], "section": _section_for_offset(source, match.start()), "parent": f"{module}.{parent}" if parent else "", "source_associations": source_associations},
            )
        )

    return ParseOutcome(symbols, {"parser": "object_pascal_regex", "language": "object_pascal", "symbol_count": len(symbols), "imports": imports, "interface_uses": interface_uses, "implementation_uses": implementation_uses, "include_files": include_files, "conditional_symbols": conditional_symbols})


def parse_object_pascal_form_file(file_path: Path) -> ParseOutcome:
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    module = file_path.stem
    source_associations = _pascal_source_associations(file_path)
    symbols: list[SymbolRecord] = []
    event_handlers: list[str] = []
    components: list[dict[str, str]] = []
    component_parent_by_name: dict[str, str] = {}
    component_stack: list[tuple[int, str]] = []
    component_properties: dict[str, list[dict[str, str]]] = {}
    current_component = ""
    lines = source.splitlines()
    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line) + 1
    for line_number, line in enumerate(lines, start=1):
        block_match = FORM_BLOCK_PATTERN.search(line)
        if block_match:
            indent = len(str(block_match.group("indent") or ""))
            while component_stack and component_stack[-1][0] >= indent:
                component_stack.pop()
            name = str(block_match.group("name") or "").strip()
            class_name = str(block_match.group("class") or "").strip()
            keyword = str(block_match.group("keyword") or "").lower()
            parent = component_stack[-1][1] if component_stack else ""
            component_stack.append((indent, name))
            component_parent_by_name[name] = parent
            components.append({"name": name, "class": class_name, "parent": parent, "inherited": str(keyword == "inherited")})
            symbols.append(
                SymbolRecord(
                    name=name,
                    qualified_name=f"{module}.{name}",
                    kind="component",
                    start_line=line_number,
                    end_line=line_number,
                    signature=line.strip(),
                    metadata={
                        "parser": "object_pascal_form_regex",
                        "language": "object_pascal_form",
                        "component_class": class_name,
                        "component_parent": f"{module}.{parent}" if parent else "",
                        "inherited_component": keyword == "inherited",
                        "imports": [],
                        "calls": [],
                        "references": [class_name] if class_name else [],
                        "source_associations": source_associations,
                    },
                )
            )
            current_component = name
            continue
        if line.strip().lower() == "end":
            if component_stack:
                component_stack.pop()
            current_component = component_stack[-1][1] if component_stack else ""
            continue
        property_match = FORM_PROPERTY_PATTERN.search(line)
        if property_match and current_component:
            property_name = str(property_match.group("property") or "").strip()
            value = str(property_match.group("value") or "").strip().strip("'\"")
            component_properties.setdefault(current_component, []).append({"property": property_name, "value": value})
    for symbol in symbols:
        if symbol.kind != "component":
            continue
        properties = component_properties.get(symbol.name, [])
        references = list(symbol.metadata.get("references", []))
        for item in properties:
            value = item.get("value", "")
            if value and value not in references:
                references.append(value)
        symbol.metadata["component_properties"] = properties
        symbol.metadata["references"] = references
    for match in FORM_EVENT_PATTERN.finditer(source):
        event_name = str(match.group("event") or "").strip()
        handler = str(match.group("handler") or "").strip()
        if not event_name or not handler:
            continue
        event_handlers.append(handler)
        line = _line_number_for_offset(source, match.start())
        symbols.append(
            SymbolRecord(
                name=handler,
                qualified_name=f"{module}.{event_name}.{handler}",
                kind="event_handler_binding",
                start_line=line,
                end_line=line,
                signature=match.group(0).strip(),
                metadata={
                    "parser": "object_pascal_form_regex",
                    "language": "object_pascal_form",
                    "event": event_name,
                    "handler": handler,
                    "imports": [],
                    "calls": [handler],
                    "references": [handler],
                    "source_associations": source_associations,
                    "form_components": components,
                },
            )
        )
    if not symbols:
        symbols.append(
            SymbolRecord(
                name=module,
                qualified_name=module,
                kind="form",
                start_line=1,
                end_line=max(1, len(source.splitlines())),
                signature=file_path.name,
                metadata={"parser": "object_pascal_form_regex", "language": "object_pascal_form", "imports": [], "calls": [], "references": [], "source_associations": source_associations},
            )
        )
    return ParseOutcome(
        symbols,
        {
            "parser": "object_pascal_form_regex",
            "language": "object_pascal_form",
            "symbol_count": len(symbols),
            "event_handlers": sorted(set(event_handlers)),
            "component_count": len(components),
        },
    )


def register(registry: ParserRegistry) -> None:
    for extension in (".pas", ".pp", ".dpr", ".dpk", ".lpr", ".dfm", ".lfm"):
        registry.register_extension(extension, parse_object_pascal_file)
