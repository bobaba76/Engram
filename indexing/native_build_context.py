from __future__ import annotations

import json
import re
import shlex
from functools import lru_cache
from pathlib import Path


_BUILD_MARKERS = ("compile_commands.json", "CMakeLists.txt", "Makefile")
_STANDARD_PATTERN = re.compile(r"(?:-std=|/std:)(?P<value>[^\s]+)")
_DEFINE_PATTERN = re.compile(r"^(?:-D|/D)(?P<value>.+)$")
_INCLUDE_FLAG_PATTERN = re.compile(r"^(?:-I|/I)(?P<value>.+)$")


def _candidate_roots(file_path: Path) -> list[Path]:
    roots: list[Path] = []
    for parent in [file_path.parent, *file_path.parents]:
        if any((parent / marker).exists() for marker in _BUILD_MARKERS):
            roots.append(parent)
        if any(parent.glob("*.sln")) or any(parent.glob("*.vcxproj")):
            roots.append(parent)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        deduped.append(root)
    return deduped


@lru_cache(maxsize=32)
def _compile_commands_map(root: str) -> dict[str, dict[str, object]]:
    root_path = Path(root)
    compile_commands = root_path / "compile_commands.json"
    if not compile_commands.exists():
        return {}
    try:
        payload = json.loads(compile_commands.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    mapped: dict[str, dict[str, object]] = {}
    for item in payload if isinstance(payload, list) else []:
        file_name = str(item.get("file", "")).strip()
        if not file_name:
            continue
        try:
            file_path = Path(file_name)
            if not file_path.is_absolute():
                file_path = (Path(str(item.get("directory", root))) / file_path).resolve()
        except Exception:
            continue
        mapped[str(file_path)] = item
    return mapped


def _tokenize_command(command: str | list[str]) -> list[str]:
    if isinstance(command, list):
        return [str(token) for token in command]
    try:
        return shlex.split(str(command), posix=False)
    except ValueError:
        return str(command).split()


def _parse_compile_flags(command_tokens: list[str], base_dir: Path) -> dict[str, object]:
    include_dirs: list[str] = []
    defines: list[str] = []
    standards: list[str] = []
    compiler = command_tokens[0] if command_tokens else ""
    index = 0
    while index < len(command_tokens):
        token = str(command_tokens[index])
        define_match = _DEFINE_PATTERN.match(token)
        include_match = _INCLUDE_FLAG_PATTERN.match(token)
        standard_match = _STANDARD_PATTERN.match(token)
        if token in {"-I", "/I", "-isystem"} and index + 1 < len(command_tokens):
            include_value = str(command_tokens[index + 1]).strip('"')
            include_path = (base_dir / include_value).resolve() if include_value and not Path(include_value).is_absolute() else Path(include_value)
            include_dirs.append(str(include_path).replace("\\", "/"))
            index += 2
            continue
        if token in {"-D", "/D"} and index + 1 < len(command_tokens):
            defines.append(str(command_tokens[index + 1]))
            index += 2
            continue
        if include_match:
            include_value = include_match.group("value").strip('"')
            include_path = (base_dir / include_value).resolve() if include_value and not Path(include_value).is_absolute() else Path(include_value)
            include_dirs.append(str(include_path).replace("\\", "/"))
        elif define_match:
            defines.append(define_match.group("value"))
        elif standard_match:
            standards.append(standard_match.group("value"))
        index += 1
    return {
        "compiler": compiler,
        "include_dirs": include_dirs,
        "defines": defines,
        "standards": standards,
    }


@lru_cache(maxsize=128)
def load_native_build_context(file_path_str: str) -> dict[str, object]:
    file_path = Path(file_path_str).resolve()
    context = {
        "build_root": str(file_path.parent).replace("\\", "/"),
        "build_systems": [],
        "compiler": "",
        "include_dirs": [],
        "defines": [],
        "standards": [],
        "project_files": [],
        "has_compile_commands": False,
    }
    for root in _candidate_roots(file_path):
        build_systems: list[str] = []
        if (root / "compile_commands.json").exists():
            build_systems.append("compile_commands")
        if (root / "CMakeLists.txt").exists():
            build_systems.append("cmake")
        if (root / "Makefile").exists():
            build_systems.append("make")
        if any(root.glob("*.sln")):
            build_systems.append("sln")
        if any(root.glob("*.vcxproj")):
            build_systems.append("vcxproj")
        if build_systems:
            context["build_root"] = str(root).replace("\\", "/")
            context["build_systems"] = build_systems
            context["project_files"] = [str(path.name) for path in list(root.glob("*.sln"))[:4] + list(root.glob("*.vcxproj"))[:8]]
        compile_entry = _compile_commands_map(str(root)).get(str(file_path))
        if compile_entry:
            context["has_compile_commands"] = True
            command_tokens = _tokenize_command(compile_entry.get("arguments") or compile_entry.get("command") or "")
            parsed = _parse_compile_flags(command_tokens, Path(str(compile_entry.get("directory", root))))
            context["compiler"] = parsed["compiler"]
            context["include_dirs"] = parsed["include_dirs"]
            context["defines"] = parsed["defines"]
            context["standards"] = parsed["standards"]
            break
    return context


def extract_macro_definitions(source: str, build_context: dict[str, object]) -> dict[str, str]:
    macros: dict[str, str] = {}
    for item in build_context.get("defines", []):
        token = str(item or "").strip()
        if not token:
            continue
        if "=" in token:
            name, value = token.split("=", 1)
            macros[name.strip()] = value.strip()
        else:
            macros[token] = "1"
    for match in re.finditer(r"^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$", source, re.MULTILINE):
        name = str(match.group(1) or "").strip()
        body = str(match.group(2) or "").strip()
        if name and "(" not in name:
            macros[name] = body or "1"
    return macros


def expand_object_like_macros(text: str, macros: dict[str, str]) -> str:
    expanded = text
    for _ in range(3):
        changed = False
        for name, value in macros.items():
            if not name or "(" in name:
                continue
            pattern = re.compile(rf"\b{re.escape(name)}\b")
            updated = pattern.sub(lambda _: str(value), expanded)
            if updated != expanded:
                changed = True
                expanded = updated
        if not changed:
            break
    return expanded


def resolve_include_targets(file_path_str: str, includes: list[str], build_context: dict[str, object]) -> list[str]:
    file_path = Path(file_path_str).resolve()
    resolved: list[str] = []
    include_roots = [file_path.parent]
    for include_dir in build_context.get("include_dirs", []):
        include_roots.append(Path(str(include_dir)))
    build_root = Path(str(build_context.get("build_root", file_path.parent)))
    for include in includes:
        token = str(include or "").strip()
        if not token:
            continue
        include_path = Path(token)
        candidates = [root / include_path for root in include_roots]
        for candidate in candidates:
            if candidate.exists():
                try:
                    resolved.append(str(candidate.resolve().relative_to(build_root)).replace("\\", "/"))
                except Exception:
                    resolved.append(str(candidate.resolve()).replace("\\", "/"))
                break
        else:
            resolved.append(token)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in resolved:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
