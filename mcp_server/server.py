from __future__ import annotations

import asyncio
import inspect
import json
import logging
import sys
from functools import wraps
from typing import Any, Callable

from mcp_server.formatters import enrich_payload
from mcp_server.tools import ToolRegistry

logger = logging.getLogger(__name__)

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
            async def wrapped_handler(*args: Any, **kwargs: Any) -> str:
                """Return a single JSON string.

                Returning a plain string (instead of a dict) keeps FastMCP from
                emitting BOTH serialized-JSON text content AND structuredContent
                for every result — that duplication roughly doubled every tool
                response's token payload. The model reads the JSON text either
                way; nothing downstream consumes structuredContent.
                """

                def _run() -> str:
                    try:
                        payload = enrich_payload(handler(*args, **kwargs))
                    except Exception as exc:
                        logger.exception("MCP tool %s raised an exception", name)
                        payload = enrich_payload({
                            "status": "error",
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                            "summary_text": f"Tool {name!r} failed: {exc}",
                            "highlights": [f"Tool {name!r} failed: {exc}"],
                        })
                    return json.dumps(payload, ensure_ascii=False)

                return await asyncio.to_thread(_run)

            wrapped_handler.__signature__ = handler_signature
            # FastMCP uses __doc__ as the tool description; @wraps copies the
            # handler's (empty) docstring, so explicitly set it from the
            # description passed to register_tool.
            if description:
                wrapped_handler.__doc__ = description

            # structured_output=False suppresses FastMCP's auto-generated
            # outputSchema. The handlers are annotated -> dict[str, object],
            # which by default makes FastMCP emit an outputSchema requiring a
            # dict return and then validate against it. But wrapped_handler
            # intentionally returns a JSON-encoded str (see comment above) to
            # avoid the structuredContent duplication that roughly doubles
            # every response's token payload. Without this flag every tool
            # call fails pydantic validation ("Input should be a valid
            # dictionary") and the client re-injects the full tool schema
            # (~25K tokens) back into context on each failure.
            self._fastmcp.tool(name=name, structured_output=False)(wrapped_handler)

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
