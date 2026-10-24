"""Tool-call logging middleware (PLAN.md T0.5).

Logs every tool call at INFO with name, duration, and outcome to the stderr logger tree.
Never logs arguments (they may contain credentials) at INFO; DEBUG includes argument keys only.
"""

from __future__ import annotations

import time

import mcp_types
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from haxcms_mcp.logging import get_logger

logger = get_logger("middleware")


class ToolLoggingMiddleware(Middleware):
    """Logs tool name, duration (ms), and outcome for every call."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mcp_types.CallToolRequestParams],
        call_next: CallNext[mcp_types.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        params = context.message
        started = time.perf_counter()
        logger.debug("tool %s args=%s", params.name, sorted((params.arguments or {}).keys()))
        try:
            result = await call_next(context)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info("tool %s failed in %.0fms: %s", params.name, elapsed_ms, exc)
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info("tool %s ok in %.0fms", params.name, elapsed_ms)
        return result
