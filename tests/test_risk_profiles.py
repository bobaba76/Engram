from services.detect_changes_service import _file_risk, _path_risk_hints, _risk_explanation, _weighted_risk
from services.risk_profiles import (
    embedded_sensitive_path_hints,
    high_risk_path_hints,
    high_risk_symbol_hints,
    path_risk_hints,
)


def test_risk_profile_preserves_embedded_c_hints() -> None:
    hints = path_risk_hints("V0.99/GLOBAL.H")

    assert "global embedded C contract header" in hints
    assert "public/native header surface" in hints
    assert high_risk_path_hints(hints)
    assert embedded_sensitive_path_hints(hints)
    assert _file_risk("V0.99/GLOBAL.H", changed_symbol_count=0, impacted=False) == "HIGH"


def test_risk_profile_preserves_mplab_project_hints() -> None:
    hints = _path_risk_hints("V0.99/Video Overlay.mcp")

    assert "MPLAB embedded project/config path" in hints
    assert embedded_sensitive_path_hints(hints)
    assert _file_risk("V0.99/Video Overlay.mcp", changed_symbol_count=0, impacted=False) == "HIGH"


def test_risk_profile_preserves_csharp_and_pascal_hints() -> None:
    assert "C# public route/API path" in path_risk_hints("src/Controllers/ProductsController.cs")
    assert "C# DTO/API contract path" in path_risk_hints("src/Contracts/ProductResponse.cs")

    pascal_hints = path_risk_hints("src/MainForm.dfm")
    assert "Object Pascal form/resource path" in pascal_hints
    assert "Object Pascal form event wiring path" in pascal_hints
    assert high_risk_path_hints(pascal_hints)


def test_symbol_hint_classification_is_centralized() -> None:
    assert high_risk_symbol_hints(["native exported symbol"])
    assert high_risk_symbol_hints(["Object Pascal conditional compilation surface"])
    assert not high_risk_symbol_hints(["native implementation file"])


def test_interrupt_vector_hint_does_not_match_normal_vector_store_names() -> None:
    assert "interrupt/trap/startup path" not in path_risk_hints("storage/vector_store.py")
    assert "interrupt/trap/startup path" in path_risk_hints("firmware/interrupt_vectors.c")
    linker_hints = path_risk_hints("firmware/app.gld")
    assert "native linker/memory layout script" in linker_hints
    assert high_risk_path_hints(linker_hints)


def test_embedded_sensitive_counts_use_profile_metadata() -> None:
    risk_by_file = [
        {
            "file": "V0.99/GLOBAL.H",
            "risk": "HIGH",
            "risk_factors": ["global embedded C contract header", "public/native header surface"],
        },
        {
            "file": "src/native.c",
            "risk": "MEDIUM",
            "risk_factors": ["native implementation file"],
        },
    ]

    explanations = _risk_explanation(["V0.99/GLOBAL.H"], [], [], risk_by_file)
    weighted = _weighted_risk(["V0.99/GLOBAL.H"], [], [], risk_by_file, {}, {})

    assert "1 embedded-C sensitive file(s) changed" in explanations
    assert any("embedded-C sensitive changed file" in factor for factor in weighted["factors"])
