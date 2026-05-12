from pathlib import Path

from indexing.scanner import scan_repo
from indexing.symbol_extractor import extract_symbols_with_status
from services.detect_changes_service import _file_risk, _path_risk_hints, _symbol_risk_hints


def test_scanner_recognizes_object_pascal_files(tmp_path: Path) -> None:
    for name in ["App.dpr", "CustomerService.pas", "MainForm.dfm", "Package.dpk", "Project.lpi"]:
        (tmp_path / name).write_text("unit Sample;", encoding="utf-8")

    records = scan_repo(tmp_path)
    languages = {record.path: record.language for record in records}

    assert languages["App.dpr"] == "object_pascal_project"
    assert languages["CustomerService.pas"] == "object_pascal"
    assert languages["MainForm.dfm"] == "object_pascal_form"
    assert languages["Package.dpk"] == "object_pascal_package"
    assert languages["Project.lpi"] == "object_pascal_project"


def test_object_pascal_path_risk_hints() -> None:
    assert "Object Pascal project/package path" in _path_risk_hints("src/App.dpr")
    assert "Object Pascal form/resource path" in _path_risk_hints("src/MainForm.dfm")
    assert "Object Pascal unit/source path" in _path_risk_hints("src/CustomerService.pas")
    assert "Object Pascal form event wiring path" in _path_risk_hints("src/LoginForm.lfm")
    assert _file_risk("src/App.dpr", changed_symbol_count=0, impacted=False) == "HIGH"
    assert _file_risk("src/CustomerService.pas", changed_symbol_count=0, impacted=False) == "MEDIUM"


def test_object_pascal_form_parser_extracts_components_and_events(tmp_path: Path) -> None:
    source = tmp_path / "MainForm.dfm"
    source.write_text(
        "object MainForm: TMainForm\n"
        "  object SaveButton: TButton\n"
        "    Caption = 'Save'\n"
        "    OnClick = SaveButtonClick\n"
        "  end\n"
        "end\n",
        encoding="utf-8",
    )

    symbols, status = extract_symbols_with_status(source)
    names = {symbol.qualified_name for symbol in symbols}
    binding = next(symbol for symbol in symbols if symbol.kind == "event_handler_binding")

    assert status["language"] == "object_pascal_form"
    assert status["event_handlers"] == ["SaveButtonClick"]
    assert "MainForm.MainForm" in names
    assert "MainForm.SaveButton" in names
    assert binding.metadata["event"] == "OnClick"
    assert binding.metadata["handler"] == "SaveButtonClick"
    assert binding.metadata["calls"] == ["SaveButtonClick"]
    assert any(path.endswith("MainForm.pas") for path in binding.metadata.get("source_associations", []))


def test_object_pascal_form_parser_extracts_hierarchy_and_key_properties(tmp_path: Path) -> None:
    source = tmp_path / "MainForm.lfm"
    source.write_text(
        "inherited MainForm: TMainForm\n"
        "  object DataSource1: TDataSource\n"
        "  end\n"
        "  object Panel1: TPanel\n"
        "    object CustomerName: TDBEdit\n"
        "      DataSource = DataSource1\n"
        "      DataField = 'Name'\n"
        "      Action = SaveAction\n"
        "    end\n"
        "  end\n"
        "end\n",
        encoding="utf-8",
    )

    symbols, status = extract_symbols_with_status(source)
    form = next(symbol for symbol in symbols if symbol.name == "MainForm")
    panel = next(symbol for symbol in symbols if symbol.name == "Panel1")
    edit = next(symbol for symbol in symbols if symbol.name == "CustomerName")

    assert status["component_count"] == 4
    assert form.metadata["inherited_component"] is True
    assert panel.metadata["component_parent"] == "MainForm.MainForm"
    assert edit.metadata["component_parent"] == "MainForm.Panel1"
    assert {"property": "DataSource", "value": "DataSource1"} in edit.metadata["component_properties"]
    assert {"property": "DataField", "value": "Name"} in edit.metadata["component_properties"]
    assert "DataSource1" in edit.metadata["references"]
    assert "SaveAction" in edit.metadata["references"]


def test_object_pascal_public_dependency_surface_is_high_risk() -> None:
    hints = _symbol_risk_hints(
        "src/Orders.pas",
        [
            {
                "kind": "unit",
                "metadata": {
                    "language": "object_pascal",
                    "public_dependency_surface": True,
                    "interface_uses": ["SysUtils"],
                },
            }
        ],
    )

    assert "Object Pascal public unit dependency surface" in hints
    assert _file_risk("src/Orders.pas", changed_symbol_count=1, impacted=False) == "MEDIUM"


def test_object_pascal_project_ownership_surface_is_high_risk() -> None:
    hints = _symbol_risk_hints(
        "CustomerApp.dproj",
        [
            {
                "kind": "project",
                "metadata": {
                    "language": "object_pascal_project",
                    "project_ownership_surface": True,
                    "project_references": ["CustomerService.pas"],
                },
            }
        ],
    )

    assert "Object Pascal project ownership surface" in hints


def test_object_pascal_include_and_conditional_surfaces_are_high_risk() -> None:
    hints = _symbol_risk_hints(
        "CustomerService.pas",
        [
            {
                "kind": "unit",
                "metadata": {
                    "language": "object_pascal",
                    "include_files": ["Shared.inc"],
                    "conditional_symbols": ["DEBUG"],
                },
            }
        ],
    )

    assert "Object Pascal include dependency surface" in hints
    assert "Object Pascal conditional compilation surface" in hints
