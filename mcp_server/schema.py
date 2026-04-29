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
        if len(non_none) == 1:
            return _annotation_to_schema(non_none[0])
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
        "target": "File path, symbol name, qualified name, or symbol UID.",
        "question": "Natural-language codebase question to investigate.",
        "feature": "Feature, workflow, route, table, or domain term to map.",
        "query": "Search text or symbol query.",
        "repo": "Optional indexed repository name or path. Leave blank to use the selected repo.",
        "file_path": "Optional repo-relative file path used to disambiguate a symbol.",
        "kind": "Optional symbol kind such as function, class, method, route, or component.",
        "symbol_uid": "Optional exact symbol UID in kind:file_path:qualified_name form.",
        "limit": "Maximum number of items to return.",
        "max_depth": "Maximum graph traversal depth.",
        "scope": "Git change scope: unstaged, staged, all, or compare.",
        "base_ref": "Optional base git ref for compare scope.",
        "direction": "Impact direction: upstream for callers/dependents, downstream for callees/dependencies.",
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
