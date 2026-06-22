from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable

from indexing.native_build_context import expand_object_like_macros, extract_macro_definitions, load_native_build_context, resolve_include_targets

logger = logging.getLogger(__name__)
from models.entity_models import SymbolRecord

try:
    from clang import cindex
except ImportError:
    cindex = None


_CLANG_CONFIGURED = False
_CLANG_STATUS: dict[str, object] = {
    "available": cindex is not None,
    "configured": False,
    "library_source": "",
    "library_value": "",
    "error": "",
}


_INTERESTING_CURSOR_KINDS = {
    "FUNCTION_DECL",
    "CXX_METHOD",
    "CONSTRUCTOR",
    "DESTRUCTOR",
    "CLASS_DECL",
    "STRUCT_DECL",
    "CLASS_TEMPLATE",
    "FUNCTION_TEMPLATE",
    "ENUM_DECL",
    "ENUM_CONSTANT_DECL",
    "TYPEDEF_DECL",
    "TYPE_ALIAS_DECL",
    "NAMESPACE",
    "MACRO_DEFINITION",
}
_REFERENCED_CURSOR_KINDS = {"CALL_EXPR", "DECL_REF_EXPR", "MEMBER_REF_EXPR"}
CLANG_SUBPROCESS_TIMEOUT_SECONDS = float(os.environ.get("CODER_CLANG_SUBPROCESS_TIMEOUT_SECONDS", "10") or "10")


def _kind_name(cursor) -> str:
    return str(getattr(cursor.kind, "name", "") or "")


def clang_available() -> bool:
    status = clang_runtime_status()
    return bool(status.get("available")) and not bool(status.get("error"))


def clang_runtime_status() -> dict[str, object]:
    global _CLANG_CONFIGURED
    if cindex is None:
        return dict(_CLANG_STATUS)
    if _CLANG_CONFIGURED:
        return dict(_CLANG_STATUS)
    _CLANG_CONFIGURED = True
    library_file = os.environ.get("CODER_LIBCLANG_DLL", "").strip() or os.environ.get("LIBCLANG_PATH", "").strip()
    library_path = os.environ.get("CODER_LIBCLANG_PATH", "").strip()
    try:
        if library_file:
            cindex.Config.set_library_file(library_file)
            _CLANG_STATUS.update({"configured": True, "library_source": "file", "library_value": library_file, "error": ""})
        elif library_path:
            cindex.Config.set_library_path(library_path)
            _CLANG_STATUS.update({"configured": True, "library_source": "path", "library_value": library_path, "error": ""})
        else:
            _CLANG_STATUS.update({"configured": True, "library_source": "default", "library_value": "", "error": ""})
    except Exception as exc:
        _CLANG_STATUS.update({"configured": False, "error": str(exc)})
    return dict(_CLANG_STATUS)


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


def _canonical_name(value: str) -> str:
    token = str(value or "").strip()
    return token.replace("::", ".").replace("->", ".")


def _qualified_cursor_name(cursor) -> str:
    parts: list[str] = []
    current = cursor
    while current is not None and getattr(current, "kind", None) is not None:
        spelling = str(getattr(current, "spelling", "") or "").strip()
        kind_name = _kind_name(current)
        if spelling and kind_name not in {"TRANSLATION_UNIT", "UNEXPOSED_DECL"}:
            parts.append(spelling)
        current = getattr(current, "semantic_parent", None)
        if current is None or _kind_name(current) == "TRANSLATION_UNIT":
            break
    qualified = ".".join(reversed(parts))
    return _canonical_name(qualified)


def _signature(cursor) -> str:
    display_name = str(getattr(cursor, "displayname", "") or "").strip()
    if display_name:
        return _canonical_name(display_name)
    spelling = str(getattr(cursor, "spelling", "") or "").strip()
    if not spelling:
        return ""
    return _canonical_name(spelling)


def _symbol_kind(cursor) -> str:
    kind_name = _kind_name(cursor)
    if kind_name in {"CLASS_DECL", "CLASS_TEMPLATE"}:
        return "class"
    if kind_name in {"STRUCT_DECL", "ENUM_DECL"}:
        return "type"
    if kind_name in {"TYPEDEF_DECL", "TYPE_ALIAS_DECL"}:
        return "typedef"
    if kind_name in {"ENUM_CONSTANT_DECL"}:
        return "constant"
    if kind_name in {"NAMESPACE"}:
        return "namespace"
    if kind_name in {"MACRO_DEFINITION"}:
        return "macro"
    if kind_name in {"CXX_METHOD", "CONSTRUCTOR", "DESTRUCTOR"}:
        return "method"
    return "function"


def _build_args(file_path: Path, build_context: dict[str, object]) -> list[str]:
    args: list[str] = []
    for include_dir in build_context.get("include_dirs", []):
        if include_dir:
            args.append(f"-I{include_dir}")
    for define in build_context.get("defines", []):
        if define:
            args.append(f"-D{define}")
    for standard in build_context.get("standards", []):
        if standard:
            standard_token = str(standard)
            if not standard_token.startswith("-std="):
                standard_token = f"-std={standard_token}"
            args.append(standard_token)
    if file_path.suffix.lower() in {".hpp", ".hh", ".hxx", ".cpp", ".cc", ".cxx"}:
        args.extend(["-x", "c++"])
    else:
        args.extend(["-x", "c"])
    args.append("-Xclang")
    args.append("-detailed-preprocessing-record")
    return args


def _iter_references(cursor) -> Iterable[str]:
    for child in cursor.get_children():
        kind_name = _kind_name(child)
        if kind_name in _REFERENCED_CURSOR_KINDS:
            spelling = str(getattr(child, "spelling", "") or "").strip()
            referenced = getattr(child, "referenced", None)
            if referenced is not None:
                referenced_name = _qualified_cursor_name(referenced) or str(getattr(referenced, "spelling", "") or "").strip()
                if referenced_name:
                    yield _canonical_name(referenced_name)
                    continue
            if spelling:
                yield _canonical_name(spelling)
        yield from _iter_references(child)


def _cursor_symbols(cursor, file_path: Path, build_context: dict[str, object], imports: list[str], macros: dict[str, str]) -> list[SymbolRecord]:
    symbols: list[SymbolRecord] = []
    location = getattr(cursor, "location", None)
    if location is not None:
        cursor_file = getattr(location, "file", None)
        if cursor_file is not None:
            try:
                if Path(str(cursor_file.name)).resolve() != file_path.resolve():
                    return []
            except Exception:
                logger.warning("clang_extractor: file path comparison failed for %s", file_path, exc_info=True)
                return []
    kind_name = _kind_name(cursor)
    if kind_name in _INTERESTING_CURSOR_KINDS:
        spelling = str(getattr(cursor, "spelling", "") or "").strip()
        qualified_name = _qualified_cursor_name(cursor)
        if not qualified_name and spelling:
            qualified_name = _canonical_name(spelling)
        if spelling or qualified_name:
            extent = getattr(cursor, "extent", None)
            start_line = getattr(getattr(extent, "start", None), "line", 1) if extent is not None else 1
            end_line = getattr(getattr(extent, "end", None), "line", start_line) if extent is not None else start_line
            display_name = str(getattr(cursor, "displayname", "") or spelling or qualified_name)
            expanded_display = expand_object_like_macros(display_name, macros)
            references = sorted({value for value in _iter_references(cursor) if value and value != qualified_name})
            calls = sorted({value.split(".")[-1] for value in references if value.split(".")[-1] != spelling})
            signature = _canonical_name(expanded_display) or qualified_name or spelling
            metadata = {
                "parser": "clang",
                "language": "cpp" if file_path.suffix.lower() in {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"} else "c",
                "node_type": kind_name.lower(),
                "imports": imports,
                "calls": calls,
                "references": references,
                "translation_unit": _translation_unit_name(file_path),
                "file_role": "header" if file_path.suffix.lower() in {".h", ".hpp", ".hh", ".hxx"} else "source",
                "source_associations": _associated_source_candidates(file_path),
                "build_context": build_context,
                "is_definition": bool(getattr(cursor, "is_definition", lambda: False)()),
                "is_declaration": kind_name in {"FUNCTION_DECL", "CXX_METHOD", "CONSTRUCTOR", "DESTRUCTOR"} and not bool(getattr(cursor, "is_definition", lambda: False)()),
            }
            symbols.append(
                SymbolRecord(
                    name=spelling or qualified_name.split(".")[-1],
                    qualified_name=qualified_name or spelling,
                    kind=_symbol_kind(cursor),
                    start_line=int(start_line or 1),
                    end_line=int(end_line or start_line or 1),
                    signature=signature,
                    metadata=metadata,
                )
            )
    for child in cursor.get_children():
        symbols.extend(_cursor_symbols(child, file_path, build_context, imports, macros))
    return symbols


def _symbol_to_dict(symbol: SymbolRecord) -> dict[str, object]:
    return {
        "name": symbol.name,
        "qualified_name": symbol.qualified_name,
        "kind": symbol.kind,
        "start_line": symbol.start_line,
        "end_line": symbol.end_line,
        "signature": symbol.signature,
        "metadata": symbol.metadata,
    }


def _symbol_from_dict(payload: dict[str, object]) -> SymbolRecord:
    metadata = payload.get("metadata", {})
    return SymbolRecord(
        name=str(payload.get("name", "") or ""),
        qualified_name=str(payload.get("qualified_name", "") or ""),
        kind=str(payload.get("kind", "") or ""),
        start_line=int(payload.get("start_line", 1) or 1),
        end_line=int(payload.get("end_line", payload.get("start_line", 1)) or 1),
        signature=str(payload.get("signature", "") or ""),
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def _extract_clang_symbols_in_process(file_path: Path) -> list[SymbolRecord]:
    status = clang_runtime_status()
    if not status.get("available") or status.get("error"):
        return []
    build_context = load_native_build_context(str(file_path))
    source = file_path.read_text(encoding="utf-8", errors="ignore")
    macros = extract_macro_definitions(source, build_context)
    imports = resolve_include_targets(str(file_path), [line.split("include", 1)[1].strip().strip('<>"') for line in source.splitlines() if line.strip().startswith("#include")], build_context)
    args = _build_args(file_path, build_context)
    try:
        index = cindex.Index.create()
        translation_unit = index.parse(str(file_path), args=args)
    except Exception:
        logger.warning("clang_extractor: clang failed to parse %s", file_path, exc_info=True)
        return []
    symbols = _cursor_symbols(translation_unit.cursor, file_path, build_context, imports, macros)
    deduped: list[SymbolRecord] = []
    seen: set[tuple[str, int, str]] = set()
    for symbol in sorted(symbols, key=lambda item: (item.start_line, item.end_line, item.qualified_name)):
        key = (symbol.qualified_name, symbol.start_line, symbol.kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(symbol)
    return deduped


def extract_clang_symbols(file_path: Path) -> list[SymbolRecord]:
    if os.environ.get("CODER_CLANG_IN_PROCESS", "").strip().lower() in {"1", "true", "yes"}:
        return _extract_clang_symbols_in_process(file_path)
    command = [
        sys.executable,
        "-m",
        "indexing.clang_worker",
        str(file_path.resolve()),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=CLANG_SUBPROCESS_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if completed.returncode != 0:
        return []
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return []
    symbols = payload.get("symbols", []) if isinstance(payload, dict) else []
    if not isinstance(symbols, list):
        return []
    return [_symbol_from_dict(item) for item in symbols if isinstance(item, dict)]
