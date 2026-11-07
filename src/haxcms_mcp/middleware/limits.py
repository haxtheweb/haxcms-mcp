"""Argument size cap (security audit): bounds the HTML and text a single tool call carries.

Every content-bearing argument (`html`, `inner_html`, `text`, `*_html`, `content_html`,
`text_or_html`) is measured as UTF-8 before the tool runs, and a call over
`HAXCMS_MCP_MAX_HTML_BYTES` (default 2 MB) is refused with INVALID_ARGUMENT. HAXcms has its
own body limits; this keeps a runaway agent from parsing and PATCHing arbitrarily large
documents through this server's lxml pipeline first.
"""

from __future__ import annotations

import mcp_types
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

CONTENT_ARGUMENT_NAMES = frozenset({"html", "inner_html", "text", "content_html", "text_or_html"})
CONTENT_ARGUMENT_SUFFIXES = ("_html",)


def is_content_argument(name: str) -> bool:
    return name in CONTENT_ARGUMENT_NAMES or name.endswith(CONTENT_ARGUMENT_SUFFIXES)


def check_argument_sizes(arguments: dict[str, object] | None, max_bytes: int) -> None:
    """Raise INVALID_ARGUMENT when a content argument exceeds `max_bytes` (UTF-8)."""
    for name, value in (arguments or {}).items():
        if not isinstance(value, str) or not is_content_argument(name):
            continue
        size = len(value.encode("utf-8", errors="surrogatepass"))
        if size > max_bytes:
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                f"{name} is {size} bytes, over the {max_bytes}-byte limit",
                hint="split the content across several pages or blocks, or raise "
                "HAXCMS_MCP_MAX_HTML_BYTES on the server",
                details={"argument": name, "bytes": size, "max_bytes": max_bytes},
            )


class ArgumentSizeMiddleware(Middleware):
    """Refuses tool calls whose content arguments exceed `settings.max_html_bytes`."""

    def __init__(self, settings: Settings) -> None:
        self.max_bytes = settings.max_html_bytes

    async def on_call_tool(
        self,
        context: MiddlewareContext[mcp_types.CallToolRequestParams],
        call_next: CallNext[mcp_types.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            check_argument_sizes(context.message.arguments, self.max_bytes)
        except HaxcmsMcpError as exc:
            # outside ErrorTranslationMiddleware, so render the standard message here
            raise ToolError(exc.formatted) from exc
        return await call_next(context)
