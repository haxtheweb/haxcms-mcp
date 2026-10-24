"""FastMCP application assembly for the HAXcms MCP server.

`build_server(settings)` creates the FastMCP app and registers every tool, resource, prompt,
and middleware. Later Phases add their registrations here (PLAN.md Section 2.1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.middleware import (
    ErrorTranslationMiddleware,
    ReadOnlyMiddleware,
    ToolLoggingMiddleware,
)
from haxcms_mcp.prompts.journeys import register_prompts
from haxcms_mcp.resources.catalog import register_catalog_resources
from haxcms_mcp.resources.sites import register_site_resources
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


def build_server(settings: Settings) -> FastMCP:
    """Create and configure the FastMCP application for one Instance."""
    client = HaxcmsClient(settings)

    @asynccontextmanager
    async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
        """Graceful shutdown (T9.4): the httpx client dies with the server session."""
        try:
            yield
        finally:
            await client.aclose()

    mcp = FastMCP("haxcms-mcp", lifespan=_lifespan)

    # Order matters: read-only gate outermost, then logging, then error translation
    # closest to the tool functions.
    mcp.add_middleware(ReadOnlyMiddleware(settings))
    mcp.add_middleware(ToolLoggingMiddleware())
    mcp.add_middleware(ErrorTranslationMiddleware())

    # one shared catalog: the content tools and the typed block tools use the same
    # 10-minute live-merge cache
    catalog = CatalogService(client)
    register_auth_tools(mcp, settings, client)
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
