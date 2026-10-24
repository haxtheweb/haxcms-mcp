"""Pages service (PLAN Phase 3 T3.4; API-REF §4.2-4.5, §4.8-4.9).

Facts this module relies on (Phase 3 reads of the 26.8.1 route source, recorded in
PROGRESS.md):

* Single `POST items` → `itemFromParams` (HAXCMS.js): honours `node.id`, REPLACES
  `metadata` wholesale (so `published`/`tags` ride in the POST body) and always slugifies
  from title/location, ignoring any slug — an explicit slug needs the `setSlug` follow-up
  (which also sets `metadata.overridePathauto`, so the slug then sticks across later
  `setTitle` calls). `published=False` additionally gets a `setPublished` follow-up per
  PLAN T3.4 (belt and braces; skipped for the default `True` to avoid a redundant git
  commit per page). Omitting `order` leaves it at the prototype default 0 — every such
  creation ties and the outline falls back to title order (verified live) — so
  `create_page` computes the append position among the future siblings itself; the bulk
  path (`addPage`) defaults `order` to `manifest.items.length` and needs no help.
* Bulk `POST items` → `addPage`: honours client-supplied ids (parents can be calculated
  ahead of time) and defaults slugs to `welcome` — `create_pages` fills missing ids and
  slugs itself. The response only carries the LAST created item, so the created pages are
  re-listed from the manifest.
* `GET items` filters (siteRouteUtils.filterItems): `filter.tags` is CSV matched lowercase;
  `filter.published` accepts 1/true/yes/on and 0/false/no/off; `filter.depth` ONLY applies
  together with `filter.ancestor`.
* `PATCH items/{idOrSlug}`: one operation per request; `setTitle` regenerates the slug
  under Pathauto — `update_page_details` issues `setSlug` LAST and chains subsequent
  PATCHes onto the response `id` so a slug change mid-sequence cannot 404 the next call.
* Restore response: `{nodeId, nodeSlug, nodeTitle, restoredFromHash, jsonVariantLocation,
  hasItemMetadata, itemMetadataRestored, links}`; `{revisionId}` must be a 7-64 hex hash.
* Search: `q` required (400 when empty), max 256 chars; results `{count, total, page,
  results: [{id, title, slug, location, score, snippet, matches, links}]}`.
"""

from __future__ import annotations

import difflib
import re
from typing import Any
from uuid import uuid4

from haxcms_mcp.client import HaxcmsClient, site_api
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.item import Item, ItemCollection
from haxcms_mcp.models.revision import Revision, RevisionDetail
from haxcms_mcp.services.outline import fetch_all_items, resolve_parent_id

REVISION_ID_RE = re.compile(r"^[a-fA-F0-9]{7,64}$")
MAX_QUERY_LENGTH = 256  # search.js rejects longer q values
PAGE_LIMIT_MAX = 200  # paginateRecords maximum (items.js / revisions.js)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return slug or "page"


async def find_page(
    client: HaxcmsClient, site: str, id_or_slug: str, *, include_content: bool = False
) -> Item:
    """One page by id or slug; a miss suggests the nearest slugs from the outline."""
    try:
        data = await site_api.get_item(client, site, id_or_slug, include_content=include_content)
        return Item.from_api(data)
    except HaxcmsMcpError as error:
        if error.code is not ErrorCode.NOT_FOUND:
            raise
    close: list[str] = []
    try:
        items = await fetch_all_items(client, site)
        known = [item.slug for item in items if item.slug] + [item.id for item in items if item.id]
        close = list(dict.fromkeys(difflib.get_close_matches(id_or_slug, known, n=3, cutoff=0.6)))
    except HaxcmsMcpError:
        pass  # the site itself may be missing; keep the plain NOT_FOUND
    hint = (
        f"did you mean: {', '.join(close)}?" if close else "call list_pages for the current pages"
    )
    raise HaxcmsMcpError(
        ErrorCode.NOT_FOUND, f"page {id_or_slug!r} not found in site {site!r}", hint=hint
    )


async def list_pages(
    client: HaxcmsClient,
    site: str,
    *,
    parent: str | None = None,
    ancestor: str | None = None,
    depth: int | None = None,
    tags: list[str] | None = None,
    published: bool | None = None,
    page_type: str | None = None,
    include_content: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> ItemCollection:
    """Filtered page list (bearer — unpublished pages included unless filtered out).

    `parent`/`ancestor` are item IDS (`filter.parent` is an exact string match upstream;
    resolve a slug with `find_page` first). `depth` only applies together with `ancestor`.
    """
    if depth is not None and ancestor is None:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "depth only filters together with ancestor",
            hint="pass ancestor as well — upstream ignores filter.depth without filter.ancestor",
        )
    params: dict[str, Any] = {
        "page.limit": max(1, min(int(limit), PAGE_LIMIT_MAX)),
        "page.offset": max(0, int(offset)),
    }
    if parent is not None:
        params["filter.parent"] = parent
    if ancestor is not None:
        params["filter.ancestor"] = ancestor
    if depth is not None:
        params["filter.depth"] = int(depth)
    if tags:
        params["filter.tags"] = ",".join(tags)  # CSV, matched lowercase upstream
    if published is not None:
        params["filter.published"] = "1" if published else "0"
    if page_type is not None:
        params["filter.pageType"] = page_type
    if include_content:
        params["include"] = "content"
    data = await site_api.list_items(client, site, params=params)
    return ItemCollection.from_api(data)


async def create_page(
    client: HaxcmsClient,
    site: str,
    title: str,
    *,
    parent: str | None = None,
    order: int | None = None,
    slug: str | None = None,
    content_html: str | None = None,
    duplicate_of: str | None = None,
    description: str | None = None,
    published: bool = True,
    tags: list[str] | None = None,
) -> Item:
    """Create one page (the tutorial's "Add > Page"); returns the created record.

    `parent` accepts an id or a slug. Without `order` the page is appended after its new
    siblings (the create form would leave every un-ordered page at order 0). `slug` is
    applied via a `setSlug` follow-up because the create form ignores slugs (Pathauto
    slugifies the title); the follow-up also sets `overridePathauto`, so the explicit slug
    survives later title changes.
    """
    clean_title = (title or "").strip()
    if not clean_title:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "title must not be empty",
            hint='the tutorial "Add > Page" creates a page titled "page"',
        )
    items = await fetch_all_items(client, site)
    parent_id: str | None = None
    if parent is not None and str(parent).strip():
        parent_id = resolve_parent_id(items, str(parent))
    if order is None:
        # itemFromParams keeps the prototype's order 0 when omitted — compute the append
        # position among the future siblings so the page lands after them
        order = (
            max((item.order for item in items if (item.parent or None) == parent_id), default=-1)
            + 1
        )
    metadata: dict[str, Any] = {"published": bool(published)}
    if tags:
        metadata["tags"] = list(tags)
    payload = {
        "site": {"name": site},
        "node": {
            "id": None,
            "title": clean_title,
            "location": None,
            "duplicate": duplicate_of,
            "contents": content_html,
        },
        "parent": parent_id,
        "order": order,
        "indent": None,
        "description": description or "",
        "metadata": metadata,
    }
    data = await site_api.create_item(client, site, payload)
    item = Item.from_api(data)
    identifier = item.id or clean_title
    if slug is not None and slug.strip():
        data = await site_api.update_item(client, site, identifier, "setSlug", slug=slug.strip())
        item = Item.from_api(data)
    if not published:
        data = await site_api.update_item(client, site, identifier, "setPublished", published=False)
        item = Item.from_api(data)
    return item


async def create_pages(client: HaxcmsClient, site: str, items: list[dict[str, Any]]) -> list[Item]:
    """Bulk-create pages (the Document Import shape; used by Phase 7).

    Missing ids are generated (`addPage` honours them, so later entries can reference
    earlier ones as `parent`) and missing slugs are slugified from the title (upstream
    would default every slug to `welcome`). The bulk response only carries the LAST item,
    so the created pages are re-listed and returned in input order.
    """
    if not items:
        raise HaxcmsMcpError(ErrorCode.INVALID_ARGUMENT, "items must not be empty")
    payload_items: list[dict[str, Any]] = []
    wanted_ids: list[str] = []
    for index, entry in enumerate(items):
        if not isinstance(entry, dict):
            raise HaxcmsMcpError(ErrorCode.INVALID_ARGUMENT, f"item {index} must be an object")
        title = str(entry.get("title") or "").strip()
        if not title and not entry.get("delete"):
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                f"item {index} has no title",
                hint="every bulk entry needs a title (upstream defaults slugs to 'welcome')",
            )
        record = dict(entry)
        record["title"] = title
        if not record.get("id"):
            record["id"] = f"item-{uuid4()}"
        if not record.get("delete"):
            if not record.get("slug"):
                record["slug"] = _slugify(title)
            wanted_ids.append(str(record["id"]))
        payload_items.append(record)
    await site_api.create_item(client, site, {"site": {"name": site}, "items": payload_items})
    listed = await fetch_all_items(client, site)
    by_id = {item.id: item for item in listed}
    return [by_id[wanted] for wanted in wanted_ids if wanted in by_id]


def build_detail_operations(
    *,
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
) -> list[dict[str, Any]]:
    """One PATCH body per changed field, in PLAN T3.4's order (pure — regression-goldened).

    `setSlug` runs LAST so a `setTitle` cannot overwrite an explicit slug under Pathauto
    (setTitle regenerates slugs only while `metadata.overridePathauto` is unset, and
    setSlug is what sets it).
    """
    if title is not None and not title.strip():
        raise HaxcmsMcpError(ErrorCode.INVALID_ARGUMENT, "title must not be empty")
    if slug is not None and not slug.strip():
        raise HaxcmsMcpError(ErrorCode.INVALID_ARGUMENT, "slug must not be empty")
    candidates: list[tuple[str, dict[str, Any] | None]] = [
        ("setTitle", {"title": title.strip()} if title is not None else None),
        (
            "setDescription",
            {"description": description} if description is not None else None,
        ),
        ("setTags", {"tags": list(tags)} if tags is not None else None),
        ("setIcon", {"icon": icon} if icon is not None else None),
        ("setImage", {"image": image} if image is not None else None),
        (
            "setRelatedItems",
            {"relatedItems": list(related_pages)} if related_pages is not None else None,
        ),
        ("setLocked", {"locked": bool(locked)} if locked is not None else None),
        ("setPublished", {"published": bool(published)} if published is not None else None),
        (
            "setHideInMenu",
            {"hideInMenu": bool(hide_in_menu)} if hide_in_menu is not None else None,
        ),
        ("setSlug", {"slug": slug.strip()} if slug is not None else None),
    ]
    return [
        {"operation": operation, **fields} for operation, fields in candidates if fields is not None
    ]


async def update_page_details(
    client: HaxcmsClient,
    site: str,
    page: str,
    *,
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
) -> Item:
    """Multi-field page-details update as a sequence of single-operation PATCHes.

    Returns the final record. Later PATCHes target the previous response's id, so a
    Pathauto slug change from `setTitle` cannot break the rest of the sequence.
    """
    operations = build_detail_operations(
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
    if not operations:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "nothing to update",
            hint="pass at least one of title, slug, description, tags, published, locked, "
            "hide_in_menu, icon, image, related_pages",
        )
    current = page
    data: dict[str, Any] = {}
    for entry in operations:
        operation = str(entry["operation"])
        fields = {key: value for key, value in entry.items() if key != "operation"}
        data = await site_api.update_item(client, site, current, operation, **fields)
        new_id = data.get("id")
        if isinstance(new_id, str) and new_id:
            current = new_id
    return Item.from_api(data)


async def delete_page(client: HaxcmsClient, site: str, page: str) -> Item:
    """Delete one page; orphaned children re-parent to the root (the folder stays on disk)."""
    item = await find_page(client, site, page)
    data = await site_api.delete_item(client, site, item.id or page)
    return Item.from_api(data)


async def list_page_revisions(
    client: HaxcmsClient, site: str, page: str, *, limit: int = 25, offset: int = 0
) -> dict[str, Any]:
    """The page's git revision log (newest first), `{node_*, count, total, page, revisions}`."""
    data = await site_api.list_revisions(
        client,
        site,
        page,
        limit=max(1, min(int(limit), PAGE_LIMIT_MAX)),
        offset=max(0, int(offset)),
    )
    raw = data.get("revisions")
    revisions = (
        [Revision.from_api(entry) for entry in raw if isinstance(entry, dict)]
        if isinstance(raw, list)
        else []
    )
    return {
        "node_id": data.get("nodeId"),
        "node_slug": data.get("nodeSlug"),
        "node_title": data.get("nodeTitle"),
        "count": int(data.get("count") or 0),
        "total": int(data.get("total") or 0),
        "page": data.get("page") if isinstance(data.get("page"), dict) else {},
        "revisions": revisions,
    }


def _validate_revision_id(revision: str) -> str:
    clean = (revision or "").strip()
    if not REVISION_ID_RE.fullmatch(clean):
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"invalid revision {revision!r}",
            hint="revision must be a 7-64 character git hash from list_page_revisions "
            "(revision numbers are not accepted)",
        )
    return clean


async def get_page_revision(
    client: HaxcmsClient, site: str, page: str, revision: str
) -> RevisionDetail:
    """One historical revision with its full page content."""
    data = await site_api.get_revision(client, site, page, _validate_revision_id(revision))
    return RevisionDetail.from_api(data)


async def restore_page_revision(
    client: HaxcmsClient, site: str, page: str, revision: str
) -> dict[str, Any]:
    """Restore a revision as a NEW commit (content plus title/description/published/etc)."""
    data = await site_api.restore_revision(client, site, page, _validate_revision_id(revision))
    return {
        "node_id": data.get("nodeId"),
        "node_slug": data.get("nodeSlug"),
        "node_title": data.get("nodeTitle"),
        "restored_from_hash": data.get("restoredFromHash"),
        "json_variant_location": data.get("jsonVariantLocation"),
        "has_item_metadata": data.get("hasItemMetadata"),
        "item_metadata_restored": data.get("itemMetadataRestored"),
    }


async def search_site(
    client: HaxcmsClient,
    site: str,
    q: str,
    *,
    parent: str | None = None,
    tags: list[str] | None = None,
    published: bool | None = None,
    page_type: str | None = None,
    fields: list[str] | None = None,
    sort: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Full-text substring search (case-insensitive, default sort -score, bearer).

    Default searched fields: title, slug, description, tags, content (id and location can
    be added). Results carry `{id, title, slug, location, score, snippet, matches}`.
    """
    query = (q or "").strip()
    if not query:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "search query must not be empty",
            hint="q is required upstream; empty queries are rejected with 400",
        )
    if len(query) > MAX_QUERY_LENGTH:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"search query too long ({len(query)} > {MAX_QUERY_LENGTH} characters)",
        )
    params: dict[str, Any] = {
        "page.limit": max(1, min(int(limit), PAGE_LIMIT_MAX)),
        "page.offset": max(0, int(offset)),
    }
    if parent is not None:
        params["filter.parent"] = parent
    if tags:
        params["filter.tags"] = ",".join(tags)
    if published is not None:
        params["filter.published"] = "1" if published else "0"
    if page_type is not None:
        params["filter.pageType"] = page_type
    if fields:
        params["fields"] = ",".join(fields)
    if sort is not None:
        params["sort"] = sort
    return await site_api.search(client, site, query, params=params)


async def list_tags(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """Tag frequencies `{count, total, page, tags: [{tag, count}]}` sorted by -count."""
    return await site_api.list_tags(client, site)
