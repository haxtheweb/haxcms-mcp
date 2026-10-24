"""Session Tools: login, logout, whoami, and the finished get_server_info (PLAN Phase 1 T1.7)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from haxcms_mcp import __version__
from haxcms_mcp.client import HaxcmsClient, system_api
from haxcms_mcp.client.auth import ACCESS_TOKEN_TTL_S
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import HaxcmsMcpError
from haxcms_mcp.tools._common import tool_annotations


def _budget_stats(client: HaxcmsClient) -> dict[str, Any]:
    stats = client.budget.stats
    return {
        "tokens": round(stats.tokens, 2),
        "waits": stats.waits,
        "denials": stats.denials,
    }


def register_auth_tools(mcp: FastMCP, settings: Settings, client: HaxcmsClient) -> None:
    """Register the four session tools on the FastMCP app."""

    @mcp.tool(
        annotations=tool_annotations("Login", read_only=False, destructive=False),
    )
    async def login(username: str, password: str) -> dict[str, Any]:
        """Log in to the HAXcms instance and start an authenticated session.

        Replaces any environment-configured credentials for this process. Call it when other
        tools fail with AUTH_REQUIRED or AUTH_FAILED. Returns the user and the access-token
        lifetime; failures surface as AUTH_FAILED (bad credentials) or RATE_LIMITED (too many
        failed attempts — wait out the retry-after window).
        """
        await client.auth.login(username, password)
        return {"user": username, "expires_in_s": ACCESS_TOKEN_TTL_S}

    @mcp.tool(
        annotations=tool_annotations("Logout", read_only=False, destructive=False),
    )
    async def logout() -> dict[str, Any]:
        """Log out of the HAXcms instance and discard all cached tokens.

        After logout, authenticated tools fail with AUTH_REQUIRED until login is called again —
        even when environment credentials are configured.
        """
        await client.auth.logout()
        return {"status": "loggedout"}

    @mcp.tool(
        annotations=tool_annotations("Who am I", read_only=True),
    )
    async def whoami() -> dict[str, Any]:
        """Validate the current session and report who is logged in.

        Returns the user, access-token age in seconds, outbound-budget statistics, the
        Read-Only Mode flag, and the Default Site. With environment credentials configured but
        no session yet, it logs in automatically. Fails with AUTH_REQUIRED after an explicit
        logout or when no credentials are available.
        """
        if settings.no_auth:
            return {
                "user": settings.username,
                "authenticated": None,
                "no_auth": True,
                "token_age_s": None,
                "budget": _budget_stats(client),
                "read_only": settings.read_only,
                "default_site": settings.default_site,
            }
        await client.auth.ensure_access()
        session_data = await system_api.session(client)
        age = client.auth.token_age_s
        return {
            "user": client.auth.username,
            "authenticated": True,
            "session": session_data,
            "token_age_s": round(age, 1) if age is not None else None,
            "budget": _budget_stats(client),
            "read_only": settings.read_only,
            "default_site": settings.default_site,
        }

    @mcp.tool(
        annotations=tool_annotations("Server info", read_only=True),
    )
    async def get_server_info() -> dict[str, Any]:
        """Return identity and configuration of this HAXcms MCP server.

        Reports which HAXcms instance the server talks to, whether Read-Only Mode is active,
        and — best effort — the instance's own version and status diagnostics (failures appear
        as `version_error` / `status_error` instead of failing the call).
        """
        info: dict[str, Any] = {
            "name": "haxcms-mcp",
            "version": __version__,
            "base_url": settings.base_url,
            "read_only": settings.read_only,
            "transport": settings.transport,
            "no_auth": settings.no_auth,
        }
        haxcms_info: dict[str, Any] = {}
        try:
            haxcms_info["version"] = await system_api.version(client)
        except HaxcmsMcpError as exc:
            haxcms_info["version_error"] = exc.formatted
        try:
            haxcms_info["status"] = await system_api.status(client)
        except HaxcmsMcpError as exc:
            haxcms_info["status_error"] = exc.formatted
        info["haxcms"] = haxcms_info
        return info
