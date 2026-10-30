"""FastMCP application assembly for the HAXcms MCP server.

`build_server(settings)` creates the FastMCP app and registers every tool, resource, prompt,
and middleware. Later Phases add their registrations here (PLAN.md Section 2.1).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.compat import CompatChecker
from haxcms_mcp.config import Settings
from haxcms_mcp.http_auth import PrincipalMiddleware, build_auth_provider
from haxcms_mcp.middleware import (
    ErrorTranslationMiddleware,
    ReadOnlyMiddleware,
    ToolLoggingMiddleware,
)
from haxcms_mcp.policy import PolicyChecker
from haxcms_mcp.prompts.journeys import register_prompts
from haxcms_mcp.resources.catalog import register_catalog_resources
from haxcms_mcp.resources.sites import register_site_resources
from haxcms_mcp.services import output_store
from haxcms_mcp.services.catalog.service import CatalogService
from haxcms_mcp.tools.auth import register_auth_tools
from haxcms_mcp.tools.blocks_typed import register_typed_block_tools
from haxcms_mcp.tools.content import register_content_tools
from haxcms_mcp.tools.converters import register_converter_tools
from haxcms_mcp.tools.exports import register_export_tools
from haxcms_mcp.tools.files import register_files_tools
from haxcms_mcp.tools.imports import register_import_tools
from haxcms_mcp.tools.outline import register_outline_tools
from haxcms_mcp.tools.pages import register_pages_tools
from haxcms_mcp.tools.settings import register_settings_tools
from haxcms_mcp.tools.sites import register_sites_tools


def _register_downloads(mcp: FastMCP, settings: Settings) -> None:
    """`GET /downloads/<token>`: per-caller results, by signed short-lived link only.

    The token is the capability (HMAC-signed path + expiry, see services/output_store.py), so
    the route needs no bearer: an MCP client can hand the link to a browser.
    """

    @mcp.custom_route(output_store.DOWNLOAD_PREFIX + "{token}", methods=["GET"])
    async def download(request: Request) -> Response:
        path = output_store.resolve_download(settings, str(request.path_params.get("token", "")))
        if path is None:
            return JSONResponse({"error": "not_found_or_expired"}, status_code=404)
        return FileResponse(
            path,
            filename=path.name,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )


def build_server(settings: Settings) -> FastMCP:
    """Create and configure the FastMCP application for one Instance."""
    client = HaxcmsClient(settings)
    compat = CompatChecker(client)
    policy = PolicyChecker(client)

    @asynccontextmanager
    async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
        """Startup spec check (best effort, never blocks) and graceful shutdown (T9.4):
        the httpx client dies with the server session."""
        check = asyncio.create_task(compat.result(), name="haxcms-spec-compat")
        # read the instance's MCP policy up front so a disabled instance is logged at start
        policy_check = asyncio.create_task(policy.current(), name="haxcms-mcp-policy")
        try:
            yield
        finally:
            for task in (check, policy_check):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            await client.aclose()

    # Authenticated HTTP transport (#3140, ADR-0004): every request must carry the caller's
    # own HAXcms access token; FastMCP rejects the rest with 401 before any tool runs.
    auth = build_auth_provider(settings, client) if settings.per_caller_auth else None
    mcp = FastMCP(
        "haxcms-mcp",
        lifespan=_lifespan,
        auth=auth,
        # remote callers never see raw exception text (paths, hosts) from unexpected errors;
        # HaxcmsMcpError text is still translated by ErrorTranslationMiddleware
        mask_error_details=settings.per_caller_auth,
    )

    if settings.per_caller_auth:
        # first, so every later middleware and tool sees the caller's identity
        mcp.add_middleware(PrincipalMiddleware())
        _register_downloads(mcp, settings)
    # Order matters: read-only gate outermost, then logging, then error translation
    # closest to the tool functions.
    mcp.add_middleware(ReadOnlyMiddleware(settings, policy))
    mcp.add_middleware(ToolLoggingMiddleware())
    mcp.add_middleware(ErrorTranslationMiddleware())

    # one shared catalog: the content tools and the typed block tools use the same
    # 10-minute live-merge cache
    catalog = CatalogService(client)
    register_auth_tools(mcp, settings, client, compat, policy)
    register_sites_tools(mcp, settings, client)
    register_outline_tools(mcp, settings, client)
    register_pages_tools(mcp, settings, client)
    register_content_tools(mcp, settings, client, catalog)
    register_typed_block_tools(mcp, settings, client, catalog)
    register_files_tools(mcp, settings, client, catalog)
    register_settings_tools(mcp, settings, client)
    register_import_tools(mcp, settings, client)
    register_converter_tools(mcp, settings, client)
    register_export_tools(mcp, settings, client)
    register_catalog_resources(mcp, settings, client, catalog)
    register_site_resources(mcp, settings, client)
    register_prompts(mcp)

    return mcp
