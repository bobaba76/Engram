from __future__ import annotations

from typing import TYPE_CHECKING

from services.change_report_service import change_impact_report
from services.index_status_service import check_stale_index
from services.test_intelligence_service import suggest_tests_for_change, test_impact

if TYPE_CHECKING:
    from pathlib import Path
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


def post_change_review(
    repo_root: Path,
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    scope: str = "unstaged",
    base_ref: str = "",
    max_symbols: int = 5,
    target: str = "",
    include_stale_check: bool = True,
) -> dict[str, object]:
    """Orchestrate a full post-change review in a single call.

    Chains:
    1. detect_changes — identify what changed
    2. change_impact_report — graph impact, route/field/process blast radius, pre-commit workflow
    3. test_impact — testing impact and risk assessment
    4. check_stale_index — (optional) detect if the index is stale

    Returns a unified summary with risk, what changed, what can break, and what to test.
    """
    # Step 1+2: change_impact_report already calls detect_changes internally
    impact_report = change_impact_report(
        repo_root,
        duckdb_store,
        kuzu_store,
        scope=scope,
        base_ref=base_ref,
        max_symbols=max_symbols,
        target=target,
    )

    # Step 3: test_impact (uses suggest_tests_for_change internally)
    test_result = test_impact(
        repo_root,
        duckdb_store,
        kuzu_store,
        scope=scope,
        base_ref=base_ref,
    )

    # Step 4: stale index check (optional)
    stale_result = None
    if include_stale_check:
        try:
            stale_result = check_stale_index(repo_root, duckdb_store)
        except Exception:
            stale_result = None

    # Merge compact summaries
    impact_summary = impact_report.get("compact_summary", {}) if isinstance(impact_report, dict) else {}
    test_summary = test_result.get("compact_summary", {}) if isinstance(test_result, dict) else {}

    risk = str(impact_report.get("risk", "UNKNOWN") or "UNKNOWN") if isinstance(impact_report, dict) else "UNKNOWN"
    test_risk = str(test_result.get("risk", "") or "") if isinstance(test_result, dict) else ""
    stale_warnings = stale_result.get("warnings", []) if isinstance(stale_result, dict) else []

    # Elevate risk if tests indicate higher risk
    risk_adjustments = list(impact_report.get("risk_adjustments", [])) if isinstance(impact_report, dict) else []
    if test_risk and test_risk == "HIGH" and risk != "CRITICAL":
        risk = "HIGH"
        risk_adjustments.append("Test impact assessment raised overall risk to HIGH.")
    elif test_risk and test_risk == "CRITICAL":
        risk = "CRITICAL"
        risk_adjustments.append("Test impact assessment raised overall risk to CRITICAL.")

    all_warnings = (
        (impact_report.get("warnings", []) if isinstance(impact_report, dict) else [])
        + (test_result.get("warnings", []) if isinstance(test_result, dict) else [])
        + stale_warnings
    )

    return {
        "scope": scope,
        "base_ref": base_ref,
        "target": target,
        "risk": risk,
        "risk_adjustments": risk_adjustments,
        "impact_report": impact_report,
        "test_impact": test_result,
        "stale_index": stale_result,
        "what_changed": impact_report.get("what_changed", []) if isinstance(impact_report, dict) else [],
        "what_can_break": impact_report.get("what_can_break", []) if isinstance(impact_report, dict) else [],
        "what_to_test": (
            test_summary.get("top_files", [])
            or impact_report.get("what_to_test", [])
            if isinstance(impact_report, dict) else []
        ),
        "warnings": all_warnings,
        "compact_summary": {
            "scope": scope,
            "target": target,
            "risk": risk,
            "risk_adjustments": risk_adjustments,
            "changed_file_count": impact_summary.get("changed_file_count", 0),
            "changed_symbol_count": impact_summary.get("changed_symbol_count", 0),
            "test_count": test_summary.get("test_count", 0),
            "test_risk": test_risk,
            "stale_index": bool(stale_result.get("stale", False)) if isinstance(stale_result, dict) else False,
            "stale_file_count": stale_result.get("stale_file_count", 0) if isinstance(stale_result, dict) else 0,
            "top_changed_files": impact_summary.get("top_changed_files", []),
            "top_risk_files": impact_summary.get("top_risk_files", []),
            "top_tests": test_summary.get("top_files", []) or impact_summary.get("top_tests", []),
            "top_impacted": impact_summary.get("top_impacted", []),
            "changed_routes": impact_summary.get("changed_routes", []),
            "shape_mismatches": impact_summary.get("shape_mismatches", []),
            "affected_processes": impact_summary.get("affected_processes", []),
            "pre_commit_slices": impact_summary.get("pre_commit_slices", []),
            "commit_plan": impact_summary.get("commit_plan", []),
            "validation_plan": impact_summary.get("validation_plan", []),
            "field_blast_radius": impact_summary.get("field_blast_radius", []),
            "process_blast_radius": impact_summary.get("process_blast_radius", []),
            "follow_up_tools": impact_summary.get("follow_up_tools", []),
            "warnings": all_warnings,
        },
    }
