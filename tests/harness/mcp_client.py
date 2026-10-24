"""Test helpers for driving the MCP server.

`McpTestClient` wraps a fastmcp in-memory Client with conveniences used across the suites.
Real subprocess transports (stdio + HTTP) live in `tests/harness/mcp_process.py` (Phase 9).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError


class McpTestClient:
    """In-memory MCP client bound to a FastMCP app."""

    def __init__(self, server: FastMCP, client: Client) -> None:
        self.server = server
        self.client = client

    async def list_tool_names(self) -> list[str]:
        tools = await self.client.list_tools()
        return [t.name for t in tools]

    async def call(self, name: str, /, **arguments: Any) -> Any:
        """Call a tool and return its structured data; fails the test on ToolError.

        `name` is positional-only so tools may themselves take a `name` argument.
        """
        result = await self.client.call_tool(name, arguments)
        return result.data

    async def call_error(self, name: str, /, **arguments: Any) -> str:
        """Call a tool expecting a ToolError; return the error message."""
        with pytest.raises(ToolError) as excinfo:
            await self.client.call_tool(name, arguments)
        return str(excinfo.value)

    async def read_resource(self, uri: str) -> Any:
        contents = await self.client.read_resource(uri)
        first = contents[0] if isinstance(contents, list | tuple) else contents
        return getattr(first, "text", first)
