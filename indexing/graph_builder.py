from models.entity_models import FileRecord, SymbolRecord
from storage.kuzu_store import KuzuStore


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


def _symbol_match_key(symbol: SymbolRecord) -> tuple[str, str]:
    qualified = _normalized_signature(symbol.qualified_name)
    signature = _normalized_signature(symbol.signature)
    tail = _qualified_tail(qualified or symbol.name)
    return tail, signature or qualified


def _translation_unit_symbols(symbols_by_file: dict[str, list[SymbolRecord]]) -> dict[str, list[tuple[str, SymbolRecord]]]:
    groups: dict[str, list[tuple[str, SymbolRecord]]] = {}
    for file_path, symbols in symbols_by_file.items():
        for symbol in symbols:
            translation_unit = str(symbol.metadata.get("translation_unit", "")).strip()
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


def _transitive_translation_unit_pairs(grouped_symbols: dict[str, list[tuple[str, SymbolRecord]]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, items in grouped_symbols.items():
        symbols = [symbol for _, symbol in items]
        for source in symbols:
            source_key = _symbol_match_key(source)
            for target in symbols:
                if source.qualified_name == target.qualified_name:
                    continue
                if source_key != _symbol_match_key(target):
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
    symbols_by_name: dict[str, list[tuple[str, str]]],
    file_symbol_names: dict[str, set[str]],
    file_name_candidates: dict[str, list[tuple[str, str]]],
    project_file_symbols: dict[str, str],
    relation: str,
) -> str | None:
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


def build_graph(kuzu_store: KuzuStore, files: list[FileRecord], symbols_by_file: dict[str, list[SymbolRecord]]) -> None:
    symbols_by_name: dict[str, list[tuple[str, str]]] = {}
    file_symbol_names = _file_candidates(symbols_by_file)
    file_name_candidates, project_file_symbols = _normalized_candidates(symbols_by_file)
    grouped_symbols = _translation_unit_symbols(symbols_by_file)
    association_groups = _source_association_groups(symbols_by_file)
    for file_path, symbols in symbols_by_file.items():
        for symbol in symbols:
            symbols_by_name.setdefault(symbol.name, []).append((file_path, symbol.qualified_name))
            symbols_by_name.setdefault(symbol.qualified_name, []).append((file_path, symbol.qualified_name))
            tail = _qualified_tail(symbol.qualified_name)
            if tail:
                symbols_by_name.setdefault(tail, []).append((file_path, symbol.qualified_name))
    for file_record in files:
        kuzu_store.ensure_file(file_record.path)
        for symbol in symbols_by_file.get(file_record.path, []):
            kuzu_store.ensure_symbol(symbol.qualified_name, file_record.path, symbol.kind, symbol.start_line, symbol.end_line)
            kuzu_store.add_edge(file_record.path, "DEFINES", symbol.qualified_name)
    for file_record in files:
        for symbol in symbols_by_file.get(file_record.path, []):
            for relation, metadata_key in (("IMPORTS", "imports"), ("CALLS", "calls"), ("REFERENCES", "references")):
                for raw_target in symbol.metadata.get(metadata_key, []):
                    target = _resolve_symbol_target(
                        raw_target,
                        current_symbol=symbol,
                        file_path=file_record.path,
                        symbols_by_name=symbols_by_name,
                        file_symbol_names=file_symbol_names,
                        file_name_candidates=file_name_candidates,
                        project_file_symbols=project_file_symbols,
                        relation=relation,
                    )
                    if target is None or target == symbol.qualified_name:
                        continue
                    kuzu_store.add_edge(symbol.qualified_name, relation, target)
    for declaration, definition in _declaration_definition_pairs(grouped_symbols):
        kuzu_store.add_edge(declaration, "DECLARES", definition)
    for source_symbol, target_symbol in _associated_symbol_pairs(association_groups):
        kuzu_store.add_edge(source_symbol, "ASSOCIATED_WITH", target_symbol)
    for source_symbol, target_symbol in _transitive_translation_unit_pairs(grouped_symbols):
        kuzu_store.add_edge(source_symbol, "ASSOCIATED_WITH", target_symbol)
