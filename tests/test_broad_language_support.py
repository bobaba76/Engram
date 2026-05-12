from pathlib import Path

from indexing.scanner import scan_repo
from indexing.symbol_extractor import extract_symbols_with_status


def test_scanner_recognizes_broad_language_files(tmp_path: Path) -> None:
    samples = {
        "service.go": "package main\nfunc Run() {}\n",
        "lib.rs": "pub fn run() {}\n",
        "worker.rb": "class Worker\nend\n",
        "app.php": "<?php function run_app() {}\n",
        "View.swift": "class ViewModel {}\n",
        "build.gradle.kts": "fun configureBuild() {}\n",
        "query.sql": "CREATE PROCEDURE refresh_data AS SELECT 1;\n",
        "script.ps1": "function Invoke-Thing { }\n",
        "go.mod": "module example.com/app\n",
        "Cargo.toml": "[package]\nname = 'app'\n",
    }
    for name, source in samples.items():
        (tmp_path / name).write_text(source, encoding="utf-8")

    records = scan_repo(tmp_path)
    languages = {record.path: record.language for record in records}

    assert languages["service.go"] == "go"
    assert languages["lib.rs"] == "rust"
    assert languages["worker.rb"] == "ruby"
    assert languages["app.php"] == "php"
    assert languages["View.swift"] == "swift"
    assert languages["build.gradle.kts"] == "kotlin"
    assert languages["query.sql"] == "sql"
    assert languages["script.ps1"] == "powershell"
    assert languages["go.mod"] == "go_project"
    assert languages["Cargo.toml"] == "rust_project"


def test_generic_parser_extracts_common_symbols(tmp_path: Path) -> None:
    cases = {
        "service.go": "package main\nimport fmt\nfunc RunService() { fmt.Println(\"ok\") }\n",
        "worker.rb": "require 'json'\nclass Worker\n  def perform\n    helper()\n  end\nend\n",
        "lib.rs": "use std::io;\nstruct Engine {}\nfn run_engine() { start(); }\n",
    }
    for file_name, source in cases.items():
        path = tmp_path / file_name
        path.write_text(source, encoding="utf-8")
        symbols, status = extract_symbols_with_status(path)

        assert status["parser"] == "generic_regex"
        assert symbols
        assert any(symbol.metadata.get("imports") for symbol in symbols)
