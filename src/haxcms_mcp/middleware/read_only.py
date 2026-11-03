"""Read-Only Mode gate and the instance MCP policy (PLAN.md Sections 2.2 step 2 and 5).

A tool that is not annotated ``read_only_hint=True`` is refused with READ_ONLY before its
function runs when either `HAXCMS_MCP_READ_ONLY` is set or the HAXcms instance publishes
`mcp.readOnly: true`. When the instance publishes `mcp.enabled: false`, every tool except
`get_server_info` (and every resource) is refused with MCP_DISABLED (policy.py).
"""

from __future__ import annotations

from typing import Any

import mcp_types
from fastmcp.exceptions import ResourceError, ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from haxcms_mcp.config import Settings
from haxcms_mcp.policy import InstancePolicy, PolicyChecker

# answers even when the instance has MCP turned off, so an operator can see why
POLICY_EXEMPT_TOOLS = frozenset({"get_server_info"})

MCP_DISABLED_MESSAGE = (
    "[MCP_DISABLED] this HAXcms instance has MCP turned off (config.mcp.enabled is false), "
    "so this server will not operate it. The instance's operator can enable it in the "
    "HAXcms config (mcp.enabled: true)"
)


class ReadOnlyMiddleware(Middleware):
    """Blocks non-read-only tool calls in Read-Only Mode, and everything when MCP is off."""

    def __init__(self, settings: Settings, policy: PolicyChecker | None = None) -> None:
        self.settings = settings
        self.policy = policy

    async def _policy(self) -> InstancePolicy | None:
        if self.policy is None or self.settings.no_auth:
            return None
        return await self.policy.current()

    async def on_call_tool(
        self,
        context: MiddlewareContext[mcp_types.CallToolRequestParams],
        call_next: CallNext[mcp_types.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        params = context.message
        policy = None if params.name in POLICY_EXEMPT_TOOLS else await self._policy()
        if policy is not None and policy.disabled:
            raise ToolError(MCP_DISABLED_MESSAGE)

        instance_read_only = policy is not None and policy.forces_read_only
        if not (self.settings.read_only or instance_read_only):
            return await call_next(context)

        is_read_only = False
        fctx = context.fastmcp_context
        if fctx is not None and fctx.fastmcp is not None:
            tool = await fctx.fastmcp.get_tool(params.name)
            annotations = getattr(tool, "annotations", None)
            is_read_only = bool(annotations and annotations.read_only_hint)

        if not is_read_only:
            if self.settings.read_only:
                why = "Set HAXCMS_MCP_READ_ONLY=false to allow writes"
            else:
                why = (
                    "the HAXcms instance allows MCP read-only (config.mcp.readOnly); its "
                    "operator can set mcp.readOnly: false to allow writes"
                )
            raise ToolError(
                "[READ_ONLY] Read-Only Mode is active; this tool would change state "
                f"on the Instance and was refused ({params.name}). {why}"
            )
        return await call_next(context)

    async def on_read_resource(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        policy = await self._policy()
        if policy is not None and policy.disabled:
            raise ResourceError(MCP_DISABLED_MESSAGE)
        return await call_next(context)
