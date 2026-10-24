"""Outline tools: the five Phase 3 structure tools (PLAN Phase 3 T3.5)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.models.item import OutlineNode
from haxcms_mcp.services import outline as outline_service
from haxcms_mcp.services.outline import flatten
from haxcms_mcp.tools._common import resolve_site, tool_annotations


def _tree_payload(site: str, nodes: list[OutlineNode]) -> dict[str, Any]:
    return {
        "site": site,
        "count": len(flatten(nodes)),
        "outline": [dump_model(node) for node in nodes],
    }


def register_outline_tools(mcp: FastMCP, settings: Settings, client: HaxcmsClient) -> None:
    """Register the five outline/structure tools on the FastMCP app."""

    @mcp.tool(annotations=tool_annotations("Get outline", read_only=True))
    async def get_outline(site: str | None = None) -> dict[str, Any]:
        """Get the site's full page outline as a tree (unpublished pages included).

        `site` defaults to the configured Default Site. Each node is `{item, children}` where
        `item` carries `id`, `title`, `slug`, `parent`, `indent`, `order`, `published`, `tags`
        and `metadata`. This is the map of the site: use the ids and slugs from it for every
        other page tool. Returns `{site, count, outline}`.
        """
        name = resolve_site(site, settings.default_site)
        nodes = await outline_service.get_outline(client, name)
        return _tree_payload(name, nodes)

    @mcp.tool(annotations=tool_annotations("Reorder pages", destructive=True))
    async def reorder_pages(
        ordered_ids: list[str], parent: str | None = None, site: str | None = None
    ) -> dict[str, Any]:
        """Reorder the children of one parent (DESTRUCTIVE — rewrites the whole outline).

        `ordered_ids` must list EVERY current child of `parent` exactly once, in the desired
        order — call get_outline first. `parent` is an id or slug; omit it to reorder the
        root level. Pages are not deleted by reordering, but the save rewrites the complete
        manifest (one git commit). Returns the fresh outline tree.
        """
        name = resolve_site(site, settings.default_site)
        nodes = await outline_service.reorder_pages(client, name, parent, ordered_ids)
        return _tree_payload(name, nodes)

    @mcp.tool(annotations=tool_annotations("Move page", idempotent=False))
    async def move_page(page: str, direction: str, site: str | None = None) -> dict[str, Any]:
        """Move one page a single step within the outline.

        `direction` is `up`/`down` (swap order with the adjacent sibling) or `indent`
        (nest under the previous sibling) / `outdent` (lift to the grandparent, right after
        the parent) — the same four moves as the outline editor's arrow buttons. `page` is an
        id or slug. Calling twice moves two steps. Returns the moved page's record.
        """
        name = resolve_site(site, settings.default_site)
        item = await outline_service.move_page(client, name, page, direction)
        return dump_model(item)

    @mcp.tool(annotations=tool_annotations("Set page parent"))
    async def set_page_parent(
        page: str, parent: str | None = None, order: int | None = None, site: str | None = None
    ) -> dict[str, Any]:
        """Reparent a page: move it under a new `parent`, or to the root level when omitted.

        `page` and `parent` are ids or slugs. Without `order` the page is APPENDED after its
        new siblings; pass `order` to place it at an exact position among them. Descendant
        pages move with the page. Returns the moved page's record.
        """
        name = resolve_site(site, settings.default_site)
        item = await outline_service.set_page_parent(client, name, page, parent, order)
        return dump_model(item)

    @mcp.tool(annotations=tool_annotations("Normalize slugs"))
    async def normalize_slugs(preview: bool = False, site: str | None = None) -> dict[str, Any]:
        """Regenerate every page slug from its title, following the site's Pathauto pattern.

        Use after bulk title edits when slugs have drifted. Pages with an explicit slug
        override (`setSlug` / `update_page_details(slug=...)`) are skipped. `preview=True`
        returns the planned changes WITHOUT writing anything — prefer it first on large
        sites. Returns `{changed, preview, changes: [{id, title, oldSlug, newSlug}],
        skipped: [...]}`.
        """
        name = resolve_site(site, settings.default_site)
        return await outline_service.normalize_slugs(client, name, preview=preview)
