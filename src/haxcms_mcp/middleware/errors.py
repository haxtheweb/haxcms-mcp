"""Error translation middleware (PLAN.md Section 2.2 step 6).

Translates ``HaxcmsMcpError`` raised anywhere below (tools, services, client) into a
FastMCP ``ToolError`` / ``ResourceError`` whose message is ``[CODE] message. hint``.
Any OTHER exception keeps fastmcp's handling; in per-caller HTTP mode the server runs with
``mask_error_details`` so those reach remote callers without internal detail.
"""

from __future__ import annotations

from typing import Any

import mcp_types
from fastmcp.exceptions import ResourceError, ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from haxcms_mcp.errors import HaxcmsMcpError


class ErrorTranslationMiddleware(Middleware):
    """Maps HaxcmsMcpError to the MCP tool-error format.

    fastmcp 4 masks exceptions raised inside tool bodies into
    ``ToolError("Error calling tool '<name>': <original message>")`` with the original
    exception attached as ``__cause__`` **before** middleware above it can see them
    (FastMCP.call_tool, server.py). We therefore handle both shapes: a bare
    HaxcmsMcpError (raised from middleware or with masking bypassed) and a masked
    ToolError whose cause is one.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[mcp_types.CallToolRequestParams],
        call_next: CallNext[mcp_types.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            return await call_next(context)
        except HaxcmsMcpError as exc:
            raise ToolError(exc.formatted) from exc
        except ToolError as exc:
            cause = exc.__cause__
            if isinstance(cause, HaxcmsMcpError):
                raise ToolError(cause.formatted) from cause
            raise

    async def on_read_resource(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        """Same for resources: with error masking on (per-caller HTTP mode) fastmcp would hide
        our actionable `[CODE] message. hint` text along with genuine internals."""
        try:
            return await call_next(context)
        except HaxcmsMcpError as exc:
            raise ResourceError(exc.formatted) from exc
        except ResourceError as exc:
            cause = exc.__cause__
            if isinstance(cause, HaxcmsMcpError):
                raise ResourceError(cause.formatted) from cause
            raise
