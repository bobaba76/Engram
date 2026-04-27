from __future__ import annotations

import hashlib
import re

from models.entity_models import ProcessClusterRecord, ProcessRecord, ProcessRelationshipRecord, ProcessSymbolMembershipRecord, SymbolRecord
from services.process_service import _entry_candidates, _flow_name
from storage.duckdb_store import DuckDBStore
from storage.kuzu_store import KuzuStore


def _symbol_qualified_name(symbol: SymbolRecord | dict[str, object]) -> str:
    if isinstance(symbol, dict):
        return str(symbol.get("qualified_name", ""))
    return symbol.qualified_name


def _symbol_name(symbol: SymbolRecord | dict[str, object]) -> str:
    if isinstance(symbol, dict):
        return str(symbol.get("name", ""))
    return symbol.name


def _module_for_symbol(symbols_by_file: dict[str, list[SymbolRecord] | list[dict[str, object]]], symbol_name: str) -> tuple[str, str]:
    for file_path, symbols in symbols_by_file.items():
        for symbol in symbols:
            if _symbol_qualified_name(symbol) == symbol_name or _symbol_name(symbol) == symbol_name:
                module = file_path.split("/", 1)[0] if "/" in file_path else file_path
                return module, file_path
    return "", ""


def _walk_call_paths(kuzu_store: KuzuStore, start: str, max_depth: int, max_flows: int) -> list[list[str]]:
    flows: list[list[str]] = []
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    while stack and len(flows) < max_flows:
        current, path = stack.pop()
        if len(path) - 1 >= max_depth:
            flows.append(path)
            continue
        callees = kuzu_store.edges_for_source(current, relation="CALLS")
        next_nodes = [str(edge.get("target", "")) for edge in callees if str(edge.get("target", "")) and str(edge.get("target", "")) not in path]
        if not next_nodes:
            flows.append(path)
            continue
        for node in reversed(next_nodes[:8]):
            stack.append((node, [*path, node]))
    return flows


def _process_id(entry_symbol: str, symbols: list[str]) -> str:
    digest = hashlib.sha1("|".join([entry_symbol, *symbols]).encode("utf-8")).hexdigest()[:16]
    return f"process:{digest}"


def _normalize_symbol_name(symbol_name: str) -> str:
    return symbol_name.split(".")[-1]


def _cluster_signature(flow: list[str]) -> str:
    reduced = [_normalize_symbol_name(symbol) for symbol in flow[:2]]
    if flow:
        reduced.append(_normalize_symbol_name(flow[-1]))
    return "|".join(reduced)


def _feature_hint(file_paths: set[str]) -> str:
    tokens: list[str] = []
    for file_path in sorted(file_paths):
        parts = [part for part in re.split(r"[/_.-]+", file_path) if part]
        for part in parts:
            lowered = part.lower()
            if lowered in {"frontend", "backend", "src", "components", "pages", "routers", "repositories", "tests"}:
                continue
            if lowered.endswith("test"):
                continue
            tokens.append(part)
    if not tokens:
        return ""
    ranked = sorted(tokens, key=lambda token: (-len(token), token.lower()))
    return ranked[0]


def _keywords(file_paths: set[str], flow: list[str]) -> list[str]:
    values = set()
    feature = _feature_hint(file_paths)
    if feature:
        values.add(feature)
    for symbol in flow:
        tail = _normalize_symbol_name(symbol)
        if len(tail) >= 4:
            values.add(tail)
    return sorted(values)[:8]


def _semantic_process_name(flow: list[str], module_name: str, file_paths: set[str]) -> str:
    feature = _feature_hint(file_paths)
    base = _flow_name(flow, module_name)
    if feature and feature.lower() not in base.lower():
        return f"{feature}: {base}"
    return base


def _cluster_id(signature: str) -> str:
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]
    return f"cluster:{digest}"


def _role_for_step(index: int, step_count: int) -> str:
    if index == 0:
        return "entry"
    if index == step_count - 1:
        return "terminal"
    return "intermediate"


def _cluster_name(records: list[ProcessRecord]) -> str:
    if not records:
        return "Process Cluster"
    names = [record.name for record in records if record.name]
    names.sort(key=lambda value: (-len(value), value))
    return names[0] if names else "Process Cluster"


def _cluster_records(process_records: list[ProcessRecord]) -> tuple[list[ProcessClusterRecord], list[ProcessSymbolMembershipRecord], list[ProcessRelationshipRecord]]:
    grouped: dict[str, list[ProcessRecord]] = {}
    process_to_cluster: dict[str, str] = {}
    memberships: list[ProcessSymbolMembershipRecord] = []
    relationships: list[ProcessRelationshipRecord] = []
    for record in process_records:
        signature = _cluster_signature([step.get("symbol", "") for step in record.step_list if step.get("symbol")])
        grouped.setdefault(signature, []).append(record)
    clusters: list[ProcessClusterRecord] = []
    for signature, records in grouped.items():
        cluster_id = _cluster_id(signature)
        module_tags = sorted({tag for record in records for tag in record.module_tags})
        community_tags = sorted({tag for record in records for tag in record.community_tags})
        file_paths = sorted({path for record in records for path in record.file_paths})
        representative = max(records, key=lambda record: (record.step_count, len(record.name), record.name))
        step_lists = [record.step_list for record in records if record.step_list]
        all_symbols = [step.get("symbol", "") for steps in step_lists for step in steps if step.get("symbol")]
        clusters.append(
            ProcessClusterRecord(
                cluster_id=cluster_id,
                name=_cluster_name(records),
                process_type=representative.process_type,
                canonical_entry_symbol=representative.entry_symbol,
                canonical_terminal_symbol=representative.terminal_symbol,
                process_count=len(records),
                avg_step_count=round(sum(record.step_count for record in records) / len(records), 2),
                module_tags=module_tags,
                community_tags=community_tags,
                file_paths=file_paths,
                keywords=sorted({symbol.split(".")[-1] for symbol in all_symbols if symbol})[:10],
            )
        )
        for record in records:
            process_to_cluster[record.process_id] = cluster_id
            for index, step in enumerate(record.step_list):
                symbol = str(step.get("symbol", ""))
                if not symbol:
                    continue
                memberships.append(
                    ProcessSymbolMembershipRecord(
                        cluster_id=cluster_id,
                        process_id=record.process_id,
                        symbol=symbol,
                        step_index=index + 1,
                        role=_role_for_step(index, len(record.step_list)),
                    )
                )
    seen_relationships: set[tuple[str, str, str, str]] = set()
    symbol_to_clusters: dict[str, set[str]] = {}
    for membership in memberships:
        symbol_to_clusters.setdefault(membership.symbol, set()).add(membership.cluster_id)
    for symbol, cluster_ids in symbol_to_clusters.items():
        ordered = sorted(cluster_ids)
        for index, source_cluster_id in enumerate(ordered):
            for target_cluster_id in ordered[index + 1:]:
                key = (source_cluster_id, target_cluster_id, "shares_symbol", symbol)
                if key in seen_relationships:
                    continue
                seen_relationships.add(key)
                relationships.append(
                    ProcessRelationshipRecord(
                        source_cluster_id=source_cluster_id,
                        target_cluster_id=target_cluster_id,
                        relation_type="shares_symbol",
                        shared_symbol=symbol,
                    )
                )
    return clusters, memberships, relationships


def build_process_records(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    symbols_by_file: dict[str, list[SymbolRecord] | list[dict[str, object]]],
    max_depth: int = 4,
    max_flows_per_target: int = 6,
) -> list[ProcessRecord]:
    process_records: list[ProcessRecord] = []
    seen_ids: set[str] = set()
    seen_clusters: set[str] = set()
    qualified_names = sorted(
        {
            _symbol_qualified_name(symbol)
            for symbols in symbols_by_file.values()
            for symbol in symbols
            if _symbol_qualified_name(symbol)
        }
    )
    for target in qualified_names:
        entrypoints = _entry_candidates(duckdb_store, kuzu_store, target)
        for entrypoint in entrypoints:
            for flow in _walk_call_paths(kuzu_store, entrypoint, max_depth=max_depth, max_flows=max_flows_per_target):
                if target not in flow and entrypoint != target:
                    flow = [entrypoint, *flow]
                if len(flow) < 2:
                    continue
                module_tags: set[str] = set()
                file_paths: set[str] = set()
                for node in flow:
                    module, file_path = _module_for_symbol(symbols_by_file, node)
                    if module:
                        module_tags.add(module)
                    if file_path:
                        file_paths.add(file_path)
                if not file_paths:
                    continue
                module_name = sorted(module_tags)[0] if module_tags else ""
                cluster_signature = _cluster_signature(flow)
                if cluster_signature in seen_clusters:
                    continue
                seen_clusters.add(cluster_signature)
                process_id = _process_id(entrypoint, flow)
                if process_id in seen_ids:
                    continue
                seen_ids.add(process_id)
                process_records.append(
                    ProcessRecord(
                        process_id=process_id,
                        name=_semantic_process_name(flow, module_name, file_paths),
                        process_type="entrypoint_call_path" if entrypoint != target else "call_path",
                        entry_symbol=entrypoint,
                        terminal_symbol=flow[-1] if flow else entrypoint,
                        step_count=len(flow),
                        step_list=[{"symbol": node, "step": index + 1} for index, node in enumerate(flow)],
                        module_tags=sorted(module_tags),
                        community_tags=sorted(module_tags),
                        file_paths=sorted(file_paths),
                    )
                )
    return process_records


def build_process_graph_records(
    duckdb_store: DuckDBStore,
    kuzu_store: KuzuStore,
    symbols_by_file: dict[str, list[SymbolRecord] | list[dict[str, object]]],
    max_depth: int = 4,
    max_flows_per_target: int = 6,
) -> tuple[list[ProcessRecord], list[ProcessClusterRecord], list[ProcessSymbolMembershipRecord], list[ProcessRelationshipRecord]]:
    process_records = build_process_records(
        duckdb_store,
        kuzu_store,
        symbols_by_file,
        max_depth=max_depth,
        max_flows_per_target=max_flows_per_target,
    )
    cluster_records, memberships, relationships = _cluster_records(process_records)
    return process_records, cluster_records, memberships, relationships
