"""Site resources (PLAN Phase 4 T4.6): read-only views of the live instance.

* `haxcms://sites` — JSON list of every site (the `list_sites` rows).
* `haxcms://sites/{site}` — one site's merged detail record as JSON.
* `haxcms://sites/{site}/outline` — the page tree as JSON: `text` renders it as an
  indented outline (`- title (slug) [id]`, two spaces per level, ` [unpublished]`
  marker), `outline` carries the full node tree (the `get_outline` tool's shape).
* `haxcms://sites/{site}/pages/{id_or_slug}` — the page's stored content HTML with a
  `<!-- block N: tag -->` comment before every top-level block (mime `text/html`): the
  anchor-picking read without a tool call. `{id_or_slug}` is ONE URI segment — nested
  slugs (`unit-1/lesson-1`) resolve through the get_page_content tool instead.
"""

from __future__ import annotations

import json

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.models.content import Block
from haxcms_mcp.models.item import OutlineNode
from haxcms_mcp.services import outline as outline_service
from haxcms_mcp.services import sites as sites_service
from haxcms_mcp.services.content import service as content_service


def _outline_lines(nodes: list[OutlineNode], depth: int = 0) -> list[str]:
    """The indented-text outline: `- title (slug) [id]`, two spaces per level."""
    lines: list[str] = []
    for node in nodes:
        item = node.item
        marker = "" if item.metadata.published is not False else " [unpublished]"
        lines.append(f"{'  ' * depth}- {item.title} ({item.slug}) [{item.id}]{marker}")
        lines.extend(_outline_lines(node.children, depth + 1))
    return lines


def render_page_html(blocks: list[Block]) -> str:
    """Content HTML with the block index as HTML comments (pure — regression-friendly)."""
    return "\n".join(f"<!-- block {block.index}: {block.tag} -->\n{block.html}" for block in blocks)


def register_site_resources(mcp: FastMCP, settings: Settings, client: HaxcmsClient) -> None:
    """Register the four site resources on the FastMCP app."""

    @mcp.resource("haxcms://sites", mime_type="application/json")
    async def sites_list() -> str:
        """JSON list of every site on the instance."""
        sites = await sites_service.list_sites(client)
        return json.dumps([dump_model(site) for site in sites], ensure_ascii=False, indent=2)

    @mcp.resource("haxcms://sites/{site}", mime_type="application/json")
    async def site_summary(site: str) -> str:
        """One site's merged detail record (system info + public summary)."""
        detail = await sites_service.get_site(client, site)
        return json.dumps(dump_model(detail), ensure_ascii=False, indent=2)

    @mcp.resource("haxcms://sites/{site}/outline", mime_type="application/json")
    async def site_outline(site: str) -> str:
        """The page tree as indented text (`text`) and JSON nodes (`outline`)."""
        nodes = await outline_service.get_outline(client, site)
        payload = {
            "site": site,
            "count": len(outline_service.flatten(nodes)),
            "text": "\n".join(_outline_lines(nodes)),
            "outline": [dump_model(node) for node in nodes],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @mcp.resource("haxcms://sites/{site}/pages/{id_or_slug}", mime_type="text/html")
    async def site_page(site: str, id_or_slug: str) -> str:
        """The page's stored content HTML, one `<!-- block N: tag -->` comment per block."""
        content = await content_service.get_page_content(client, site, id_or_slug)
        return render_page_html(content.blocks)
