"""Site lifecycle tools: the nine Phase 2 tools (PLAN Phase 2 T2.4)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.services import sites as sites_service
from haxcms_mcp.tools._common import resolve_site, tool_annotations


def register_sites_tools(mcp: FastMCP, settings: Settings, client: HaxcmsClient) -> None:
    """Register the nine site lifecycle tools on the FastMCP app."""

    @mcp.tool(annotations=tool_annotations("List sites", read_only=True))
    async def list_sites() -> dict[str, Any]:
        """List every site on the HAXcms instance.

        Each entry carries the site's machine `name` (the value every other tool's `site`
        argument expects), `title`, `description`, `page_count` and `location`. Use this first
        when the Default Site is not configured or a site name is unknown.
        """
        entries = await sites_service.list_sites(client)
        return {"count": len(entries), "sites": [dump_model(entry) for entry in entries]}

    @mcp.tool(annotations=tool_annotations("Get site", read_only=True))
    async def get_site(site: str | None = None) -> dict[str, Any]:
        """Get one site's full record: identity, theme, page/file counts and operation links.

        `site` defaults to the configured Default Site. Merges the system site info (title,
        description, `page_count`, created/updated, links to clone/archive/download operations)
        with the public summary (`theme`, `language`, `counts` of items/published items/tags/
        regions/files). Fails with NOT_FOUND for an unknown site name.
        """
        name = resolve_site(site, settings.default_site)
        detail = await sites_service.get_site(client, name)
        return dump_model(detail)

    @mcp.tool(annotations=tool_annotations("Create site", idempotent=False))
    async def create_site(
        name: str,
        title: str | None = None,
        description: str = "",
        theme: str = "clean-one",
        license: str | None = None,
        first_page_title: str = "Home",
        first_page_content: str = "<p></p>",
    ) -> dict[str, Any]:
        """Create a new blank site with one starting page.

        `name` must be a lowercase machine name: a-z, 0-9, - and _ only — names cannot contain
        spaces; use - or _ (for example `first-underscore-course`). If `name` is already taken
        the server creates `<name>-1` instead and the result carries a warning — always read the
        returned `name`. `theme` must be a machine name from list_themes (default `clean-one`);
        an unknown theme fails with INVALID_ARGUMENT before anything is written. `license` is a
        Creative Commons code (`by`, `by-sa`, `by-nd`, `by-nc`, `by-nc-sa`, `by-nc-nd`; default
        `by-sa`). Returns the created site's record — use its `name` for all later calls.
        """
        detail = await sites_service.create_site(
            client,
            name,
            title=title,
            description=description,
            theme=theme,
            license=license,
            first_page_title=first_page_title,
            first_page_content=first_page_content,
        )
        return dump_model(detail)

    @mcp.tool(
        annotations=tool_annotations("Create site from skeleton", idempotent=False),
    )
    async def create_site_from_skeleton(
        skeleton: str,
        name: str | None = None,
        title: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a site pre-populated from an installed skeleton (a site template).

        Skeletons are HAXcms's ready-made journeys — grouped by `category` they cover Course,
        Website, Portfolio and more; browse them with list_skeletons and inspect one with
        get_skeleton. The skeleton's own theme, description, license and pages WIN over the
        arguments here. `name` follows the same machine-name rules as create_site and defaults
        to the skeleton's machine name. Returns the created site's record.
        """
        detail = await sites_service.create_site_from_skeleton(
            client, skeleton, name, title=title, description=description
        )
        return dump_model(detail)

    @mcp.tool(annotations=tool_annotations("List skeletons", read_only=True))
    async def list_skeletons() -> dict[str, Any]:
        """List installed site skeletons (templates) available to create_site_from_skeleton.

        Each record carries `machine_name` (the value create_site_from_skeleton expects),
        `title`, `description`, `category` (Course, Website, Portfolio, ...) and `enabled`.
        Templates saved from existing sites appear here alongside the bundled ones.
        """
        skeletons = await sites_service.list_skeletons(client)
        return {"count": len(skeletons), "skeletons": [dump_model(entry) for entry in skeletons]}

    @mcp.tool(annotations=tool_annotations("Get skeleton", read_only=True))
    async def get_skeleton(skeleton: str) -> dict[str, Any]:
        """Get one skeleton's full detail.

        Returns `meta` (title, description, category, tags), `site` (default name/description/
        theme) and `build` (the page outline it creates). Use it to show what a journey contains
        before create_site_from_skeleton. Fails with NOT_FOUND for an unknown machine name.
        """
        record = await sites_service.get_skeleton(client, skeleton)
        return dump_model(record)

    @mcp.tool(annotations=tool_annotations("List themes", read_only=True))
    async def list_themes() -> dict[str, Any]:
        """List the themes installed on the HAXcms instance.

        `machine_name` is the value create_site's `theme` argument expects. Records also carry
        `name`, `description`, `category` and flags: avoid themes with `hidden` or `terrible`
        set unless the user asks for one specifically.
        """
        themes = await sites_service.list_themes(client)
        return {"count": len(themes), "themes": [dump_model(entry) for entry in themes]}

    @mcp.tool(annotations=tool_annotations("Clone site", idempotent=False))
    async def clone_site(site: str | None = None) -> dict[str, Any]:
        """Clone an existing site, pages and files included, under a new server-chosen name.

        `site` defaults to the configured Default Site. Returns `{name, site}` where `name` is
        the NEW site's machine name (usually `<site>-1`, `<site>-2`, ...) — use it for all later
        calls on the copy. The original is untouched.
        """
        name = resolve_site(site, settings.default_site)
        return await sites_service.clone_site(client, name)

    @mcp.tool(
        annotations=tool_annotations("Archive site", destructive=True),
    )
    async def archive_site(site: str | None = None) -> dict[str, Any]:
        """Archive a site (DESTRUCTIVE — confirm with the user first).

        The site leaves list_sites and its folder moves under `_archived/` in the HAXcms root;
        nothing is deleted and an administrator can restore it manually. `site` defaults to the
        configured Default Site. Returns `{name, archived_name, detail}`.
        """
        name = resolve_site(site, settings.default_site)
        return await sites_service.archive_site(client, name)
