from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore


def get_file_summary(duckdb_store: DuckDBStore, target: str) -> dict[str, object]:
    symbols = duckdb_store.symbols.fetch_for_file(target)
    chunks = duckdb_store.chunks.fetch_for_target(target, limit=1000)
    findings = duckdb_store.reviews.fetch_findings_for_target(target)
    return {
        "target": target,
        "symbol_count": len(symbols),
        "chunk_count": len(chunks),
        "finding_count": len(findings),
        "compact_summary": {
            "target": target,
            "symbol_count": len(symbols),
            "finding_count": len(findings),
            "top_symbols": [symbol["qualified_name"] for symbol in symbols[:5]],
            "top_findings": [finding["title"] for finding in findings[:3]],
        },
        "symbols": [
            {
                "name": symbol["name"],
                "qualified_name": symbol["qualified_name"],
                "kind": symbol["kind"],
                "start_line": symbol["start_line"],
                "end_line": symbol["end_line"],
            }
            for symbol in symbols
        ],
        "recent_findings": [
            {
                "title": finding["title"],
                "severity": finding["severity"],
                "category": finding["category"],
                "line_range": [finding["start_line"], finding["end_line"]],
            }
            for finding in findings[:5]
        ],
    }
