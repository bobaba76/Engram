from __future__ import annotations

import inspect
import json
import sys
from functools import wraps
from typing import Any, Callable

from mcp_server.formatters import enrich_payload
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

    def register_tool(self, name: str, handler: Callable[..., Any], description: str = "") -> None:
        self.registry.register(name, handler, description=description)
        if self._fastmcp is not None:
            handler_signature = inspect.signature(handler)

            @wraps(handler)
            def wrapped_handler(*args: Any, **kwargs: Any) -> Any:
                return enrich_payload(handler(*args, **kwargs))

            wrapped_handler.__signature__ = handler_signature

            self._fastmcp.tool(name=name)(wrapped_handler)

    def describe(self) -> dict[str, object]:
        return {
            "transport": "stdio" if self._fastmcp is not None else "fallback",
            "tools": self.registry.describe_tools(),
        }

    def run(self) -> None:
        if self._fastmcp is not None:
            self._fastmcp.run(transport="stdio")
            return
        sys.stderr.write(json.dumps(self.describe()) + "\n")
