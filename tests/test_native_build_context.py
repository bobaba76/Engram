import json
import subprocess
from pathlib import Path

from indexing.native_build_context import expand_object_like_macros, extract_macro_definitions, load_native_build_context, summarize_native_build_context
from indexing.symbol_extractor import extract_symbols_with_status


def test_native_build_context_loads_compile_commands_for_c_file(tmp_path: Path) -> None:
    include_dir = tmp_path / "include"
    src_dir = tmp_path / "src"
    include_dir.mkdir()
    src_dir.mkdir()
    source = src_dir / "engine.c"
    source.write_text(
        '#include "engine.h"\n'
        "int run_engine(void) { return FEATURE_FLAG; }\n",
        encoding="utf-8",
    )
    (include_dir / "engine.h").write_text("#define FEATURE_FLAG 1\n", encoding="utf-8")
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": str(source),
                    "command": "clang -I include -DFEATURE_FLAG=7 -std=c11 -c src/engine.c -o CMakeFiles/app.dir/src/engine.c.o",
                    "output": "CMakeFiles/app.dir/src/engine.c.o",
                }
            ]
        ),
        encoding="utf-8",
    )

    context = load_native_build_context(str(source))

    assert context["confidence"] == "high"
    assert context["has_compile_commands"] is True
    assert context["target"] == "engine.c"
    assert "compile_commands" in context["build_systems"]
    assert str(include_dir).replace("\\", "/") in context["include_dirs"]
    assert "FEATURE_FLAG=7" in context["defines"]
    assert context["standards"] == ["c11"]


def test_c_parser_status_exposes_build_context(tmp_path: Path) -> None:
    source = tmp_path / "engine.c"
    source.write_text("int run_engine(void) { return 1; }\n", encoding="utf-8")
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": str(source),
                    "arguments": ["clang", "-I", ".", "-DPLATFORM_TEST", "-std=c17", "-c", str(source)],
                }
            ]
        ),
        encoding="utf-8",
    )

    symbols, status = extract_symbols_with_status(source)

    assert symbols
    assert status["language"] == "c"
    assert status["build_context"]["confidence"] == "high"
    assert status["build_context"]["has_compile_commands"] is True
    assert "PLATFORM_TEST" in status["build_context"]["defines"]


def test_clang_extractor_uses_isolated_worker_process(tmp_path: Path, monkeypatch) -> None:
    from indexing import clang_extractor

    source = tmp_path / "engine.c"
    source.write_text("int run_engine(void) { return 1; }\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"symbols":[{"name":"run_engine","qualified_name":"run_engine","kind":"function",'
                '"start_line":1,"end_line":1,"signature":"run_engine(void)","metadata":{"parser":"clang"}}]}'
            ),
            stderr="",
        )

    monkeypatch.delenv("CODER_CLANG_IN_PROCESS", raising=False)
    monkeypatch.setattr(clang_extractor.subprocess, "run", fake_run)

    symbols = clang_extractor.extract_clang_symbols(source)

    assert calls
    assert calls[0][1:3] == ["-m", "indexing.clang_worker"]
    assert symbols[0].name == "run_engine"
    assert symbols[0].metadata["parser"] == "clang"


def test_summarize_native_build_context_reports_repo_level_confidence(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    source = src_dir / "engine.cpp"
    source.write_text("int run_engine() { return 1; }\n", encoding="utf-8")
    (tmp_path / "CMakeLists.txt").write_text("add_executable(app src/engine.cpp)\n", encoding="utf-8")
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": str(source),
                    "command": "clang++ -I src -DAPP_BUILD -std=c++20 -c src/engine.cpp",
                }
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_native_build_context(tmp_path)

    assert summary["confidence"] == "high"
    assert set(summary["build_systems"]) >= {"compile_commands", "cmake"}
    assert summary["compile_entry_count"] == 1
    assert "clang++" in summary["compilers"]
    assert "APP_BUILD" in summary["defines"]
    assert "c++20" in summary["standards"]
    assert tmp_path.name in summary["targets"]


def test_native_build_context_maps_cmake_targets_without_compile_commands(tmp_path: Path) -> None:
    source = tmp_path / "src" / "engine.c"
    source.parent.mkdir()
    source.write_text("int run_engine(void) { return 1; }\n", encoding="utf-8")
    (tmp_path / "CMakeLists.txt").write_text(
        "add_library(engine STATIC src/engine.c include/engine.h)\n",
        encoding="utf-8",
    )

    context = load_native_build_context(str(source))
    summary = summarize_native_build_context(tmp_path)

    assert context["confidence"] == "medium"
    assert context["target"] == "engine"
    assert "engine" in summary["targets"]


def test_macro_extraction_skips_function_like_recursive_and_unsafe_macros() -> None:
    source = "\n".join(
        [
            "#define SAFE_LIMIT 42",
            "#define FEATURE_FLAG",
            "#define CALL(x) do_call(x)",
            "#define LOOP LOOP + 1",
            "#define CONCAT(a, b) a ## b",
            "#define HUGE " + ("A" * 240),
        ]
    )

    macros = extract_macro_definitions(source, {"defines": ["CLI_SAFE=7", "CLI_LOOP=CLI_LOOP + 1"]})

    assert macros == {
        "CLI_SAFE": "7",
        "SAFE_LIMIT": "42",
        "FEATURE_FLAG": "1",
    }


def test_macro_expansion_revalidates_before_substitution() -> None:
    expanded = expand_object_like_macros(
        "return SAFE_LIMIT + LOOP + CALL(1);",
        {
            "SAFE_LIMIT": "42",
            "LOOP": "LOOP + 1",
            "CALL": "(x) do_call(x)",
        },
    )

    assert expanded == "return 42 + LOOP + CALL(1);"
