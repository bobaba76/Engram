from typing import Any

from mcp_server.formatters import format_payload


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, name: str, handler: Any) -> None:
        self._tools[name] = handler

    def list_tools(self) -> list[str]:
        return sorted(self._tools)

    def call(self, name: str, **kwargs: Any) -> str:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        payload = self._tools[name](**kwargs)
        return format_payload(payload)
