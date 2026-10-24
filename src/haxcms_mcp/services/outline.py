"""Outline service (PLAN Phase 3 T3.3; API-REF §4.2, §4.4, §4.6-4.7).

Facts this module relies on (Phase 3 reads of the 26.8.1 route source, recorded in
PROGRESS.md):

* `GET items` paginates with default limit 25 and max 200 (items.js `paginateRecords`) —
  `fetch_all_items` loops `page.limit=200` until `total` is reached. Bearer callers see
  unpublished items too.
* `PATCH site/outline` (saveOutline.js): items OMITTED from the payload are NOT deleted
  (only an explicit `delete: true` entry removes a page), but they keep their old order and
  every SENT item's slug is regenerated from its title under Pathauto unless its
  `metadata.overridePathauto` is true — so `reorder_pages` always sends the COMPLETE
  manifest with each item's metadata round-tripped.
* `setParent` defaults `order` to 0 upstream (nodeDetailOperations.js) — the service
  computes an append position when the caller omits `order`.
* `moveUp`/`moveDown` swap `order` with the adjacent sibling; `indent` reparents under the
  previous sibling; `outdent` moves to the grandparent right after the parent.
* `POST site/normalize-slugs` supports `preview: true` (plans without writing) and skips
  items with `overridePathauto`.
"""

from __future__ import annotations

from typing import Any

from haxcms_mcp.client import HaxcmsClient, site_api
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.item import Item, OutlineNode

PAGE_LIMIT = 200  # paginateRecords maximum in items.js

DIRECTIONS = {"up": "moveUp", "down": "moveDown", "indent": "indent", "outdent": "outdent"}


async def fetch_all_items(client: HaxcmsClient, site: str) -> list[Item]:
    """Every item of the site in manifest order, paginating `GET items` (bearer)."""
    items: list[Item] = []
    offset = 0
    while True:
        data = await site_api.list_items(
            client, site, params={"page.limit": PAGE_LIMIT, "page.offset": offset}
        )
        raw = data.get("items")
        page_items = (
            [Item.from_api(record) for record in raw if isinstance(record, dict)]
            if isinstance(raw, list)
            else []
        )
        items.extend(page_items)
        total = int(data.get("total") or 0)
        offset += len(page_items)
        if not page_items or offset >= total:
            return items


def build_outline(items: list[Item]) -> list[OutlineNode]:
    """Group by parent, sort by order, recurse (pure — PLAN T3.3).

    Orphans (a `parent` id that is not in the item set) surface at root level so no page is
    ever silently dropped; parent cycles are broken by visiting each item at most once.
    """
    by_id = {item.id for item in items if item.id}
    children_of: dict[str | None, list[Item]] = {}
    for item in items:
        parent = item.parent if item.parent in by_id else None
        children_of.setdefault(parent, []).append(item)
    for bucket in children_of.values():
        bucket.sort(key=lambda entry: (entry.order, entry.title))

    visited: set[str] = set()

    def attach(item: Item) -> OutlineNode | None:
        if item.id:
            if item.id in visited:
                return None
            visited.add(item.id)
        node = OutlineNode(item=item)
        for child in children_of.get(item.id, []):
            child_node = attach(child)
            if child_node is not None:
                node.children.append(child_node)
        return node

    roots: list[OutlineNode] = []
    for root_item in children_of.get(None, []):
        node = attach(root_item)
        if node is not None:
            roots.append(node)
    # items inside a parent cycle were unreachable from any root: surface each chain once
    for item in items:
        if item.id and item.id not in visited:
            node = attach(item)
            if node is not None:
                roots.append(node)
    return roots


def flatten(nodes: list[OutlineNode]) -> list[Item]:
    """Pre-order walk of the tree back into a flat item list."""
    out: list[Item] = []
    for node in nodes:
        out.append(node.item)
        out.extend(flatten(node.children))
    return out


async def get_outline(client: HaxcmsClient, site: str) -> list[OutlineNode]:
    """The site's full outline tree, unpublished pages included."""
    return build_outline(await fetch_all_items(client, site))


def resolve_parent_id(items: list[Item], parent: str | None) -> str | None:
    """Map a parent id-or-slug to its id using an already-fetched item list."""
    if parent is None:
        return None
    needle = parent.strip()
    if not needle:
        return None
    for item in items:
        if item.id == needle or item.slug == needle:
            return item.id
    raise HaxcmsMcpError(
        ErrorCode.NOT_FOUND,
        f"parent page {parent!r} not found in the site outline",
        hint="call get_outline for the current page ids and slugs",
    )


def build_reorder_payload(
    items: list[Item], parent: str | None, ordered_ids: list[str]
) -> list[dict[str, Any]]:
    """The COMPLETE `PATCH site/outline` payload reordering one parent's children (pure).

    The children's current order slots (sorted ascending) are reassigned to the new
    sequence, so no other item's position shifts. Every item round-trips its slug and
    metadata: saveOutline regenerates slugs under Pathauto but honours
    `metadata.overridePathauto`, and merged metadata keys must not be lost.
    """
    child_ids = [item.id for item in items if (item.parent or None) == (parent or None)]
    wanted = list(ordered_ids)
    if sorted(wanted) != sorted(child_ids):
        current = set(child_ids)
        missing = [cid for cid in child_ids if cid not in set(wanted)]
        unknown = [oid for oid in wanted if oid not in current]
        parts = []
        if missing:
            parts.append(f"missing {missing}")
        if unknown:
            parts.append(f"not children of this parent: {unknown}")
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "ordered_ids must list every child of the parent exactly once "
            f"({len(child_ids)} children); " + "; ".join(parts),
            hint="call get_outline for the current children of this parent",
        )
    slots = sorted(item.order for item in items if (item.parent or None) == (parent or None))
    new_order = dict(zip(wanted, slots, strict=True))
    payload: list[dict[str, Any]] = []
    for item in items:
        payload.append(
            {
                "id": item.id,
                "title": item.title,
                "parent": item.parent,
                "indent": item.indent,
                "order": new_order.get(item.id, item.order),
                "slug": item.slug,
                "metadata": item.metadata.to_api(),
            }
        )
    return payload


async def reorder_pages(
    client: HaxcmsClient, site: str, parent: str | None, ordered_ids: list[str]
) -> list[OutlineNode]:
    """Reorder one parent's children (None = root level) and return the fresh outline.

    `ordered_ids` must be exactly the current children of `parent` in the desired order.
    Sends the COMPLETE manifest to `PATCH site/outline` (omitted items would survive but
    keep stale order values).
    """
    items = await fetch_all_items(client, site)
    parent_id = resolve_parent_id(items, parent)
    payload = build_reorder_payload(items, parent_id, ordered_ids)
    data = await site_api.save_outline(client, site, payload)
    raw = data.get("items")
    saved = (
        [Item.from_api(record) for record in raw if isinstance(record, dict)]
        if isinstance(raw, list)
        else []
    )
    return build_outline(saved or items)


async def set_page_parent(
    client: HaxcmsClient, site: str, page: str, parent: str | None = None, order: int | None = None
) -> Item:
    """Reparent a page (`operation setParent`); None parent moves it to root level.

    Upstream defaults `order` to 0, which would jump the page to the top — when omitted,
    the page is appended after its new siblings instead.
    """
    items = await fetch_all_items(client, site)
    parent_id = resolve_parent_id(items, parent)
    if order is None:
        siblings = [item for item in items if (item.parent or None) == parent_id]
        order = max((sibling.order for sibling in siblings), default=-1) + 1
    data = await site_api.update_item(
        client, site, page, "setParent", parent=parent_id, order=int(order)
    )
    return Item.from_api(data)


async def move_page(client: HaxcmsClient, site: str, page: str, direction: str) -> Item:
    """Move a page one step: `up`/`down` among siblings, `indent`/`outdent` in the tree."""
    operation = DIRECTIONS.get((direction or "").strip().lower())
    if operation is None:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown direction {direction!r}",
            hint="use up, down, indent or outdent",
        )
    data = await site_api.update_item(client, site, page, operation)
    return Item.from_api(data)


async def normalize_slugs(
    client: HaxcmsClient, site: str, *, preview: bool = False
) -> dict[str, Any]:
    """Regenerate every slug from its title per Pathauto (API-REF §4.7).

    Returns `{changed, preview, changes: [{id, title, oldSlug, newSlug}], skipped: [...]}`;
    pages with an explicit slug override are skipped. `preview=True` plans without writing.
    """
    return await site_api.normalize_slugs(client, site, preview=preview)
