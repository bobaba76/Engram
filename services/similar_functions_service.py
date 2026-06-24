"""Find functions with similar signatures or behavior across the codebase.

Uses a combination of:
- Parameter count and type matching
- Return type matching
- Function name similarity (token-based)
- Call target overlap (do they call the same functions?)
"""
from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from services.graph_edge_utils import edges_for_source_limited

if TYPE_CHECKING:
    from storage.duckdb_store import DuckDBStore
    from storage.kuzu_store import KuzuStore


def _tokenize_name(name: str) -> set[str]:
    """Split a function name into lowercase tokens."""
    parts = re.split(r"[._\-](?=[A-Z])|[._\-]|(?<=[a-z])(?=[A-Z])", name)
    return {p.lower() for p in parts if len(p) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _parse_param_count(signature: str) -> int:
    """Extract parameter count from a signature string."""
    if not signature:
        return 0
    match = re.search(r"\(([^)]*)\)", signature)
    if not match:
        return 0
    params = match.group(1).strip()
    if not params:
        return 0
    return len([p for p in params.split(",") if p.strip()])


def _parse_return_type(signature: str) -> str:
    """Extract return type from a signature string."""
    if not signature:
        return ""
    if "->" in signature:
        return signature.split("->")[-1].strip().split("[")[0].strip()
    if ":" in signature and ")" in signature:
        after_paren = signature.split(")")[-1].strip()
        if after_paren.startswith(":"):
            return after_paren[1:].strip().split("[")[0].strip()
    return ""


def _get_callees(kuzu_store: KuzuStore, qualified_name: str, limit: int = 20) -> set[str]:
    """Get the set of call targets for a symbol."""
    edges = edges_for_source_limited(kuzu_store, qualified_name, relation="CALLS", limit=limit)
    return {str(edge.get("target", "")) for edge in edges if str(edge.get("target", ""))}


def find_similar_functions(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    target: str,
    limit: int = 10,
    similarity_threshold: float = 0.3,
) -> dict[str, object]:
    """Find functions similar to the target by signature and behavior.

    Similarity is computed from:
    - Name token overlap (Jaccard)
    - Parameter count proximity
    - Return type match
    - Call target overlap (do they call similar functions?)
    """
    from services.symbol_resolution_service import resolve_candidates

    candidates = resolve_candidates(duckdb_store, target=target, limit=1)
    if not candidates:
        return {
            "status": "not_found",
            "target": target,
            "similar_functions": [],
            "compact_summary": {"status": "not_found", "target": target},
        }

    symbol = candidates[0].get("symbol", {}) if isinstance(candidates[0], dict) else {}
    target_qn = str(symbol.get("qualified_name", "") or target)
    target_name = str(symbol.get("name", "") or target)
    target_sig = str(symbol.get("signature", "") or "")
    target_kind = str(symbol.get("kind", "") or "")

    target_tokens = _tokenize_name(target_name)
    target_param_count = _parse_param_count(target_sig)
    target_return = _parse_return_type(target_sig)
    target_callees = _get_callees(kuzu_store, target_qn)

    # Fetch all functions/methods from DuckDB
    all_symbols = duckdb_store.execute(
        """
        SELECT qualified_name, name, kind, signature, file_path
        FROM symbols
        WHERE kind IN ('function', 'method')
        ORDER BY qualified_name
        LIMIT 5000
        """
    ).fetchall()

    scored: list[dict[str, object]] = []
    for row in all_symbols:
        qn = str(row[0] or "")
        name = str(row[1] or "")
        kind = str(row[2] or "")
        sig = str(row[3] or "")
        file_path = str(row[4] or "")

        if qn == target_qn:
            continue

        # Name token similarity
        name_tokens = _tokenize_name(name)
        name_sim = _jaccard(target_tokens, name_tokens)

        # Param count similarity
        param_count = _parse_param_count(sig)
        if target_param_count == 0 and param_count == 0:
            param_sim = 1.0
        elif target_param_count == 0 or param_count == 0:
            param_sim = 0.0
        else:
            param_sim = 1.0 - abs(target_param_count - param_count) / max(target_param_count, param_count)

        # Return type similarity
        ret_type = _parse_return_type(sig)
        ret_sim = 1.0 if target_return and ret_type and target_return == ret_type else 0.0

        # Call target overlap
        callees = _get_callees(kuzu_store, qn)
        call_sim = _jaccard(target_callees, callees) if target_callees or callees else 0.0

        # Weighted score
        score = name_sim * 0.35 + param_sim * 0.25 + ret_sim * 0.15 + call_sim * 0.25

        if score >= similarity_threshold:
            scored.append({
                "qualified_name": qn,
                "name": name,
                "kind": kind,
                "file_path": file_path,
                "signature": sig,
                "similarity": round(score, 3),
                "similarity_breakdown": {
                    "name": round(name_sim, 3),
                    "params": round(param_sim, 3),
                    "return_type": round(ret_sim, 3),
                    "call_targets": round(call_sim, 3),
                },
            })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    top = scored[:limit]

    return {
        "status": "ok",
        "target": target,
        "target_symbol": {
            "qualified_name": target_qn,
            "name": target_name,
            "kind": target_kind,
            "signature": target_sig,
        },
        "similar_functions": top,
        "similar_count": len(scored),
        "compact_summary": {
            "status": "ok",
            "target": target_name,
            "similar_count": len(scored),
            "top_matches": [
                {"name": s["name"], "file": s["file_path"], "similarity": s["similarity"]}
                for s in top[:5]
            ],
        },
        "summary_text": f"Found {len(scored)} similar functions to {target_name}. Top match: {top[0]['name']} ({top[0]['similarity']})" if top else f"No similar functions found for {target_name}.",
    }
