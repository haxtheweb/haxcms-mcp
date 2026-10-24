"""Read-Only Mode gate (PLAN.md Sections 2.2 step 2 and 5).

When ``settings.read_only`` is set, every tool that is not annotated ``read_only_hint=True``
is refused with a READ_ONLY error before its function runs.
"""

from __future__ import annotations

import mcp_types
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from haxcms_mcp.config import Settings


class ReadOnlyMiddleware(Middleware):
    """Blocks non-read-only tool calls when Read-Only Mode is active."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def on_call_tool(
        self,
        context: MiddlewareContext[mcp_types.CallToolRequestParams],
        call_next: CallNext[mcp_types.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if not self.settings.read_only:
            return await call_next(context)

        params = context.message
        is_read_only = False
        fctx = context.fastmcp_context
        if fctx is not None and fctx.fastmcp is not None:
            tool = await fctx.fastmcp.get_tool(params.name)
            annotations = getattr(tool, "annotations", None)
            is_read_only = bool(annotations and annotations.read_only_hint)

        if not is_read_only:
            raise ToolError(
                "[READ_ONLY] Read-Only Mode is active; this tool would change state "
                f"on the Instance and was refused ({params.name}). "
                "Set HAXCMS_MCP_READ_ONLY=false to allow writes"
            )
        return await call_next(context)
