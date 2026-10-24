"""Content and generic block tools: the twelve Phase 4 content tools (PLAN T4.5).

Reads (`get_page_content`, `get_page_blocks`) and the whole-body write
(`set_page_content`, destructive) go through `services/content/service`; the block
operations go through `services/content/blocks` (one GET + one PATCH content per call,
one git revision per save). `add_block` validates tag and attributes against the Block
Catalog first; `list_blocks` / `get_block_schema` expose that catalog (bundled entries,
merged with live server schemas when a site is addressed).

Anchor grammar (PLAN §2.3, shared by every anchored operation):
`anchor` addresses ONE top-level block — either a case-insensitive text substring
(matched against block text and, for media blocks, attribute values like alt/source) or
a tag selector (`p`, `media-image`, `media-image[alt*=prairie]`, `tag[attr=value]`).
A lowercase single word that looks like a selector is treated as one. `occurrence`
disambiguates multiple matches: `"first"` (default), `"last"`, or a 1-based number.
Unresolvable anchors fail with ANCHOR_NOT_FOUND (with block previews) or
ANCHOR_AMBIGUOUS (listing every match) — nothing is saved in that case.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.services.catalog.service import CatalogService
from haxcms_mcp.services.content import blocks as blocks_service
from haxcms_mcp.services.content import service as content_service
from haxcms_mcp.services.content.blocks import build_block_html
from haxcms_mcp.tools._common import resolve_site, tool_annotations


def register_content_tools(
    mcp: FastMCP, settings: Settings, client: HaxcmsClient, catalog: CatalogService
) -> None:
    """Register the twelve content tools on the FastMCP app.

    `catalog` is the server-wide shared CatalogService (one live-merge cache), built in
    server.py and also used by the typed block tools.
    """

    @mcp.tool(annotations=tool_annotations("Get page content", read_only=True))
    async def get_page_content(page: str, site: str | None = None) -> dict[str, Any]:
        """Read a page's stored body: `{item, html, blocks}`.

        `html` is the raw stored body (no `<page-break>` envelope — that is managed
        automatically); `blocks` is the parsed top-level block list with `index`, `tag`,
        `attributes`, `text` and `preview` — the vocabulary for anchors. `page` is an id
        or slug (nested slugs like `unit-1/lesson-1` work). Use get_page_blocks for the
        compact index without the full HTML.
        """
        name = resolve_site(site, settings.default_site)
        content = await content_service.get_page_content(client, name, page)
        return dump_model(content)

    @mcp.tool(annotations=tool_annotations("Set page content", destructive=True))
    async def set_page_content(page: str, html: str, site: str | None = None) -> dict[str, Any]:
        """Replace a page's ENTIRE body (DESTRUCTIVE — read get_page_content first).

        `html` is the new body as top-level elements (`<p>`, `<h2>`, `<media-image>`,
        ...); any `<page-break>` tags in it are stripped — the envelope is rebuilt from
        the page's current record, so title, published flag and other details survive.
        The media schema (metadata.images/videos) is recomputed from the new body. One
        git revision is committed; restore_page_revision can undo. Returns the fresh
        `{item, html, blocks}`. For targeted changes prefer the block tools (add_block,
        replace_block, update_block, ...).
        """
        name = resolve_site(site, settings.default_site)
        content = await content_service.set_page_content(client, name, page, html)
        return dump_model(content)

    @mcp.tool(annotations=tool_annotations("Get page blocks", read_only=True))
    async def get_page_blocks(page: str, site: str | None = None) -> dict[str, Any]:
        """List a page's top-level blocks: `{count, blocks}` with index/tag/attributes/
        text/preview per block.

        The cheap orientation read before any anchored operation: pick the `anchor`
        (a text substring or tag selector) and `occurrence` from what you see here.
        """
        name = resolve_site(site, settings.default_site)
        blocks = await content_service.get_page_blocks(client, name, page)
        return {"count": len(blocks), "blocks": [dump_model(block) for block in blocks]}

    @mcp.tool(annotations=tool_annotations("Add block", idempotent=False))
    async def add_block(
        page: str,
        tag: str,
        attributes: dict[str, Any],
        inner_html: str = "",
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add one block (any catalog tag or native HTML element) and save the page.

        `tag` is validated against the Block Catalog (list_blocks / get_block_schema):
        unknown tags and attribute names fail with suggestions BEFORE anything is
        fetched or saved. `attributes` maps attribute name → value (pass `{}` for
        none): `true` becomes the HAX flag form (`card="card"`), `false`/`null` are
        omitted, lists/dicts become JSON.
        `inner_html` carries children — slotted content like
        `<p slot="question">...</p>` or inline markup. Placement: `append`/`prepend`
        (page level, NO anchor) or `after`/`before` (REQUIRE an anchor addressing the
        reference block; `occurrence` picks among matches). Typed tools (add_image,
        add_self_check, add_paragraph, ...) are the friendlier path for Core Blocks;
        this generic tool covers everything else. Returns `{site, page_id, page_slug,
        operation, affected, block_count, saved}` — one git revision per call.
        """
        name = resolve_site(site, settings.default_site)
        await catalog.validate(tag, attributes, site=name)
        html = build_block_html(tag, attributes, inner_html)
        result = await blocks_service.insert_block(
            client,
            name,
            page,
            html,
            anchor=anchor,
            occurrence=occurrence,
            placement=placement,
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Replace block", destructive=True))
    async def replace_block(
        page: str,
        anchor: str,
        html: str,
        occurrence: str | int | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Replace the anchored block with new HTML (DESTRUCTIVE for that block).

        `html` may contain several top-level elements — they all take the anchored
        block's place (the tutorial's paragraph → heading conversion is
        `replace_block(page, anchor="The First Secret", html='<h2>The First Secret is
        Noticing</h2>')`). The replacement is NOT catalog-validated (raw HTML escape
        hatch); prefer remove + add_block for validated rebuilds. Returns the standard
        block-operation result with the new blocks in `affected`.
        """
        name = resolve_site(site, settings.default_site)
        result = await blocks_service.replace_block(
            client, name, page, html, anchor=anchor, occurrence=occurrence
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Remove block", destructive=True))
    async def remove_block(
        page: str,
        anchor: str,
        occurrence: str | int | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Delete the anchored block (DESTRUCTIVE — confirm with the user first).

        The media schema is recomputed, so removing the last `<media-image>` also
        clears it from the page's metadata. `affected` reports the removed block at its
        OLD index. An administrator can restore it from the page's revision history.
        """
        name = resolve_site(site, settings.default_site)
        result = await blocks_service.remove_block(
            client, name, page, anchor, occurrence=occurrence
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Move block"))
    async def move_block(
        page: str,
        anchor: str,
        occurrence: str | int | None = None,
        target_anchor: str | None = None,
        target_occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Move the anchored block elsewhere on the same page.

        `placement`: `append`/`prepend` move to the page end/start (no
        `target_anchor`); `after`/`before` position relative to `target_anchor`.
        The target is resolved AFTER the source is lifted out, so target anchors
        address the page as it looks at insertion time (moving the first of two `h2`s
        "after the last h2" lands it after the other one). The source must not match
        its own target anchor.
        """
        name = resolve_site(site, settings.default_site)
        result = await blocks_service.move_block(
            client,
            name,
            page,
            anchor,
            occurrence=occurrence,
            target_anchor=target_anchor,
            target_occurrence=target_occurrence,
            placement=placement,
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Update block attributes"))
    async def update_block(
        page: str,
        anchor: str,
        set: dict[str, Any] | None = None,
        unset: list[str] | None = None,
        occurrence: str | int | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Set and/or remove attributes on the anchored block; tag, text and children stay.

        `set` maps attribute → value (values are stringified; HAX boolean flags want
        their own name as the value: `{"card": "card"}` — stored bodies use that form);
        `unset` lists attribute names to remove (absent names are a silent no-op).
        Names are validated as XML names; for catalog-level checks call
        get_block_schema first. The tutorial's "set image source, alt, caption" step is
        one update_block with all of them in `set`. At least one of `set`/`unset` is
        required.
        """
        name = resolve_site(site, settings.default_site)
        result = await blocks_service.update_block_attributes(
            client, name, page, anchor, occurrence=occurrence, set=set, unset=unset
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Set block text"))
    async def set_block_text(
        page: str,
        anchor: str,
        text: str,
        occurrence: str | int | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Replace the anchored block's text; its tag and attributes are kept.

        Markup in `text` is escaped, not parsed — for rich content use replace_block.
        For slotted blocks (self-check, grid-plate, ...) only the DEFAULT slot content
        is replaced; children carrying a `slot` attribute survive. Empty `text` clears
        the text.
        """
        name = resolve_site(site, settings.default_site)
        result = await blocks_service.set_block_text(
            client, name, page, anchor, text, occurrence=occurrence
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Add link", idempotent=False))
    async def add_link(
        page: str,
        anchor: str,
        text: str,
        url: str,
        occurrence: str | int | None = None,
        new_tab: bool = False,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Wrap text INSIDE the anchored block in `<a href>` (e.g. linking "Watch it
        here." within a paragraph).

        `anchor` addresses the containing block; `text` is the exact, CASE-SENSITIVE
        snippet inside it — the first match in document order is split out and wrapped,
        surrounding markup stays untouched. `new_tab=true` adds `target="_blank"`.
        Repeating the call wraps the text again (inside the existing link), so check
        the block first. A miss fails with the block's preview in the error details.
        """
        name = resolve_site(site, settings.default_site)
        result = await blocks_service.wrap_text_with_link(
            client,
            name,
            page,
            anchor,
            text,
            url,
            occurrence=occurrence,
            new_tab=new_tab,
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("List blocks", read_only=True))
    async def list_blocks() -> dict[str, Any]:
        """List the Block Catalog: `{count, blocks}` with `{tag, title, description,
        category}` per entry.

        The 31 bundled HAX Core Blocks (categories: text, media, layout, assessment,
        education, reference, embed) plus native HTML available through add_block
        (`p`, `h1`-`h6`, `ul`/`ol`/`li`, `table`, `blockquote`, `hr`, `a`, ...).
        Call get_block_schema(tag) for an entry's attributes, slots and example HTML.
        """
        blocks = await catalog.list_blocks()
        return {"count": len(blocks), "blocks": blocks}

    @mcp.tool(annotations=tool_annotations("Get block schema", read_only=True))
    async def get_block_schema(tag: str, site: str | None = None) -> dict[str, Any]:
        """Get one catalog entry: attributes (`name`, `type`, `required`, `description`,
        `enum`), `slots`, `example_html` and `agent_notes`.

        The reference for add_block and the typed block tools. With a site addressed
        (argument or HAXCMS_MCP_DEFAULT_SITE) the entry is merged with the server's
        live schema for that tag (cached 10 minutes); live failures degrade silently
        to the bundled entry. Unknown tags fail with the closest matches; tags the
        server's wc-registry knows but the catalog does not resolve through the live
        registry (category `embed`).
        """
        name = site or settings.default_site  # catalog reads work without a site
        entry = await catalog.get_block_schema(tag, site=name)
        return dump_model(entry)
