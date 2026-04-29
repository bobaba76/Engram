from typing import Any

from mcp_server.formatters import format_payload
from mcp_server.schema import ToolDefinition, describe_tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, name: str, handler: Any, description: str = "") -> ToolDefinition:
        self._tools[name] = handler
        definition = describe_tool(name, handler, description=description)
        self._definitions[name] = definition
        return definition

    def list_tools(self) -> list[str]:
        return sorted(self._tools)

    def describe_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": definition.name,
                "description": definition.description,
                "inputSchema": definition.input_schema or {},
            }
            for definition in sorted(self._definitions.values(), key=lambda item: item.name)
        ]

    def call(self, name: str, **kwargs: Any) -> str:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        payload = self._tools[name](**kwargs)
        return format_payload(payload)
