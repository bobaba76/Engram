from collections.abc import Callable

from models.entity_models import FileRecord, SymbolRecord
from storage.kuzu_store import KuzuStore

# Edge confidence taxonomy. EXTRACTED edges are parsed directly from source
# by tree-sitter (call sites, import statements, include directives, field
# reads). INFERRED edges are derived by heuristics — name-based resolution
# across files, DI registration matching, header/implementation pairing,
# transitive translation-unit associations — so consumers can weight them
# lower when reasoning about blast radius or rename safety.
EXTRACTED_RELATIONS = frozenset({
    "DEFINES",
    "CALLS",
    "IMPORTS",
    "INCLUDES",
    "REFERENCES",
    "ACCESSES",
    "FETCHES",
    "READS_FIELD",
    "EXTENDS",
    "IMPLEMENTS",
    "HAS_METHOD",
    "HAS_PROPERTY",
    "DECLARES",
})
INFERRED_RELATIONS = frozenset({
    "INJECTS",
    "USES_SERVICE",
    "METHOD_OVERRIDES",
    "METHOD_IMPLEMENTS",
    "ASSOCIATED_WITH",
    "DECLARES_IN_HEADER",
    "DEFINES_IMPLEMENTATION",
    "HAS_COMPONENT",
    "OWNS",
})
def _confidence_for_relation(relation: str) -> str:
    if relation in INFERRED_RELATIONS:
        return "INFERRED"
    if relation in EXTRACTED_RELATIONS:
        return "EXTRACTED"
    return "AMBIGUOUS"

NOISY_REFERENCE_TOKENS = {
    "a",
    "args",
    "branch",
    "children",
    "className",
    "color",
    "data",
    "e",
    "error",
    "event",
    "html",
    "i",
    "id",
    "index",
    "item",
    "items",
    "key",
    "margin",
    "name",
    "result",
    "results",
    "row",
    "selected",
    "start",
    "text",
    "theme",
    "type",
    "value",
    "values",
    "views",
}

# Python builtins that commonly collide with repo symbols. A bare unqualified
# call (sum(), len(), max()...) inside a .py file must NEVER resolve to a
# same-named symbol from another file or language — the resolver has no other
# way to know the call is a language builtin.
PYTHON_BUILTINS = frozenset({
    "abs", "all", "any", "bin", "bool", "bytes", "callable", "chr", "classmethod",
    "compile", "complex", "delattr", "dict", "dir", "divmod", "enumerate", "eval",
    "exec", "filter", "float", "format", "frozenset", "getattr", "globals", "hasattr",
    "hash", "help", "hex", "id", "input", "int", "isinstance", "issubclass", "iter",
    "len", "list", "locals", "map", "max", "memoryview", "min", "next", "object",
    "oct", "open", "ord", "pow", "print", "property", "range", "repr", "reversed",
    "round", "set", "setattr", "slice", "sorted", "staticmethod", "str", "sum",
    "super", "tuple", "type", "vars", "zip",
})

def _file_candidates(symbols_by_file: dict[str, list[SymbolRecord]]) -> dict[str, set[str]]:
    return {
        file_path: {symbol.name for symbol in symbols} | {symbol.qualified_name for symbol in symbols}
        for file_path, symbols in symbols_by_file.items()
    }

def _normalized_candidates(symbols_by_file: dict[str, list[SymbolRecord]]) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
    by_basename: dict[str, list[tuple[str, str]]] = {}
    project_files: dict[str, str] = {}
    for file_path, symbols in symbols_by_file.items():
        basename = file_path.split("/")[-1]
        stem = basename.rsplit(".", 1)[0] if "." in basename else basename
        representative = symbols[0].qualified_name if symbols else file_path
        by_basename.setdefault(basename, []).append((file_path, representative))
        by_basename.setdefault(stem, []).append((file_path, representative))
        for symbol in symbols:
            if symbol.kind in {"project", "solution"}:
                project_files[basename] = symbol.qualified_name
                project_files[stem] = symbol.qualified_name
    return by_basename, project_files

def _is_noise_reference(raw_target: str) -> bool:
    token = str(raw_target or "").strip()
    if not token:
        return True
    if token in NOISY_REFERENCE_TOKENS:
        return True
    if len(token) <= 2 and token.islower():
        return True
    return False

def _qualified_tail(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if "." in token:
        token = token.split(".")[-1]
    if "::" in token:
        token = token.split("::")[-1]
    return token

def _normalized_signature(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    token = token.replace("::", ".")
    token = " ".join(token.split())
    return token

def _normalize_file_reference(value: str) -> str:
    token = str(value or "").strip().strip("'\"")
    if not token:
        return ""
    token = token.replace("\\", "/")
    while token.startswith("./"):
        token = token[2:]
    return token

def _project_reference_targets(raw_reference: str, symbols_by_file: dict[str, list[SymbolRecord]]) -> list[str]:
    reference = _normalize_file_reference(raw_reference)
    if not reference:
        return []
    basename = reference.split("/")[-1]
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    matches: list[str] = []
    for file_path, symbols in symbols_by_file.items():
        normalized_path = _normalize_file_reference(file_path)
        normalized_basename = normalized_path.split("/")[-1]
        normalized_stem = normalized_basename.rsplit(".", 1)[0] if "." in normalized_basename else normalized_basename
        if normalized_path == reference or normalized_path.endswith(f"/{reference}") or normalized_basename == basename or normalized_stem == stem:
            matches.extend(symbol.qualified_name for symbol in symbols)
    return matches

def _symbol_match_key(symbol: SymbolRecord) -> tuple[str, str]:
    declaration_key = _normalized_signature(str(symbol.metadata.get("declaration_key", "") or ""))
    if declaration_key:
        return _qualified_tail(declaration_key), declaration_key
    qualified = _normalized_signature(symbol.qualified_name)
    signature = _normalized_signature(symbol.signature)
    tail = _qualified_tail(qualified or symbol.name)
    return tail, signature or qualified

def _translation_unit_symbols(symbols_by_file: dict[str, list[SymbolRecord]]) -> dict[str, list[tuple[str, SymbolRecord]]]:
    groups: dict[str, list[tuple[str, SymbolRecord]]] = {}
    for file_path, symbols in symbols_by_file.items():
        for symbol in symbols:
            translation_unit = str(symbol.metadata.get("translation_unit", "")).strip()
            if not translation_unit and str(symbol.metadata.get("language", "")).lower() == "object_pascal":
                translation_unit = file_path
            if translation_unit:
                groups.setdefault(translation_unit, []).append((file_path, symbol))
    return groups

def _source_association_groups(symbols_by_file: dict[str, list[SymbolRecord]]) -> dict[str, list[tuple[str, SymbolRecord]]]:
    groups: dict[str, list[tuple[str, SymbolRecord]]] = {}
    for file_path, symbols in symbols_by_file.items():
        for symbol in symbols:
            groups.setdefault(file_path, []).append((file_path, symbol))
            for candidate in symbol.metadata.get("source_associations", []):
                groups.setdefault(str(candidate), []).append((file_path, symbol))
    return groups

def _file_association_map(symbols_by_file: dict[str, list[SymbolRecord]]) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {file_path: set() for file_path in symbols_by_file}
    for file_path, symbols in symbols_by_file.items():
        for symbol in symbols:
            for candidate in symbol.metadata.get("source_associations", []):
                candidate_text = str(candidate or "").strip()
                if candidate_text:
                    adjacency.setdefault(file_path, set()).add(candidate_text)
    expanded: dict[str, set[str]] = {}
    for file_path in adjacency:
        visited: set[str] = set()
        stack = list(adjacency.get(file_path, set()))
        while stack:
            candidate = stack.pop()
            if candidate in visited:
                continue
            visited.add(candidate)
            stack.extend(adjacency.get(candidate, set()) - visited)
        expanded[file_path] = visited
    return expanded

def _associated_special_target(
    raw_target: str,
    current_symbol: SymbolRecord,
    file_path: str,
    relation: str,
    symbols_by_file: dict[str, list[SymbolRecord]],
    file_associations: dict[str, set[str]],
) -> str | None:
    if relation not in {"IMPORTS", "CALLS", "REFERENCES"}:
        return None
    associated_files = file_associations.get(file_path, set())
    if not associated_files:
        return None
    if str(current_symbol.metadata.get("language", "")).lower() == "object_pascal_form" and relation in {"CALLS", "REFERENCES"}:
        matches = [
            symbol.qualified_name
            for associated_file in associated_files
            for symbol in symbols_by_file.get(associated_file, [])
            if symbol.name == raw_target and symbol.kind in {"procedure", "function", "constructor", "destructor", "method"}
        ]
        if len(set(matches)) == 1:
            return matches[0]
    namespace_aliases = current_symbol.metadata.get("import_aliases", {})
    if isinstance(namespace_aliases, dict) and "." in raw_target:
        namespace_name, member_name = raw_target.split(".", 1)
        if str(namespace_aliases.get(namespace_name, "") or "").strip() == "__namespace__":
            matches = [
                symbol.qualified_name
                for associated_file in associated_files
                for symbol in symbols_by_file.get(associated_file, [])
                if symbol.name == member_name and (bool(symbol.metadata.get("exported")) or bool(symbol.metadata.get("default_export")))
            ]
            return matches[0] if len(set(matches)) == 1 else None
    if raw_target == "default":
        matches = [
            symbol.qualified_name
            for associated_file in associated_files
            for symbol in symbols_by_file.get(associated_file, [])
            if bool(symbol.metadata.get("default_export"))
        ]
        return matches[0] if len(set(matches)) == 1 else None
    if raw_target == "__namespace__":
        matches = [
            symbol.qualified_name
            for associated_file in associated_files
            for symbol in symbols_by_file.get(associated_file, [])
            if symbol.kind == "module" and symbol.name == "exports"
        ]
        return matches[0] if len(set(matches)) == 1 else None
    return None

def _declaration_definition_pairs(grouped_symbols: dict[str, list[tuple[str, SymbolRecord]]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, items in grouped_symbols.items():
        declarations = [symbol for _, symbol in items if symbol.metadata.get("is_declaration")]
        definitions = [symbol for _, symbol in items if symbol.metadata.get("is_definition")]
        for declaration in declarations:
            decl_key = _symbol_match_key(declaration)
            matches = [definition for definition in definitions if _symbol_match_key(definition) == decl_key or definition.name == declaration.name]
            if len(matches) == 1:
                pair = (declaration.qualified_name, matches[0].qualified_name)
                if pair in seen:
                    continue
                seen.add(pair)
                pairs.append(pair)
    return pairs

def _associated_symbol_pairs(grouped_symbols: dict[str, list[tuple[str, SymbolRecord]]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, items in grouped_symbols.items():
        headers = [symbol for file_path, symbol in items if str(symbol.metadata.get("file_role", "")) == "header"]
        sources = [symbol for file_path, symbol in items if str(symbol.metadata.get("file_role", "")) == "source"]
        for header in headers:
            for source in sources:
                if _symbol_match_key(header) != _symbol_match_key(source) and header.name != source.name:
                    continue
                pair = (header.qualified_name, source.qualified_name)
                if pair in seen:
                    continue
                seen.add(pair)
                pairs.append(pair)
    return pairs

def _header_implementation_pairs(grouped_symbols: dict[str, list[tuple[str, SymbolRecord]]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, items in grouped_symbols.items():
        headers = [
            symbol
            for _, symbol in items
            if str(symbol.metadata.get("file_role", "")) == "header"
            and symbol.kind in {"function", "method", "typedef", "type", "class", "macro"}
        ]
        implementations = [
            symbol
            for _, symbol in items
            if str(symbol.metadata.get("file_role", "")) == "source"
            and bool(symbol.metadata.get("is_definition"))
        ]
        for header in headers:
            header_key = _symbol_match_key(header)
            matches = [
                implementation
                for implementation in implementations
                if _symbol_match_key(implementation) == header_key or implementation.name == header.name
            ]
            if len(matches) != 1:
                continue
            pair = (header.qualified_name, matches[0].qualified_name)
            if pair in seen:
                continue
            seen.add(pair)
            pairs.append(pair)
    return pairs

def _transitive_translation_unit_pairs(grouped_symbols: dict[str, list[tuple[str, SymbolRecord]]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, items in grouped_symbols.items():
        # Group symbols by match key in one O(n) pass, then generate
        # pairs within each key group. The previous implementation was
        # O(n²) per translation unit — for a group of 50k symbols that
        # meant 2.5B comparisons, each involving string normalization.
        # Key groups are typically 2-3 symbols (same symbol declared in
        # a header and defined in a source), so the pairwise phase is
        # trivially small.
        by_key: dict[tuple[str, str], list[SymbolRecord]] = {}
        for _, symbol in items:
            by_key.setdefault(_symbol_match_key(symbol), []).append(symbol)
        for symbols in by_key.values():
            for source in symbols:
                for target in symbols:
                    if source.qualified_name == target.qualified_name:
                        continue
                    pair = (source.qualified_name, target.qualified_name)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    pairs.append(pair)
    return pairs

def _resolve_symbol_target(
    raw_target: str,
    current_symbol: SymbolRecord,
    file_path: str,
    symbols_by_file: dict[str, list[SymbolRecord]],
    symbols_by_name: dict[str, list[tuple[str, str]]],
    file_symbol_names: dict[str, set[str]],
    file_name_candidates: dict[str, list[tuple[str, str]]],
    project_file_symbols: dict[str, str],
    file_associations: dict[str, set[str]],
    relation: str,
) -> str | None:
    import_aliases = current_symbol.metadata.get("import_aliases", {})
    if isinstance(import_aliases, dict):
        alias_target = str(import_aliases.get(raw_target, "") or "").strip()
        if alias_target and alias_target != raw_target:
            raw_target = alias_target
    if (
        relation == "CALLS"
        and file_path.lower().endswith(".py")
        and raw_target in PYTHON_BUILTINS
        and raw_target not in file_symbol_names.get(file_path, set())
    ):
        # Unqualified call to a Python builtin (sum(), len(), ...). Same-file
        # definitions/imports shadow builtins and are handled above (aliases)
        # or here (local names); anything else is a language builtin and must
        # not resolve to a same-named repo symbol from another file/language.
        return None
    special_target = _associated_special_target(raw_target, current_symbol, file_path, relation, symbols_by_file, file_associations)
    if special_target is not None:
        return None if special_target == current_symbol.qualified_name else special_target
    candidates = symbols_by_name.get(raw_target, [])
    if not candidates and relation == "IMPORTS":
        candidates = file_name_candidates.get(raw_target, [])
        if not candidates and "/" in raw_target:
            candidates = file_name_candidates.get(raw_target.split("/")[-1], [])
    if not candidates:
        tail = _qualified_tail(raw_target)
        if tail and tail != raw_target:
            candidates = symbols_by_name.get(tail, [])
    if not candidates and relation == "IMPORTS":
        project_target = project_file_symbols.get(raw_target) or project_file_symbols.get(_qualified_tail(raw_target))
        if project_target:
            return project_target
    if not candidates:
        return None
    associated_files = file_associations.get(file_path, set())
    if associated_files:
        associated_candidates = [qualified_name for candidate_file, qualified_name in candidates if candidate_file in associated_files]
        if len(set(associated_candidates)) == 1:
            only = associated_candidates[0]
            return None if only == current_symbol.qualified_name else only
    same_file = [qualified_name for candidate_file, qualified_name in candidates if candidate_file == file_path]
    if same_file:
        return same_file[0]
    if relation == "REFERENCES" and _is_noise_reference(raw_target):
        return None
    unique_candidates = {qualified_name for _, qualified_name in candidates}
    if len(unique_candidates) == 1:
        only = next(iter(unique_candidates))
        return None if only == current_symbol.qualified_name else only
    local_names = file_symbol_names.get(file_path, set())
    if raw_target in local_names:
        return None
    if relation == "REFERENCES":
        tail = _qualified_tail(raw_target)
        if tail and tail != raw_target:
            narrowed = [qualified_name for _, qualified_name in candidates if qualified_name.split(".")[-1] == tail]
            if len(set(narrowed)) == 1:
                return narrowed[0]
        return None
    if relation == "IMPORTS":
        import_like = [qualified_name for _, qualified_name in candidates if qualified_name.split(".")[-1] in {raw_target, _qualified_tail(raw_target)}]
        if len(import_like) == 1:
            return import_like[0]
        if raw_target in project_file_symbols:
            return project_file_symbols[raw_target]
    if relation == "CALLS":
        tail = _qualified_tail(raw_target)
        call_like = [qualified_name for _, qualified_name in candidates if qualified_name.split(".")[-1] == tail]
        if len(set(call_like)) == 1:
            return call_like[0]
    return None

def _should_log_index(index: int, total: int) -> bool:
    if total <= 10:
        return True
    interval = max(total // 10, 1)
    return index == 1 or index == total or index % interval == 0

def _property_symbol_name(access_path: str) -> str:
    return f"property:{str(access_path or '').strip()}"

def _route_symbol_name(route: str) -> str:
    route_text = "/" + str(route or "").strip().strip("/")
    return f"route:{route_text.rstrip('/') or '/'}"

def _field_symbol_name(field_path: str) -> str:
    return f"field:{str(field_path or '').strip()}"

def _parent_symbol_name(symbol: SymbolRecord) -> str:
    parent = str(symbol.metadata.get("parent", "") or "").strip()
    if parent:
        return parent
    parent_chain = symbol.metadata.get("parent_chain", [])
    if isinstance(parent_chain, list) and parent_chain:
        return ".".join(str(item) for item in parent_chain if str(item))
    return ""

def _method_index(symbols_by_file: dict[str, list[SymbolRecord]]) -> dict[tuple[str, str], list[str]]:
    methods: dict[tuple[str, str], list[str]] = {}
    for symbols in symbols_by_file.values():
        for symbol in symbols:
            parent = _parent_symbol_name(symbol)
            if parent:
                methods.setdefault((parent, symbol.name), []).append(symbol.qualified_name)
    return methods

def _parent_symbol(symbols: list[SymbolRecord], symbol: SymbolRecord) -> SymbolRecord | None:
    parent = _parent_symbol_name(symbol)
    if not parent:
        return None
    for candidate in symbols:
        if candidate.qualified_name == parent or candidate.name == parent.rsplit(".", 1)[-1]:
            return candidate
    return None

def _member_ownership_relation(symbol: SymbolRecord) -> str:
    if symbol.kind in {"method", "function", "procedure", "constructor", "destructor"}:
        return "HAS_METHOD"
    if symbol.kind in {"field", "property"}:
        return "HAS_PROPERTY"
    return ""

def build_graph(
    kuzu_store: KuzuStore,
    files: list[FileRecord],
    symbols_by_file: dict[str, list[SymbolRecord]],
    progress_callback: Callable[[str], None] | None = None,
) -> None:
    symbols_by_name: dict[str, list[tuple[str, str]]] = {}
    file_symbol_names = _file_candidates(symbols_by_file)
    file_name_candidates, project_file_symbols = _normalized_candidates(symbols_by_file)
    file_associations = _file_association_map(symbols_by_file)
    grouped_symbols = _translation_unit_symbols(symbols_by_file)
    association_groups = _source_association_groups(symbols_by_file)
    methods_by_parent_and_name = _method_index(symbols_by_file)
    inheritance_edges: list[tuple[str, str, str]] = []
    for file_path, symbols in symbols_by_file.items():
        for symbol in symbols:
            symbols_by_name.setdefault(symbol.name, []).append((file_path, symbol.qualified_name))
            symbols_by_name.setdefault(symbol.qualified_name, []).append((file_path, symbol.qualified_name))
            tail = _qualified_tail(symbol.qualified_name)
            if tail:
                symbols_by_name.setdefault(tail, []).append((file_path, symbol.qualified_name))

    # ------------------------------------------------------------------
        # Bulk-collect phase. Nodes and edges are accumulated in memory and
        # flushed with a handful of UNWIND statements instead of one kuzu
        # query per node/edge (~11x on edges). Duplicates are collapsed here:
        # first (source, target) wins, matching the old per-edge CREATE +
        # duplicate-skip behaviour. See KuzuStore.bulk_* for the flush side.
        # ------------------------------------------------------------------
        file_nodes: list[str] = []
        symbol_nodes: dict[str, dict] = {}
        edge_buckets: dict[str, dict[tuple[str, str], str]] = {}
        def _edge(relation: str, source: str, target: str, confidence: str) -> None:
            edge_buckets.setdefault(relation, {}).setdefault((source, target), confidence)
        def _symbol_node(qualified_name: str, file_path: str, kind: str, start_line: int, end_line: int) -> None:
            symbol_nodes.setdefault(
                qualified_name,
                {
                    "qualified_name": qualified_name,
                    "file_path": file_path,
                    "kind": kind,
                    "start_line": start_line,
                    "end_line": end_line,
                },
            )
        for index, file_record in enumerate(files, start=1):
            file_nodes.append(file_record.path)
            for symbol in symbols_by_file.get(file_record.path, []):
                _symbol_node(symbol.qualified_name, file_record.path, symbol.kind, symbol.start_line, symbol.end_line)
                _edge("DEFINES", file_record.path, symbol.qualified_name, "EXTRACTED")
            if progress_callback is not None and _should_log_index(index, len(files)):
                progress_callback(f"graph node progress: {index}/{len(files)} files ({file_record.path})")

    for index, file_record in enumerate(files, start=1):
        for symbol in symbols_by_file.get(file_record.path, []):
            for relation, metadata_key in (("IMPORTS", "imports"), ("CALLS", "calls"), ("REFERENCES", "references")):
                for raw_target in symbol.metadata.get(metadata_key, []):
                    target = _resolve_symbol_target(
                        raw_target,
                        current_symbol=symbol,
                        file_path=file_record.path,
                        symbols_by_file=symbols_by_file,
                        symbols_by_name=symbols_by_name,
                        file_symbol_names=file_symbol_names,
                        file_name_candidates=file_name_candidates,
                        project_file_symbols=project_file_symbols,
                        file_associations=file_associations,
                        relation=relation,
                    )
                    if target is None or target == symbol.qualified_name:
                        continue

                    _edge(relation, symbol.qualified_name, target, "EXTRACTED")

                    if relation == "IMPORTS" and str(symbol.metadata.get("language", "")).lower() in {"c", "cpp"}:

                        _edge("INCLUDES", symbol.qualified_name, target, "EXTRACTED")

            for raw_reference in symbol.metadata.get("project_references", []):
                for target in _project_reference_targets(str(raw_reference), symbols_by_file):
                    if target == symbol.qualified_name:
                        continue

                    _edge("REFERENCES", symbol.qualified_name, target, "EXTRACTED")

                    if str(symbol.metadata.get("language", "")).lower().startswith("object_pascal"):

                        _edge("OWNS", symbol.qualified_name, target, "INFERRED")

            for raw_include in symbol.metadata.get("include_files", []):
                for target in _project_reference_targets(str(raw_include), symbols_by_file):
                    if target == symbol.qualified_name:
                        continue

                    _edge("INCLUDES", symbol.qualified_name, target, "EXTRACTED")
                    _edge("REFERENCES", symbol.qualified_name, target, "EXTRACTED")

            parent = _parent_symbol(symbols_by_file.get(file_record.path, []), symbol)
            member_relation = _member_ownership_relation(symbol)
            if parent is not None and member_relation:

                _edge(member_relation, parent.qualified_name, symbol.qualified_name, "EXTRACTED")

            component_parent = str(symbol.metadata.get("component_parent", "") or "").strip()
            if component_parent:
                target = _resolve_symbol_target(
                    component_parent,
                    current_symbol=symbol,
                    file_path=file_record.path,
                    symbols_by_file=symbols_by_file,
                    symbols_by_name=symbols_by_name,
                    file_symbol_names=file_symbol_names,
                    file_name_candidates=file_name_candidates,
                    project_file_symbols=project_file_symbols,
                    file_associations=file_associations,
                    relation="REFERENCES",
                )
                if target and target != symbol.qualified_name:

                    _edge("HAS_COMPONENT", target, symbol.qualified_name, "INFERRED")

            for raw_access in symbol.metadata.get("accesses", []):
                access_path = str(raw_access or "").strip()
                if not access_path or "." not in access_path:
                    continue
                target = _property_symbol_name(access_path)

                _symbol_node(target, file_record.path, "property", symbol.start_line, symbol.end_line)
                _edge("ACCESSES", symbol.qualified_name, target, "EXTRACTED")

            for raw_route in symbol.metadata.get("fetches", []):
                route = str(raw_route or "").strip()
                if not route:
                    continue
                target = _route_symbol_name(route)

                _symbol_node(target, file_record.path, "api_route", symbol.start_line, symbol.end_line)
                _edge("FETCHES", symbol.qualified_name, target, "EXTRACTED")

            for raw_field in symbol.metadata.get("field_reads", []):
                field_path = str(raw_field or "").strip()
                if not field_path:
                    continue
                target = _field_symbol_name(field_path)

                _symbol_node(target, file_record.path, "field", symbol.start_line, symbol.end_line)
                _edge("READS_FIELD", symbol.qualified_name, target, "EXTRACTED")

            for relation, metadata_key in (("EXTENDS", "extends"), ("IMPLEMENTS", "implements")):
                for raw_target in symbol.metadata.get(metadata_key, []):
                    target = _resolve_symbol_target(
                        str(raw_target),
                        current_symbol=symbol,
                        file_path=file_record.path,
                        symbols_by_file=symbols_by_file,
                        symbols_by_name=symbols_by_name,
                        file_symbol_names=file_symbol_names,
                        file_name_candidates=file_name_candidates,
                        project_file_symbols=project_file_symbols,
                        file_associations=file_associations,
                        relation=relation,
                    )
                    if target is None or target == symbol.qualified_name:
                        continue

                    _edge(relation, symbol.qualified_name, target, "EXTRACTED")

                    inheritance_edges.append((symbol.qualified_name, relation, target))
            for registration in symbol.metadata.get("di_registrations", []):
                if not isinstance(registration, dict):
                    continue
                service = str(registration.get("service", "") or "")
                implementation = str(registration.get("implementation", "") or "")
                service_target = _resolve_symbol_target(
                    service,
                    current_symbol=symbol,
                    file_path=file_record.path,
                    symbols_by_file=symbols_by_file,
                    symbols_by_name=symbols_by_name,
                    file_symbol_names=file_symbol_names,
                    file_name_candidates=file_name_candidates,
                    project_file_symbols=project_file_symbols,
                    file_associations=file_associations,
                    relation="REFERENCES",
                )
                implementation_target = _resolve_symbol_target(
                    implementation,
                    current_symbol=symbol,
                    file_path=file_record.path,
                    symbols_by_file=symbols_by_file,
                    symbols_by_name=symbols_by_name,
                    file_symbol_names=file_symbol_names,
                    file_name_candidates=file_name_candidates,
                    project_file_symbols=project_file_symbols,
                    file_associations=file_associations,
                    relation="REFERENCES",
                )
                if service_target and implementation_target and service_target != implementation_target:

                    _edge("INJECTS", service_target, implementation_target, "INFERRED")

            dependency_sources = list(symbol.metadata.get("constructor_dependencies", []) if isinstance(symbol.metadata.get("constructor_dependencies", []), list) else [])
            if not dependency_sources:
                parent_symbol = _parent_symbol(symbols_by_file.get(file_record.path, []), symbol)
                if parent_symbol is not None:
                    dependency_sources = list(parent_symbol.metadata.get("constructor_dependencies", []) if isinstance(parent_symbol.metadata.get("constructor_dependencies", []), list) else [])
            for dependency in dependency_sources:
                service_target = _resolve_symbol_target(
                    str(dependency),
                    current_symbol=symbol,
                    file_path=file_record.path,
                    symbols_by_file=symbols_by_file,
                    symbols_by_name=symbols_by_name,
                    file_symbol_names=file_symbol_names,
                    file_name_candidates=file_name_candidates,
                    project_file_symbols=project_file_symbols,
                    file_associations=file_associations,
                    relation="REFERENCES",
                )
                if service_target and service_target != symbol.qualified_name:

                    _edge("USES_SERVICE", symbol.qualified_name, service_target, "INFERRED")

        if progress_callback is not None and _should_log_index(index, len(files)):
            progress_callback(f"graph edge progress: {index}/{len(files)} files ({file_record.path})")
    for child, relation, parent in inheritance_edges:
        method_relation = "METHOD_IMPLEMENTS" if relation == "IMPLEMENTS" else "METHOD_OVERRIDES"
        for (parent_symbol, method_name), parent_methods in methods_by_parent_and_name.items():
            if parent_symbol != parent:
                continue
            for child_method in methods_by_parent_and_name.get((child, method_name), []):
                for parent_method in parent_methods:

                    _edge(method_relation, child_method, parent_method, "INFERRED")

    if progress_callback is not None:
        progress_callback("graph association edges started")
    for declaration, definition in _declaration_definition_pairs(grouped_symbols):

        _edge("DECLARES", declaration, definition, "EXTRACTED")

    if progress_callback is not None:
        progress_callback("graph association edges: declaration-definition pairs done")

    for header_symbol, implementation_symbol in _header_implementation_pairs(association_groups):

        _edge("DECLARES_IN_HEADER", header_symbol, implementation_symbol, "INFERRED")
        _edge("DEFINES_IMPLEMENTATION", implementation_symbol, header_symbol, "INFERRED")

    if progress_callback is not None:
        progress_callback("graph association edges: header-implementation pairs done")

    for source_symbol, target_symbol in _associated_symbol_pairs(association_groups):

        _edge("ASSOCIATED_WITH", source_symbol, target_symbol, "INFERRED")

    if progress_callback is not None:
        progress_callback("graph association edges: associated symbol pairs done")

    for source_symbol, target_symbol in _transitive_translation_unit_pairs(grouped_symbols):

        _edge("ASSOCIATED_WITH", source_symbol, target_symbol, "INFERRED")

    if progress_callback is not None:
        progress_callback(f"graph association edges done: {sum(len(b) for b in edge_buckets.values())} edges collected")
    # ------------------------------------------------------------------
    # Flush phase: all nodes first (edges MATCH them), then one UNWIND
    # batch per relation. Kuzu does not enforce the rel PK for UNWIND
    # CREATE, so duplicates were already collapsed during collection.
    # ------------------------------------------------------------------
    if progress_callback is not None:
        progress_callback(f"graph flush: {len(file_nodes)} file nodes, {len(symbol_nodes)} symbol nodes")
    kuzu_store.bulk_ensure_nodes(file_nodes, list(symbol_nodes.values()))
    if progress_callback is not None:
        progress_callback("graph flush: nodes inserted, flushing edges")
    total_edges = sum(len(b) for b in edge_buckets.values())
    flushed_edges = 0
    for relation, bucket in edge_buckets.items():
        edge_list = [(source, target, confidence) for (source, target), confidence in bucket.items()]
        if progress_callback is not None:
            progress_callback(f"graph flush: {relation} — {len(edge_list)} edges ({flushed_edges}/{total_edges} total)")
        kuzu_store.bulk_add_edges(relation, edge_list)
        flushed_edges += len(edge_list)
    if progress_callback is not None:
        progress_callback("graph flush complete")
