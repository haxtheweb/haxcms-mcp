"""Content service (PLAN Phase 4 T4.3; API-REF §5.1-5.2).

Read path: `GET items/{idOrSlug}?include=content` — one call yields both the record (the
envelope source) and the body; stored `content` never carries a `<page-break>` (stripped
on save).

Write path facts (saveNode.js, verified Phase 4):

* saveNode RESETS `metadata.videos`/`metadata.images` on every page save and rebuilds
  them from the sent `schema` — so every write recomputes the media schema from the very
  body it saves and always sends it (an empty list clears stale media metadata).
* The envelope prepended by `save_content` must be the ONLY `<page-break>` in the body:
  pageBreakParser splits on every page-break and would treat later segments as separate
  pages. Incoming HTML is parsed and re-serialized (normalisation) with any user-supplied
  `<page-break>` elements dropped.
* Writes run under the per-site lock (§2.3) — read-modify-write is one critical section.
"""

from __future__ import annotations

from lxml.html import HtmlElement

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.models.content import Block, PageContent
from haxcms_mcp.models.item import Item
from haxcms_mcp.services.content.media_schema import build_media_schema
from haxcms_mcp.services.content.page_break import save_content
from haxcms_mcp.services.content.parser import parse_blocks, parse_body
from haxcms_mcp.services.content.serializer import serialize_elements
from haxcms_mcp.services.locks import site_lock
from haxcms_mcp.services.pages import find_page


def strip_envelopes(elements: list[HtmlElement]) -> list[HtmlElement]:
    """Drop user-supplied `<page-break>` elements — only `save_content` emits one."""
    return [element for element in elements if element.tag != "page-break"]


async def fetch_page_body(
    client: HaxcmsClient, site: str, page: str
) -> tuple[Item, list[HtmlElement]]:
    """Fresh record + parsed working elements in ONE GET (include=content).

    The record doubles as the envelope source for the save that follows (it must be
    fresh — a stale one would roll page details back), so block operations never need a
    second item read.
    """
    item = await find_page(client, site, page, include_content=True)
    return item, strip_envelopes(parse_body(item.content or ""))


async def get_page_content(client: HaxcmsClient, site: str, page: str) -> PageContent:
    """The page's record, raw stored body and parsed blocks (API-REF §5.1 content)."""
    item = await find_page(client, site, page, include_content=True)
    html = item.content or ""
    return PageContent(item=item, html=html, blocks=parse_blocks(html))


async def get_page_blocks(client: HaxcmsClient, site: str, page: str) -> list[Block]:
    """Just the block list — the cheap read for anchor discovery."""
    content = await get_page_content(client, site, page)
    return content.blocks


async def set_page_content(client: HaxcmsClient, site: str, page: str, html: str) -> PageContent:
    """Replace the whole body (destructive; one upstream git commit).

    Lock → fresh `get_item` (envelope source) → parse/normalise the incoming HTML →
    media schema → PATCH → re-GET the item so the returned PageContent reflects the
    stored state (upstream may have adjusted description/readtime/images/videos).
    """
    async with site_lock(site):
        item, elements = await fetch_page_body(client, site, page)
        new_elements = strip_envelopes(parse_body(html or ""))
        schema = build_media_schema(new_elements)
        saved = await save_content(
            client, site, item, serialize_elements(new_elements), schema=schema
        )
        return await get_page_content(client, site, saved.id or page)
