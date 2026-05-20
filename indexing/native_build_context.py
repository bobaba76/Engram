from __future__ import annotations

import json
import re
import shlex
from functools import lru_cache
from pathlib import Path


_MPLAB_PROJECT_EXTENSIONS = (".mcp", ".mcw", ".mptags", ".scl", ".plt")
_BUILD_MARKERS = ("compile_commands.json", "CMakeLists.txt", "Makefile")
_STANDARD_PATTERN = re.compile(r"(?:-std=|/std:)(?P<value>[^\s]+)")
_DEFINE_PATTERN = re.compile(r"^(?:-D|/D)(?P<value>.+)$")
_INCLUDE_FLAG_PATTERN = re.compile(r"^(?:-I|/I)(?P<value>.+)$")
_CMAKE_TARGET_PATTERN = re.compile(r"\badd_(?:executable|library)\s*\(\s*(?P<target>[A-Za-z_][A-Za-z0-9_.+-]*)\s+(?P<sources>[^)]*)\)", re.IGNORECASE | re.DOTALL)
_MACRO_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_MACRO_BODY_PATTERN = re.compile(r"^[A-Za-z0-9_\s+\-*/%<>=!&|^~().,?:'\"\\[\]]*$")
_MPLAB_SOURCE_EXTENSIONS = {".c", ".cc", ".cpp", ".cxx", ".s", ".asm", ".S"}
_MPLAB_HEADER_EXTENSIONS = {".h", ".hh", ".hpp", ".hxx", ".inc"}
_MPLAB_LINKER_EXTENSIONS = {".gld", ".ld", ".lds", ".scl"}
MAX_EXPANDABLE_MACRO_BODY_LENGTH = 200


def _candidate_roots(file_path: Path) -> list[Path]:
    roots: list[Path] = []
    for parent in [file_path.parent, *file_path.parents]:
        if any((parent / marker).exists() for marker in _BUILD_MARKERS):
            roots.append(parent)
        if any(parent.glob("*.sln")) or any(parent.glob("*.vcxproj")):
            roots.append(parent)
        if any(any(parent.glob(f"*{extension}")) for extension in _MPLAB_PROJECT_EXTENSIONS):
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


def _read_text_file(path: Path, max_bytes: int = 1_000_000) -> str:
    try:
        payload = path.read_bytes()[:max_bytes]
    except OSError:
        return ""
    return payload.decode("utf-8", errors="ignore")


def _parse_ini_sections(source: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current = ""
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        section_match = re.fullmatch(r"\[(?P<section>[^\]]+)\]", line)
        if section_match:
            current = section_match.group("section").strip()
            sections.setdefault(current, {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        sections.setdefault(current, {})[key.strip()] = value.strip().strip('"')
    return sections


def _normalize_project_path(root: Path, value: str) -> str:
    token = str(value or "").strip().strip('"').replace("\\", "/")
    if not token:
        return ""
    path = Path(token)
    if not path.is_absolute():
        path = root / token
    try:
        return str(path.resolve()).replace("\\", "/")
    except OSError:
        return str(path).replace("\\", "/")


def _relative_project_path(root: Path, value: str) -> str:
    normalized = _normalize_project_path(root, value)
    if not normalized:
        return ""
    try:
        return str(Path(normalized).resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return normalized


def _parse_mplab_tool_options(sections: dict[str, dict[str, str]], root: Path) -> dict[str, list[str]]:
    include_dirs: list[str] = []
    defines: list[str] = []
    standards: list[str] = []
    tool_options: list[str] = []
    for value in sections.get("TOOL_SETTINGS", {}).values():
        if not value:
            continue
        tool_options.append(value)
        parsed = _parse_compile_flags(_tokenize_command(value), root)
        include_dirs.extend(str(item) for item in parsed.get("include_dirs", []) if item)
        defines.extend(str(item) for item in parsed.get("defines", []) if item)
        standards.extend(str(item) for item in parsed.get("standards", []) if item)
    return {
        "include_dirs": _unique(include_dirs, limit=30),
        "defines": _unique(defines, limit=30),
        "standards": _unique(standards, limit=12),
        "tool_options": _unique(tool_options, limit=12),
    }


@lru_cache(maxsize=64)
def _mplab_project_context(root: str) -> dict[str, object]:
    root_path = Path(root)
    project_files = sorted([path for extension in _MPLAB_PROJECT_EXTENSIONS for path in root_path.glob(f"*{extension}")])
    project_names: list[str] = []
    devices: list[str] = []
    include_dirs: list[str] = [str(root_path.resolve()).replace("\\", "/")]
    defines: list[str] = []
    standards: list[str] = []
    source_files: list[str] = []
    header_files: list[str] = []
    linker_scripts: list[str] = []
    tool_options: list[str] = []

    for project_file in project_files:
        if project_file.suffix.lower() != ".mcp":
            continue
        project_names.append(project_file.stem)
        sections = _parse_ini_sections(_read_text_file(project_file))
        header = sections.get("HEADER", {})
        if header.get("device"):
            devices.append(header["device"])
        path_info = sections.get("PATH_INFO", {})
        for key, value in path_info.items():
            if key.lower().startswith("dir_") and value:
                include_dirs.append(_normalize_project_path(root_path, value))
        subfolders = sections.get("CAT_SUBFOLDERS", {})
        for key, value in subfolders.items():
            if value and ("inc" in key.lower() or "src" in key.lower()):
                include_dirs.append(_normalize_project_path(root_path, value.replace("_", "")))
                include_dirs.append(_normalize_project_path(root_path, value))
        file_subfolders = sections.get("FILE_SUBFOLDERS", {})
        file_info = sections.get("FILE_INFO", {})
        for key, value in file_info.items():
            if not value:
                continue
            raw_path = value.replace("\\", "/")
            if "/" not in raw_path:
                subfolder = file_subfolders.get(key, "").replace("\\", "/").strip(".")
                if subfolder:
                    raw_path = f"{subfolder}/{raw_path}"
            relative = _relative_project_path(root_path, raw_path)
            suffix = Path(relative).suffix.lower()
            if suffix in {item.lower() for item in _MPLAB_SOURCE_EXTENSIONS}:
                source_files.append(relative)
            elif suffix in _MPLAB_HEADER_EXTENSIONS:
                header_files.append(relative)
            elif suffix in _MPLAB_LINKER_EXTENSIONS:
                linker_scripts.append(relative)
        parsed_tools = _parse_mplab_tool_options(sections, root_path)
        include_dirs.extend(parsed_tools["include_dirs"])
        defines.extend(parsed_tools["defines"])
        standards.extend(parsed_tools["standards"])
        tool_options.extend(parsed_tools["tool_options"])

    for scl_file in root_path.glob("*.scl"):
        linker_scripts.append(str(scl_file.resolve()).replace("\\", "/"))
        scl_source = _read_text_file(scl_file)
        for match in re.finditer(r'for\s+"(?P<device>[^"]+)"', scl_source, re.IGNORECASE):
            devices.append(match.group("device"))
    for plt_file in root_path.glob("*.plt"):
        linker_scripts.append(str(plt_file.resolve()).replace("\\", "/"))

    return {
        "project_names": _unique(project_names, limit=12),
        "devices": _unique(devices, limit=12),
        "include_dirs": _unique(include_dirs, limit=40),
        "defines": _unique(defines, limit=40),
        "standards": _unique(standards, limit=12),
        "source_files": _unique(source_files, limit=200),
        "header_files": _unique(header_files, limit=200),
        "linker_scripts": _unique(linker_scripts, limit=40),
        "tool_options": _unique(tool_options, limit=20),
        "project_files": _unique([path.name for path in project_files], limit=40),
    }


def _unique(values: list[object], limit: int = 50) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def _build_systems_for_root(root: Path) -> list[str]:
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
    if any(any(root.glob(f"*{extension}")) for extension in _MPLAB_PROJECT_EXTENSIONS):
        build_systems.append("mplab")
    return build_systems


def _compile_entry_target(compile_entry: dict[str, object], build_root: Path) -> str:
    output = str(compile_entry.get("output", "") or "").strip()
    if output:
        return Path(output).stem
    directory = Path(str(compile_entry.get("directory", build_root) or build_root))
    if directory.name.lower() not in {"", ".", "build", "debug", "release"}:
        return directory.name
    return build_root.name


@lru_cache(maxsize=64)
def _cmake_target_map(root: str) -> dict[str, str]:
    root_path = Path(root)
    cmake_file = root_path / "CMakeLists.txt"
    if not cmake_file.exists():
        return {}
    try:
        source = cmake_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    mapped: dict[str, str] = {}
    for match in _CMAKE_TARGET_PATTERN.finditer(source):
        target = str(match.group("target") or "").strip()
        raw_sources = str(match.group("sources") or "")
        for token in re.split(r"[\s\r\n]+", raw_sources):
            normalized = token.strip().strip('"').strip("'")
            if not normalized or normalized.startswith("$") or normalized.upper() in {"STATIC", "SHARED", "MODULE", "OBJECT", "EXCLUDE_FROM_ALL"}:
                continue
            suffix = Path(normalized).suffix.lower()
            if suffix not in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".hxx"}:
                continue
            candidate = (root_path / normalized).resolve()
            mapped[str(candidate)] = target
            mapped[normalized.replace("\\", "/")] = target
    return mapped


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
        "source_files": [],
        "header_files": [],
        "linker_scripts": [],
        "devices": [],
        "tool_options": [],
        "has_compile_commands": False,
        "compile_command_file": "",
        "target": "",
        "confidence": "low",
    }
    for root in _candidate_roots(file_path):
        build_systems = _build_systems_for_root(root)
        if build_systems:
            context["build_root"] = str(root).replace("\\", "/")
            context["build_systems"] = build_systems
            context["project_files"] = [
                str(path.name)
                for path in (
                    list(root.glob("*.sln"))[:4]
                    + list(root.glob("*.vcxproj"))[:8]
                    + [path for extension in _MPLAB_PROJECT_EXTENSIONS for path in list(root.glob(f"*{extension}"))[:4]]
                )
            ]
            context["confidence"] = "medium"
            if "mplab" in build_systems:
                mplab = _mplab_project_context(str(root))
                context["project_files"] = _unique(list(context["project_files"]) + list(mplab.get("project_files", [])), limit=40)
                context["include_dirs"] = _unique(list(context["include_dirs"]) + list(mplab.get("include_dirs", [])), limit=40)
                context["defines"] = _unique(list(context["defines"]) + list(mplab.get("defines", [])), limit=40)
                context["standards"] = _unique(list(context["standards"]) + list(mplab.get("standards", [])), limit=12)
                context["source_files"] = list(mplab.get("source_files", []))
                context["header_files"] = list(mplab.get("header_files", []))
                context["linker_scripts"] = list(mplab.get("linker_scripts", []))
                context["devices"] = list(mplab.get("devices", []))
                context["tool_options"] = list(mplab.get("tool_options", []))
                if not context["target"]:
                    project_names = list(mplab.get("project_names", []))
                    context["target"] = project_names[0] if project_names else root.name
            cmake_target = _cmake_target_map(str(root)).get(str(file_path)) or _cmake_target_map(str(root)).get(str(file_path.relative_to(root)).replace("\\", "/")) if root in file_path.parents or root == file_path.parent else ""
            if cmake_target and not context["target"]:
                context["target"] = cmake_target
        compile_entry = _compile_commands_map(str(root)).get(str(file_path))
        if compile_entry:
            context["has_compile_commands"] = True
            context["compile_command_file"] = str((root / "compile_commands.json").resolve()).replace("\\", "/")
            context["target"] = _compile_entry_target(compile_entry, root)
            context["confidence"] = "high"
            command_tokens = _tokenize_command(compile_entry.get("arguments") or compile_entry.get("command") or "")
            parsed = _parse_compile_flags(command_tokens, Path(str(compile_entry.get("directory", root))))
            context["compiler"] = parsed["compiler"]
            context["include_dirs"] = parsed["include_dirs"]
            context["defines"] = parsed["defines"]
            context["standards"] = parsed["standards"]
            break
    return context


def summarize_native_build_context(repo_root: str | Path, sample_limit: int = 200) -> dict[str, object]:
    root = Path(repo_root).resolve()
    build_roots: list[str] = []
    build_systems: list[str] = []
    project_files: list[str] = []
    compilers: list[str] = []
    include_dirs: list[str] = []
    defines: list[str] = []
    standards: list[str] = []
    targets: list[str] = []
    compile_command_files: list[str] = []
    source_files: list[str] = []
    header_files: list[str] = []
    linker_scripts: list[str] = []
    devices: list[str] = []
    tool_options: list[str] = []
    compile_entry_count = 0

    candidate_roots = [root]
    candidate_roots.extend(path.parent for path in root.rglob("compile_commands.json"))
    candidate_roots.extend(path.parent for path in root.rglob("CMakeLists.txt"))
    candidate_roots.extend(path.parent for path in root.rglob("Makefile"))
    candidate_roots.extend(path.parent for path in root.rglob("*.sln"))
    candidate_roots.extend(path.parent for path in root.rglob("*.vcxproj"))
    for extension in _MPLAB_PROJECT_EXTENSIONS:
        candidate_roots.extend(path.parent for path in root.rglob(f"*{extension}"))

    for candidate in _unique([str(path) for path in candidate_roots], limit=100):
        candidate_root = Path(candidate)
        systems = _build_systems_for_root(candidate_root)
        if not systems:
            continue
        build_roots.append(str(candidate_root).replace("\\", "/"))
        build_systems.extend(systems)
        project_files.extend(
            str(path.relative_to(root)).replace("\\", "/")
            for path in (
                list(candidate_root.glob("*.sln"))[:4]
                + list(candidate_root.glob("*.vcxproj"))[:8]
                + [path for extension in _MPLAB_PROJECT_EXTENSIONS for path in list(candidate_root.glob(f"*{extension}"))[:4]]
            )
        )
        targets.extend(_cmake_target_map(str(candidate_root)).values())
        if "mplab" in systems:
            mplab = _mplab_project_context(str(candidate_root))
            include_dirs.extend(str(item) for item in mplab.get("include_dirs", []) if item)
            defines.extend(str(item) for item in mplab.get("defines", []) if item)
            standards.extend(str(item) for item in mplab.get("standards", []) if item)
            source_files.extend(str(item) for item in mplab.get("source_files", []) if item)
            header_files.extend(str(item) for item in mplab.get("header_files", []) if item)
            linker_scripts.extend(str(item) for item in mplab.get("linker_scripts", []) if item)
            devices.extend(str(item) for item in mplab.get("devices", []) if item)
            tool_options.extend(str(item) for item in mplab.get("tool_options", []) if item)
            targets.extend(str(item) for item in mplab.get("project_names", []) if item)
        compile_commands = candidate_root / "compile_commands.json"
        if not compile_commands.exists():
            continue
        compile_command_files.append(str(compile_commands.resolve()).replace("\\", "/"))
        for compile_entry in list(_compile_commands_map(str(candidate_root)).values())[:sample_limit]:
            compile_entry_count += 1
            command_tokens = _tokenize_command(compile_entry.get("arguments") or compile_entry.get("command") or "")
            parsed = _parse_compile_flags(command_tokens, Path(str(compile_entry.get("directory", candidate_root))))
            compilers.append(str(parsed.get("compiler", "") or ""))
            include_dirs.extend(str(item) for item in parsed.get("include_dirs", []) if item)
            defines.extend(str(item) for item in parsed.get("defines", []) if item)
            standards.extend(str(item) for item in parsed.get("standards", []) if item)
            targets.append(_compile_entry_target(compile_entry, candidate_root))

    systems = _unique(build_systems, limit=12)
    confidence = "high" if compile_command_files else "medium" if systems else "low"
    warnings: list[str] = []
    if systems and not compile_command_files:
        if "mplab" in systems and (source_files or header_files):
            warnings.append("MPLAB project metadata was parsed, but no compile_commands.json was discovered; C/C++ compiler-flag confidence is limited.")
        else:
            warnings.append("Native build markers found, but no compile_commands.json was discovered; C/C++ semantic confidence is limited.")
    if not systems:
        warnings.append("No native build context discovered for C/C++ files.")
    return {
        "repo_root": str(root).replace("\\", "/"),
        "confidence": confidence,
        "build_systems": systems,
        "build_roots": _unique(build_roots, limit=12),
        "compile_command_files": _unique(compile_command_files, limit=8),
        "compile_entry_count": compile_entry_count,
        "compilers": _unique(compilers, limit=8),
        "include_dirs": _unique(include_dirs, limit=20),
        "defines": _unique(defines, limit=20),
        "standards": _unique(standards, limit=8),
        "targets": _unique(targets, limit=20),
        "devices": _unique(devices, limit=12),
        "source_files": _unique(source_files, limit=40),
        "header_files": _unique(header_files, limit=40),
        "linker_scripts": _unique(linker_scripts, limit=20),
        "tool_options": _unique(tool_options, limit=12),
        "project_files": _unique(project_files, limit=12),
        "warnings": warnings,
    }


def extract_macro_definitions(source: str, build_context: dict[str, object]) -> dict[str, str]:
    macros: dict[str, str] = {}
    for item in build_context.get("defines", []):
        token = str(item or "").strip()
        if not token:
            continue
        if "=" in token:
            name, value = token.split("=", 1)
            name = name.strip()
            value = value.strip()
            if _is_expandable_object_macro(name, value):
                macros[name] = value
        else:
            if _is_expandable_object_macro(token, "1"):
                macros[token] = "1"
    for line in source.splitlines():
        parsed = _parse_object_like_define(line)
        if parsed is None:
            continue
        name, body = parsed
        if _is_expandable_object_macro(name, body):
            macros[name] = body or "1"
    return macros


def _parse_object_like_define(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped.startswith("#define"):
        return None
    rest = stripped[len("#define"):].lstrip()
    if not rest:
        return None
    match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(.*)$", rest)
    if match is None:
        return None
    name = match.group(1)
    suffix = match.group(2)
    if suffix.startswith("("):
        return None
    return name, suffix.strip()


def _is_expandable_object_macro(name: str, body: str) -> bool:
    macro_name = str(name or "").strip()
    macro_body = str(body or "").strip() or "1"
    if not _MACRO_NAME_PATTERN.match(macro_name):
        return False
    if len(macro_body) > MAX_EXPANDABLE_MACRO_BODY_LENGTH:
        return False
    if re.match(r"^\(\s*[A-Za-z_][A-Za-z0-9_]*(?:\s*,|\s*\))", macro_body):
        return False
    if "#" in macro_body:
        return False
    if re.search(rf"\b{re.escape(macro_name)}\b", macro_body):
        return False
    if not _SAFE_MACRO_BODY_PATTERN.match(macro_body):
        return False
    return True


def expand_object_like_macros(text: str, macros: dict[str, str]) -> str:
    expanded = text
    for _ in range(3):
        changed = False
        for name, value in macros.items():
            if not _is_expandable_object_macro(name, value):
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
