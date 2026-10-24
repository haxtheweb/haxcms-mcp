"""Page tools: the eleven Phase 3 page/revisions/search tools (PLAN Phase 3 T3.5)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.services import pages as pages_service
from haxcms_mcp.tools._common import resolve_site, tool_annotations


def register_pages_tools(mcp: FastMCP, settings: Settings, client: HaxcmsClient) -> None:
    """Register the eleven page tools on the FastMCP app."""

    @mcp.tool(annotations=tool_annotations("List pages", read_only=True))
    async def list_pages(
        parent: str | None = None,
        ancestor: str | None = None,
        depth: int | None = None,
        tags: list[str] | None = None,
        published: bool | None = None,
        page_type: str | None = None,
        include_content: bool = False,
        limit: int = 100,
        offset: int = 0,
        site: str | None = None,
    ) -> dict[str, Any]:
        """List pages with optional filters, flat (use get_outline for the tree).

        All filters combine: `parent` (direct children of this page id), `ancestor` with
        optional `depth` (a subtree; `depth` needs `ancestor`), `tags` (match ANY tag),
        `published`, `page_type` (e.g. `lesson`, `course`). `include_content=True` embeds
        each page's HTML body — leave it off for long lists. Paginated: returns
        `{count, total, page, items}`; `limit` caps at 200, page further with `offset`.
        Unpublished pages are included unless `published` filters them out.
        """
        name = resolve_site(site, settings.default_site)
        collection = await pages_service.list_pages(
            client,
            name,
            parent=parent,
            ancestor=ancestor,
            depth=depth,
            tags=tags,
            published=published,
            page_type=page_type,
            include_content=include_content,
            limit=limit,
            offset=offset,
        )
        return dump_model(collection)

    @mcp.tool(annotations=tool_annotations("Get page", read_only=True))
    async def get_page(
        page: str, include_content: bool = False, site: str | None = None
    ) -> dict[str, Any]:
        """Get one page's record by `page` (its id or slug — nested slugs like `unit-1/lesson-1`
        work).

        `include_content=True` adds the page's HTML body; details-only calls stay small.
        A miss fails with NOT_FOUND and suggests the nearest slugs. Page content is authored
        with the Phase 4 block tools; this read is the entry point to a page's identity,
        metadata and links.
        """
        name = resolve_site(site, settings.default_site)
        item = await pages_service.find_page(client, name, page, include_content=include_content)
        return dump_model(item)

    @mcp.tool(annotations=tool_annotations("Create page", idempotent=False))
    async def create_page(
        title: str,
        parent: str | None = None,
        order: int | None = None,
        slug: str | None = None,
        content_html: str | None = None,
        duplicate_of: str | None = None,
        description: str | None = None,
        published: bool = True,
        tags: list[str] | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Create one page and return its record (read the returned `id` and `slug`).

        The tutorial's "Add > Page" is `create_page(title="page")` — a page appended under
        the current parent. `parent` accepts an id or slug (omit for the root level); without
        `order` the page lands after its new siblings. The slug is auto-generated from the
        title (Pathauto); pass `slug` to pin an explicit one — that also makes it survive
        later title changes. `content_html` seeds the body (plain HTML; data-URI images
        become site files), `duplicate_of` copies another page's content instead.
        `published=False` creates a draft hidden from anonymous visitors.
        """
        name = resolve_site(site, settings.default_site)
        item = await pages_service.create_page(
            client,
            name,
            title,
            parent=parent,
            order=order,
            slug=slug,
            content_html=content_html,
            duplicate_of=duplicate_of,
            description=description,
            published=published,
            tags=tags,
        )
        return dump_model(item)

    @mcp.tool(annotations=tool_annotations("Create pages (bulk)", idempotent=False))
    async def create_pages(items: list[dict[str, Any]], site: str | None = None) -> dict[str, Any]:
        """Create many pages in ONE request (one git commit) — the fast path for imports.

        `items` is a list of page objects: `title` is required; `slug`, `parent`, `order`,
        `indent`, `content`, `description` and `metadata` are optional. Missing ids and slugs
        are generated (slug from title), so later entries can set `parent` to an earlier
        entry's id to build a tree in a single call. Returns `{count, pages}` with every
        created record, in input order. For a single page prefer create_page.
        """
        name = resolve_site(site, settings.default_site)
        created = await pages_service.create_pages(client, name, items)
        return {"count": len(created), "pages": [dump_model(item) for item in created]}

    @mcp.tool(annotations=tool_annotations("Update page details"))
    async def update_page_details(
        page: str,
        title: str | None = None,
        slug: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        published: bool | None = None,
        locked: bool | None = None,
        hide_in_menu: bool | None = None,
        icon: str | None = None,
        image: str | None = None,
        related_pages: list[str] | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Update page-details fields; pass only the ones to change. Returns the final record.

        This is the page "details" panel: the tutorial's rename ("page details → Title") is
        `update_page_details(page, title="...")`. Renaming regenerates the slug under
        Pathauto unless the page has an explicit slug override. `slug` pins an explicit slug
        (applied last, so a title change in the same call cannot overwrite it);
        `published=False` hides the page from anonymous visitors; `locked=True` blocks
        content edits; `hide_in_menu` removes it from navigation without unpublishing;
        `tags` REPLACES the tag list; `related_pages` takes page ids.
        """
        name = resolve_site(site, settings.default_site)
        item = await pages_service.update_page_details(
            client,
            name,
            page,
            title=title,
            slug=slug,
            description=description,
            tags=tags,
            published=published,
            locked=locked,
            hide_in_menu=hide_in_menu,
            icon=icon,
            image=image,
            related_pages=related_pages,
        )
        return dump_model(item)

    @mcp.tool(annotations=tool_annotations("Delete page", destructive=True))
    async def delete_page(page: str, site: str | None = None) -> dict[str, Any]:
        """Delete one page (DESTRUCTIVE — confirm with the user first).

        Child pages are NOT deleted: they re-parent to the root level and move to the end of
        the outline. The deletion is a git commit; an administrator can restore the page from
        the site's history, but treat this as permanent. `page` is an id or slug. Returns the
        deleted page's record.
        """
        name = resolve_site(site, settings.default_site)
        deleted = await pages_service.delete_page(client, name, page)
        return dump_model(deleted)

    @mcp.tool(annotations=tool_annotations("List page revisions", read_only=True))
    async def list_page_revisions(
        page: str, limit: int = 25, offset: int = 0, site: str | None = None
    ) -> dict[str, Any]:
        """List a page's git-backed revisions, newest first.

        Every save (details, content, outline) is a commit. Each entry carries
        `revision_number`, `hash` (the value get_page_revision / restore_page_revision
        expect), `short_hash`, `author`, `timestamp`, `date` and the commit `message`.
        Returns `{node_id, node_slug, node_title, count, total, page, revisions}`.
        """
        name = resolve_site(site, settings.default_site)
        result = await pages_service.list_page_revisions(
            client, name, page, limit=limit, offset=offset
        )
        revisions = [dump_model(revision) for revision in result.pop("revisions", [])]
        return {**result, "revisions": revisions}

    @mcp.tool(annotations=tool_annotations("Get page revision", read_only=True))
    async def get_page_revision(
        page: str, revision: str, site: str | None = None
    ) -> dict[str, Any]:
        """Get one historical revision with its full page content.

        `revision` is the git `hash` (7-64 hex characters) from list_page_revisions —
        revision NUMBERS are not accepted. Returns `{node_id, node_slug, node_title,
        revision, content}`; diff `content` against get_page(include_content=True) to show
        what changed before restoring.
        """
        name = resolve_site(site, settings.default_site)
        detail = await pages_service.get_page_revision(client, name, page, revision)
        return dump_model(detail)

    @mcp.tool(annotations=tool_annotations("Restore page revision", destructive=True))
    async def restore_page_revision(
        page: str, revision: str, site: str | None = None
    ) -> dict[str, Any]:
        """Restore a page to a historical revision (DESTRUCTIVE — confirm with the user first).

        The restore itself lands as a NEW commit, so nothing is lost and it can be undone by
        restoring a later revision. Restores the revision's content AND the details stored
        with it (title, description, published, locked, image). `revision` is the git `hash`
        from list_page_revisions. Returns `{node_id, node_slug, node_title,
        restored_from_hash, ...}`.
        """
        name = resolve_site(site, settings.default_site)
        return await pages_service.restore_page_revision(client, name, page, revision)

    @mcp.tool(annotations=tool_annotations("Search site", read_only=True))
    async def search_site(
        q: str,
        parent: str | None = None,
        tags: list[str] | None = None,
        published: bool | None = None,
        page_type: str | None = None,
        fields: list[str] | None = None,
        sort: str | None = None,
        limit: int = 25,
        offset: int = 0,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Full-text search across the site's pages, best match first.

        `q` is a case-insensitive substring query (max 256 characters) matched against
        title, slug, description, tags and content by default — narrow with `fields`
        (e.g. `["title"]`; `id` and `location` are also allowed). Filters (`parent`, `tags`,
        `published`, `page_type`) work like list_pages. Results carry `{id, title, slug,
        score, snippet, matches}`; `sort` defaults to `-score`. Paginated `{count, total,
        page, results}`.
        """
        name = resolve_site(site, settings.default_site)
        return await pages_service.search_site(
            client,
            name,
            q,
            parent=parent,
            tags=tags,
            published=published,
            page_type=page_type,
            fields=fields,
            sort=sort,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=tool_annotations("List tags", read_only=True))
    async def list_tags(site: str | None = None) -> dict[str, Any]:
        """List the site's tags with page frequencies, most used first.

        Returns `{count, total, page, tags: [{tag, count}]}` — the vocabulary for
        list_pages(tags=...) and search_site(tags=...).
        """
        name = resolve_site(site, settings.default_site)
        return await pages_service.list_tags(client, name)
