from __future__ import annotations

import json
import sys
from typing import Any, Callable

from mcp_server.tools import ToolRegistry

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None


class MCPServer:
    def __init__(self, name: str = "Coder") -> None:
        self.registry = ToolRegistry()
        self.name = name
        self._fastmcp = FastMCP(name, json_response=True) if FastMCP is not None else None

    def register_tool(self, name: str, handler: Callable[..., Any]) -> None:
        self.registry.register(name, handler)
        if self._fastmcp is not None:
            self._fastmcp.tool(name=name)(handler)

    def describe(self) -> dict[str, object]:
        return {
            "transport": "stdio" if self._fastmcp is not None else "fallback",
            "tools": self.registry.list_tools(),
        }

    def run(self) -> None:
        if self._fastmcp is not None:
            self._fastmcp.run(transport="stdio")
            return
        sys.stderr.write(json.dumps(self.describe()) + "\n")
