"""Catalog resources (PLAN Phase 4 T4.6).

* `haxcms://catalog/blocks` — JSON list of catalog summaries (`{tag, title, description,
  category}` per row, same rows the `list_blocks` tool returns).
* `haxcms://catalog/blocks/{tag}` — one merged catalog record as JSON: attributes,
  slots, `example_html` and `agent_notes`. When a Default Site is configured the record
  is live-merged with that site's schema through the shared CatalogService (the same
  10-minute cache the `get_block_schema` tool uses); unknown tags fail with the closest
  matches.
"""

from __future__ import annotations

import json

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.services.catalog.service import CatalogService


def register_catalog_resources(
    mcp: FastMCP, settings: Settings, client: HaxcmsClient, catalog: CatalogService
) -> None:
    """Register the two catalog resources on the FastMCP app.

    `catalog` is the server-wide shared CatalogService built in server.py — the same
    instance (and cache) the content and typed block tools use.
    """

    @mcp.resource("haxcms://catalog/blocks", mime_type="application/json")
    async def catalog_blocks() -> str:
        """JSON list of every catalog block: tag, title, description, category."""
        blocks = await catalog.list_blocks()
        return json.dumps(blocks, ensure_ascii=False, indent=2)

    @mcp.resource("haxcms://catalog/blocks/{tag}", mime_type="application/json")
    async def catalog_block(tag: str) -> str:
        """One merged catalog record (attributes, slots, example_html, agent_notes)."""
        entry = await catalog.get_block_schema(tag, site=settings.default_site)
        return json.dumps(dump_model(entry), ensure_ascii=False, indent=2)
