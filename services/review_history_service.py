from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
 
 
def get_review_history(duckdb_store: DuckDBStore, target: str) -> dict[str, object]:
    matched = duckdb_store.reviews.fetch_findings_for_target(target)
    analyses = duckdb_store.reviews.fetch_agent_analyses_for_target(target)
    history = {
        "target": target,
        "findings": matched,
        "agent_analyses": analyses,
        "compact_findings": [
            {
                "title": finding["title"],
                "severity": finding["severity"],
                "category": finding["category"],
                "line_range": [finding["start_line"], finding["end_line"]],
            }
            for finding in matched[:5]
        ],
        "compact_analyses": [
            {
                "agent_type": analysis["agent_type"],
                "model_name": analysis["model_name"],
                "summary": analysis["summary"],
            }
            for analysis in analyses[:5]
        ],
    }
    return history
