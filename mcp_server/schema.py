from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Union, get_args, get_origin


@dataclass(slots=True)
class ToolDefinition:
    name: str
    handler: Callable[..., Any]
    description: str = ""
    input_schema: dict[str, Any] | None = None


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation in {dict, dict[str, object], dict[str, Any]}:
        return {"type": "object"}
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is list:
        return {"type": "array", "items": _annotation_to_schema(args[0]) if args else {}}
    if origin is dict:
        return {"type": "object"}
    if origin is Union:
        non_none = [arg for arg in args if arg is not type(None)]
        has_none = len(non_none) != len(args)
        if len(non_none) == 1:
            inner = _annotation_to_schema(non_none[0])
            if has_none:
                inner = {**inner, "nullable": True}
            return inner
        if has_none and len(non_none) > 1:
            return {"anyOf": [_annotation_to_schema(arg) for arg in non_none], "nullable": True}
    if str(annotation).startswith("typing.Literal"):
        return {"type": "string", "enum": list(args)}
    return {"type": "string"}


def _description_for_parameter(handler: Callable[..., Any], name: str) -> str:
    descriptions = getattr(handler, "__mcp_param_descriptions__", {})
    if isinstance(descriptions, dict):
        explicit = str(descriptions.get(name, "") or "")
        if explicit:
            return explicit
    common = {
        "target": "Primary identifier: file path, symbol name, qualified name, symbol UID, or tool-specific value (accepted as alias by all tools).",
        "question": "Natural-language codebase question to investigate.",
        "task": "Natural-language search task describing what you are looking for.",
        "feature": "Feature, workflow, route, table, or domain term to map.",
        "query": "Cypher query string for graph_query, or search text for other tools. 'target' is accepted as an alias.",
        "repo": "Optional indexed repository name or path. Leave blank to use the selected repo.",
        "file_path": "Optional repo-relative file path used to disambiguate a symbol. 'target' is accepted as an alias by get_file_dependencies.",
        "kind": "Optional symbol kind such as function, class, method, route, or component.",
        "symbol_uid": "Optional exact symbol UID in kind:file_path:qualified_name form.",
        "symbol_name": "Symbol name to rename or search for. 'target' is accepted as an alias.",
        "new_name": "New name for a rename preview.",
        "limit": "Maximum number of items to return.",
        "max_matches": "Maximum number of symbol matches to return.",
        "max_depth": "Maximum graph traversal depth.",
        "neighborhood_depth": "Depth of graph neighborhood expansion (1 = direct neighbors only).",
        "view": "Optional view mode to control output formatting.",
        "direction": "Impact direction: upstream for callers/dependents, downstream for callees/dependencies.",
        "relation": "Graph relation type to follow (e.g. CALLS, IMPORTS, REFERENCES). Leave empty to check all relations.",
        "file_pattern": "Optional glob pattern to filter results by file path (e.g. '*.py', 'backend/**').",
        "scope": "Git change scope: unstaged, staged, all, or compare.",
        "base_ref": "Optional base git ref for compare scope.",
        "run_id": "Index run identifier to fetch metrics for.",
        "project_root": "Repository root path to reindex. Leave blank to use the selected repo.",
        "run_mode": "Index mode: 'incremental' (changed files only) or 'full' (complete rebuild).",
        "background": "If true, run the reindex in the background and return a job ID immediately.",
        "job_id": "Background reindex job ID to poll status for.",
        "group_name": "Name of a repo group for multi-repo analysis.",
        "group_path": "Optional path for a new repo group.",
        "hierarchy_path": "Dot-separated path identifying a repo within a group hierarchy.",
        "community_id": "Identifier of a detected functional community.",
        "min_size": "Minimum community size for community detection.",
        "max_size": "Maximum community size for community detection.",
        "algorithm": "Community detection algorithm: 'label_propagation' or 'louvain'.",
        "similarity_threshold": "Minimum similarity score (0-1) for similar function results.",
        "stack_trace": "Full Python or TypeScript/JavaScript stack trace to explain. 'target' is accepted as an alias.",
        "field": "Field or property name to trace. 'target' is accepted as an alias by field_impact and trace_data_flow.",
        "changed_files": "Optional explicit list of changed file paths instead of git diff.",
        "max_snippets": "Maximum number of source snippets to include in diff context.",
        "edge_limit": "Maximum number of edges in a unified graph.",
        "poll_interval": "Seconds between filesystem polls for realtime indexing.",
        "debounce": "Seconds to wait after last change before triggering a reindex.",
    }
    return common.get(name, "")


def input_schema_for(handler: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(handler)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        if parameter.kind in {inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL}:
            continue
        schema = _annotation_to_schema(parameter.annotation)
        description = _description_for_parameter(handler, name)
        if description:
            schema["description"] = description
        if parameter.default is not inspect.Parameter.empty:
            schema["default"] = parameter.default
        else:
            required.append(name)
        properties[name] = schema
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def describe_tool(name: str, handler: Callable[..., Any], description: str = "") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        handler=handler,
        description=description or inspect.getdoc(handler) or "",
        input_schema=input_schema_for(handler),
    )
