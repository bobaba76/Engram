from __future__ import annotations

from typing import Any


def edges_for_target_limited(kuzu_store: Any, target: str, relation: str | None = None, limit: int | None = None) -> list[dict[str, object]]:
    try:
        return list(kuzu_store.edges_for_target(target, relation=relation, limit=limit))
    except TypeError:
        edges = list(kuzu_store.edges_for_target(target, relation=relation))
        return edges[:limit] if limit is not None else edges


def edges_for_source_limited(kuzu_store: Any, source: str, relation: str | None = None, limit: int | None = None) -> list[dict[str, object]]:
    try:
        return list(kuzu_store.edges_for_source(source, relation=relation, limit=limit))
    except TypeError:
        edges = list(kuzu_store.edges_for_source(source, relation=relation))
        return edges[:limit] if limit is not None else edges
