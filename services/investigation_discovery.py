"""Discovery — cheap symbol discovery, alternate anchors, broad lexical search terms."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from services.investigation_constants import GENERIC_SEARCH_TERMS, STOPWORD_TOKENS

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore


def _alternate_seed_targets(seed_target: str, query_rewrite: dict[str, object], limit: int = 4) -> list[str]:
    candidates: list[str] = []
    for field in ("symbol_terms", "route_terms", "file_terms", "search_seeds", "rewritten_queries"):
        values = query_rewrite.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            candidate = str(value or "").strip()
            if not candidate or candidate == seed_target or candidate in candidates:
                continue
            candidates.append(candidate)
            if len(candidates) >= limit:
                return candidates
    return candidates

def should_allow_broad_vector_fallback(search_task: str, query_rewrite: dict[str, object]) -> bool:
    candidate = str(search_task or "").strip()
    if not candidate:
        return False
    route_terms = query_rewrite.get("route_terms", [])
    file_terms = query_rewrite.get("file_terms", [])
    if isinstance(route_terms, list) and candidate in route_terms:
        return True
    if isinstance(file_terms, list) and candidate in file_terms:
        return True
    if "/" in candidate or candidate.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        return True
    if "." in candidate or ":" in candidate:
        return True
    if re.search(r"[a-z][A-Z]", candidate):
        lowered = candidate.lower()
        if lowered in GENERIC_SEARCH_TERMS:
            return False
        parts = [part for part in re.split(r"[^a-zA-Z0-9]+", candidate) if part]
        if len(parts) == 1 and len(candidate) >= 14:
            return True
        if len(parts) >= 2:
            return True
    lowered_tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", candidate.lower()) if token]
    if not lowered_tokens:
        return False
    if all(token in GENERIC_SEARCH_TERMS or token in STOPWORD_TOKENS for token in lowered_tokens):
        return False
    return False

def broad_lexical_search_terms(search_task: str, query_rewrite: dict[str, object], limit: int = 4) -> list[str]:
    terms: list[str] = []

    def token_key(value: str) -> tuple[str, ...]:
        return tuple(token for token in re.split(r"[^a-zA-Z0-9]+", value.lower()) if token)

    def add_term(value: object) -> None:
        candidate = str(value or "").strip()
        if not candidate or candidate in terms:
            return
        lowered_tokens = list(token_key(candidate))
        if lowered_tokens and all(token in GENERIC_SEARCH_TERMS or token in STOPWORD_TOKENS for token in lowered_tokens):
            return
        terms.append(candidate)

    add_term(search_task)
    for field in ("route_terms", "file_terms", "symbol_terms", "search_seeds"):
        values = query_rewrite.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            candidate = str(value or "").strip()
            if not candidate or " " in candidate:
                continue
            if field in {"route_terms", "file_terms"}:
                add_term(candidate)
            elif should_allow_broad_vector_fallback(candidate, query_rewrite):
                add_term(candidate)
            if len(terms) >= limit:
                return terms[:limit]
    if len(terms) < limit:
        for value in list(terms):
            split_variant = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value).strip()
            if split_variant and split_variant != value:
                add_term(split_variant)
            compact_variant = "".join(token_key(value))
            if compact_variant and compact_variant != value.lower():
                add_term(compact_variant)
            if len(terms) >= limit:
                return terms[:limit]
    if len(terms) < limit:
        core_terms = query_rewrite.get("core_terms", [])
        if isinstance(core_terms, list):
            focused_terms = [term for term in core_terms if term not in GENERIC_SEARCH_TERMS and term not in STOPWORD_TOKENS]
            if len(focused_terms) >= 2:
                add_term(" ".join(focused_terms[:2]))
            elif focused_terms:
                add_term(focused_terms[0])
    return terms[:limit]

def cheap_symbol_discovery_terms(search_task: str, query_rewrite: dict[str, object], limit: int = 4) -> list[str]:
    terms = broad_lexical_search_terms(search_task, query_rewrite, limit=limit)
    for value in list(terms):
        split_variant = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value).strip()
        if split_variant and split_variant not in terms:
            terms.append(split_variant)
        if len(terms) >= limit:
            return terms[:limit]
    return terms[:limit]

def alternate_discovery_anchors(
    search_task: str,
    query_rewrite: dict[str, object],
    app_target: str = "",
    limit: int = 2,
) -> list[str]:
    anchors: list[str] = []
    normalized_seed = str(search_task or "").strip().lower()

    def add_anchor(value: object) -> None:
        candidate = str(value or "").strip()
        if not candidate:
            return
        normalized = candidate.lower()
        if normalized == normalized_seed or candidate in anchors:
            return
        tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", normalized) if token]
        if tokens and all(token in GENERIC_SEARCH_TERMS or token in STOPWORD_TOKENS for token in tokens):
            return
        if " " in candidate and not any(marker in candidate for marker in ("/", ".", ":")):
            return
        if not (
            should_allow_broad_vector_fallback(candidate, query_rewrite)
            or "/" in candidate
            or "." in candidate
            or ":" in candidate
            or re.search(r"[a-z][A-Z]", candidate)
            or len(candidate) >= 8
        ):
            return
        anchors.append(candidate)

    for value in [app_target]:
        add_anchor(value)
    for field in ("route_terms", "file_terms", "symbol_terms", "search_seeds"):
        values = query_rewrite.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            add_anchor(value)
            if len(anchors) >= limit:
                return anchors[:limit]
    core_terms = query_rewrite.get("core_terms", [])
    if isinstance(core_terms, list):
        for value in core_terms:
            add_anchor(value)
            if len(anchors) >= limit:
                return anchors[:limit]
    return anchors[:limit]

def cheap_symbol_discovery(
    duckdb_store: DuckDBStore,
    search_task: str,
    query_rewrite: dict[str, object],
    limit: int = 5,
) -> list[dict[str, object]]:
    fetch_symbols = getattr(duckdb_store, "fetch_symbols_for_target", None)
    if not callable(fetch_symbols):
        return []
    matches: list[dict[str, object]] = []
    seen: set[tuple[str, str, object, object]] = set()
    for term in cheap_symbol_discovery_terms(search_task, query_rewrite, limit=max(limit, 4)):
        for symbol in fetch_symbols(term, limit=max(limit * 3, 12)):
            key = (
                str(symbol.get("qualified_name", "") or ""),
                str(symbol.get("file_path", "") or ""),
                symbol.get("start_line"),
                symbol.get("end_line"),
            )
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                {
                    "qualified_name": symbol.get("qualified_name", ""),
                    "name": symbol.get("name", ""),
                    "file_path": symbol.get("file_path", ""),
                    "kind": symbol.get("kind", ""),
                    "start_line": symbol.get("start_line"),
                    "end_line": symbol.get("end_line"),
                    "discovery_term": term,
                }
            )
            if len(matches) >= limit:
                return matches
    return matches

def cheap_ui_symbol_discovery_terms(search_task: str, query_rewrite: dict[str, object], limit: int = 4) -> list[str]:
    terms: list[str] = []

    def add_term(value: object) -> None:
        candidate = str(value or "").strip()
        if not candidate or candidate in terms:
            return
        tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", candidate.lower()) if token]
        if tokens and all(token in GENERIC_SEARCH_TERMS or token in STOPWORD_TOKENS for token in tokens):
            return
        terms.append(candidate)

    split_variant = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(search_task or "")).strip()
    if split_variant and split_variant != search_task:
        add_term(split_variant)
    core_terms = query_rewrite.get("core_terms", [])
    if isinstance(core_terms, list):
        focused = [str(term).strip() for term in core_terms if str(term).strip() and str(term) not in GENERIC_SEARCH_TERMS and str(term) not in STOPWORD_TOKENS]
        if len(focused) >= 2:
            add_term(" ".join(focused[:2]))
        for term in focused:
            add_term(term)
            if len(terms) >= limit:
                return terms[:limit]
    if split_variant:
        add_term(split_variant.replace(" ", ""))
    return terms[:limit]

def cheap_ui_symbol_discovery(
    duckdb_store: DuckDBStore,
    search_task: str,
    query_rewrite: dict[str, object],
    limit: int = 5,
) -> list[dict[str, object]]:
    search_chunks = getattr(duckdb_store, "search_chunks_content", None)
    fetch_symbols_for_file = getattr(duckdb_store, "fetch_symbols_for_file", None)
    if not callable(search_chunks) or not callable(fetch_symbols_for_file):
        return []
    matches: list[dict[str, object]] = []
    seen: set[tuple[str, str, object, object]] = set()
    for term in cheap_ui_symbol_discovery_terms(search_task, query_rewrite, limit=max(limit, 4)):
        chunk_rows = search_chunks(term, limit=max(limit * 2, 8))
        for chunk in chunk_rows:
            file_path = str(chunk.get("file_path", "") or "")
            if not file_path:
                continue
            for symbol in fetch_symbols_for_file(file_path)[:4]:
                key = (
                    str(symbol.get("qualified_name", "") or ""),
                    str(symbol.get("file_path", file_path) or file_path),
                    symbol.get("start_line"),
                    symbol.get("end_line"),
                )
                if key in seen:
                    continue
                seen.add(key)
                matches.append(
                    {
                        "qualified_name": symbol.get("qualified_name", symbol.get("name", "")),
                        "name": symbol.get("name", ""),
                        "file_path": symbol.get("file_path", file_path) or file_path,
                        "kind": symbol.get("kind", ""),
                        "start_line": symbol.get("start_line"),
                        "end_line": symbol.get("end_line"),
                        "discovery_term": term,
                        "discovery_source": "chunk_content",
                    }
                )
                if len(matches) >= limit:
                    return matches
    return matches
