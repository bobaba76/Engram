from __future__ import annotations

from collections import defaultdict
from typing import Any


def diversify_results(results: list[dict[str, Any]], limit: int, per_file_limit: int = 3) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    per_file_counts: dict[str, int] = defaultdict(int)
    overflow: list[dict[str, Any]] = []
    for result in results:
        file_path = str(result.get("file_path", ""))
        if per_file_counts[file_path] < per_file_limit:
            selected.append(result)
            per_file_counts[file_path] += 1
        else:
            overflow.append(result)
        if len(selected) >= limit:
            return selected
    return [*selected, *overflow][:limit]


def rerank_with_diversity(task: str, results: list[dict[str, Any]], limit: int, base_reranker) -> list[dict[str, Any]]:
    reranked = base_reranker(task, results, limit=max(limit * 3, limit))
    return diversify_results(reranked, limit=limit)
