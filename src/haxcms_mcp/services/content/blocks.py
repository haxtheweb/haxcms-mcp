"""Block operations (PLAN Phase 4 T4.3; §2.3 anchors, §2.5 results).

Every operation is a read-modify-write under the per-site lock: fetch the fresh record
and body (`fetch_page_body`), resolve anchors against the current block list, mutate the
working element list, recompute the media schema, save through the envelope, and return a
`BlockOpResult` naming the operation, the affected blocks and the post-save block count.

Placement semantics (shared by `insert_block` and `move_block`):

* `append` / `prepend` — page level: the end/start of the body; passing an anchor
  (or target anchor) with them is rejected rather than silently ignored.
* `after` / `before` — immediately after/before the anchored block; require an anchor.

`move_block` resolves the TARGET after the source has been lifted out, so target anchors
address the page as it looks at insertion time (moving the first of two `h2`s "after the
last h2" lands it after the other one).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from lxml import html as lxml_html
from lxml.html import HtmlElement

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.content import Block, BlockOpResult
from haxcms_mcp.services.content.anchors import resolve_anchor
from haxcms_mcp.services.content.media_schema import build_media_schema
from haxcms_mcp.services.content.page_break import save_content
from haxcms_mcp.services.content.parser import parse_body, to_blocks
from haxcms_mcp.services.content.serializer import serialize_elements
from haxcms_mcp.services.content.service import fetch_page_body, strip_envelopes
from haxcms_mcp.services.locks import site_lock

PLACEMENTS = ("after", "before", "append", "prepend")
RELATIVE_PLACEMENTS = ("after", "before")

# XML Name production (no spaces/quotes/=) — anything else would serialize malformed
_ATTR_NAME_RE = re.compile(r"^[A-Za-z_:][-A-Za-z0-9_:.]*$")

# mutates the working element list in place; returns the affected blocks (post-mutation
# indices, except removals which report the OLD index)
Mutator = Callable[[list[HtmlElement]], list[Block]]


async def _run_block_op(
    client: HaxcmsClient, site: str, page: str, operation: str, mutate: Mutator
) -> BlockOpResult:
    async with site_lock(site):
        item, elements = await fetch_page_body(client, site, page)
        affected = mutate(elements)
        schema = build_media_schema(elements)
        saved = await save_content(client, site, item, serialize_elements(elements), schema=schema)
        return BlockOpResult(
            site=site,
            page_id=saved.id or item.id,
            page_slug=saved.slug or item.slug,
            operation=operation,
            affected=affected,
            block_count=len(elements),
        )


def _parse_new_blocks(html: str) -> list[HtmlElement]:
    """Parse incoming block HTML (one or more top-level elements; envelopes dropped)."""
    elements = strip_envelopes(parse_body(html or ""))
    if not elements:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "block html must not be empty",
            hint="pass complete elements, e.g. <p>text</p> or "
            '<media-image source="files/a.png"></media-image>',
        )
    return elements


def _validate_placement(placement: str, anchor: str | None) -> str:
    if placement not in PLACEMENTS:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"invalid placement {placement!r}",
            hint="placement is one of: after, before, append, prepend",
        )
    if placement in RELATIVE_PLACEMENTS and not anchor:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"placement {placement!r} requires an anchor",
            hint="the anchor addresses the block to position relative to; append/prepend need none",
        )
    if placement not in RELATIVE_PLACEMENTS and anchor:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"placement {placement!r} is page-level and takes no anchor",
            hint="use after/before to position relative to an anchored block",
        )
    return placement


def build_block_html(
    tag: str, attributes: dict[str, Any] | None = None, inner_html: str = ""
) -> str:
    """Build `<tag attr="...">inner_html</tag>` for the generic and typed tools.

    Attribute values: `True` → the HAX flag form (`name="name"`), `False`/`None` →
    omitted, dict/list → JSON, everything else → `str(value)`; escaping happens through
    the parse + serialize round trip. `inner_html` is parsed as HTML (slotted children,
    inline markup). A nested `<page-break>` is rejected: it would forge a second segment
    boundary inside the saved body (the envelope is managed by `save_content` alone).
    """
    name = (tag or "").strip().lower()
    if not _ATTR_NAME_RE.match(name):
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"invalid block tag {tag!r}",
            hint="tags are XML names, e.g. p, h2, media-image",
        )
    parsed = strip_envelopes(parse_body(f"<{name}>{inner_html or ''}</{name}>"))
    if not parsed:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"could not build a block for tag {tag!r}",
            hint="inner_html must be HTML content, not an envelope",
        )
    element = parsed[0]
    for descendant in element.iter():
        if descendant.tag == "page-break":
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                "page-break cannot appear inside a block",
                hint="the page-break envelope is managed automatically; pass plain content",
            )
    for attribute_name, value in (attributes or {}).items():
        if not _ATTR_NAME_RE.match(attribute_name):
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                f"invalid attribute name {attribute_name!r}",
                hint="attribute names are XML names: letters, digits, -, _, ., : — "
                "no spaces, quotes or =",
            )
        if value is True:
            element.set(attribute_name, attribute_name)  # HAX boolean flag form
        elif value is False or value is None:
            continue
        elif isinstance(value, dict | list):
            element.set(attribute_name, json.dumps(value, ensure_ascii=False))
        else:
            element.set(attribute_name, str(value))
    return serialize_elements([element])


def _resolve_index(
    elements: list[HtmlElement], anchor: str, occurrence: str | int | None
) -> tuple[int, Block]:
    """Anchor → (index into `elements`, the Block itself)."""
    target = resolve_anchor(to_blocks(elements), anchor, occurrence)
    return target.index, target


async def insert_block(
    client: HaxcmsClient,
    site: str,
    page: str,
    html: str,
    *,
    anchor: str | None = None,
    occurrence: str | int | None = None,
    placement: str = "append",
) -> BlockOpResult:
    """Insert one or more new blocks (parsed from `html`) at the placement position."""
    _validate_placement(placement, anchor)
    inserted = _parse_new_blocks(html)

    def mutate(elements: list[HtmlElement]) -> list[Block]:
        position = _insert_position(elements, placement, anchor, occurrence)
        elements[position:position] = inserted
        return to_blocks(elements)[position : position + len(inserted)]

    return await _run_block_op(client, site, page, "insert_block", mutate)


def _insert_position(
    elements: list[HtmlElement],
    placement: str,
    anchor: str | None,
    occurrence: str | int | None,
) -> int:
    if placement == "append":
        return len(elements)
    if placement == "prepend":
        return 0
    index, _ = _resolve_index(elements, anchor or "", occurrence)
    return index + 1 if placement == "after" else index


async def replace_block(
    client: HaxcmsClient,
    site: str,
    page: str,
    html: str,
    *,
    anchor: str,
    occurrence: str | int | None = None,
) -> BlockOpResult:
    """Replace the anchored block with the block(s) parsed from `html`."""
    replacement = _parse_new_blocks(html)

    def mutate(elements: list[HtmlElement]) -> list[Block]:
        index, _ = _resolve_index(elements, anchor, occurrence)
        elements[index : index + 1] = replacement
        return to_blocks(elements)[index : index + len(replacement)]

    return await _run_block_op(client, site, page, "replace_block", mutate)


async def remove_block(
    client: HaxcmsClient,
    site: str,
    page: str,
    anchor: str,
    occurrence: str | int | None = None,
) -> BlockOpResult:
    """Delete the anchored block; `affected` reports it at its OLD index."""

    def mutate(elements: list[HtmlElement]) -> list[Block]:
        index, removed = _resolve_index(elements, anchor, occurrence)
        del elements[index]
        return [removed]

    return await _run_block_op(client, site, page, "remove_block", mutate)


async def move_block(
    client: HaxcmsClient,
    site: str,
    page: str,
    anchor: str,
    *,
    occurrence: str | int | None = None,
    target_anchor: str | None = None,
    target_occurrence: str | int | None = None,
    placement: str = "append",
) -> BlockOpResult:
    """Move the anchored block to the placement position (relative to `target_anchor`)."""
    _validate_placement(placement, target_anchor)

    def mutate(elements: list[HtmlElement]) -> list[Block]:
        index, _ = _resolve_index(elements, anchor, occurrence)
        element = elements[index]
        del elements[index]
        if placement in RELATIVE_PLACEMENTS:
            # resolve the target AFTER lifting the source: indices have shifted and the
            # source must not match its own target anchor
            target_index, _ = _resolve_index(elements, target_anchor or "", target_occurrence)
            position = target_index + 1 if placement == "after" else target_index
        else:
            position = len(elements) if placement == "append" else 0
        elements.insert(position, element)
        return [to_blocks(elements)[position]]

    return await _run_block_op(client, site, page, "move_block", mutate)


async def update_block_attributes(
    client: HaxcmsClient,
    site: str,
    page: str,
    anchor: str,
    *,
    occurrence: str | int | None = None,
    set: dict[str, Any] | None = None,
    unset: list[str] | None = None,
) -> BlockOpResult:
    """Set and/or unset attributes on the anchored block (tag, children and text kept).

    Values are stringified; HAX boolean attributes want their name as the value
    (`{"card": "card"}` — stored bodies use that form). Unsetting an absent attribute is
    a silent no-op.
    """
    changes = dict(set or {})
    removals = list(unset or [])
    if not changes and not removals:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "nothing to update",
            hint="pass set (attribute -> value) and/or unset (attribute names)",
        )
    for name in [*changes, *removals]:
        if not _ATTR_NAME_RE.match(name):
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                f"invalid attribute name {name!r}",
                hint="attribute names are XML names: letters, digits, -, _, ., : — "
                "no spaces, quotes or =",
            )

    def mutate(elements: list[HtmlElement]) -> list[Block]:
        index, _ = _resolve_index(elements, anchor, occurrence)
        element = elements[index]
        for name, value in changes.items():
            element.set(name, str(value))
        for name in removals:
            element.attrib.pop(name, None)
        return [to_blocks(elements)[index]]

    return await _run_block_op(client, site, page, "update_block_attributes", mutate)


async def set_block_text(
    client: HaxcmsClient,
    site: str,
    page: str,
    anchor: str,
    text: str,
    *,
    occurrence: str | int | None = None,
) -> BlockOpResult:
    """Replace the block's inner text; tag and attributes are kept.

    For slotted blocks (self-check, multiple-choice, grid-plate) only the DEFAULT slot
    content is replaced — children carrying a `slot` attribute survive (the new text
    becomes the element's leading text node; shadow-DOM rendering follows the slot order,
    not the light-DOM one). Markup in `text` is escaped, not parsed.
    """

    def mutate(elements: list[HtmlElement]) -> list[Block]:
        index, _ = _resolve_index(elements, anchor, occurrence)
        element = elements[index]
        slotted = [
            child
            for child in element
            if isinstance(child.tag, str) and child.get("slot") is not None
        ]
        for child in list(element):
            element.remove(child)
        element.text = text or ""
        element.extend(slotted)
        return [to_blocks(elements)[index]]

    return await _run_block_op(client, site, page, "set_block_text", mutate)


def _text_nodes(element: HtmlElement) -> list[tuple[HtmlElement, bool]]:
    """`(node, is_tail)` pairs for every text slot in the subtree, in document order.

    Comment/PI `.text` is skipped (not wrappable content) but their tails are included —
    a tail always renders inside the parent's content.
    """
    pairs: list[tuple[HtmlElement, bool]] = []

    def walk(node: HtmlElement) -> None:
        if isinstance(node.tag, str):
            pairs.append((node, False))
        for child in node:
            walk(child)
            pairs.append((child, True))

    walk(element)
    return pairs


def _wrap_first_occurrence(element: HtmlElement, needle: str, href: str, new_tab: bool) -> bool:
    """Wrap the first document-order occurrence of `needle` in `<a href>`; True if done."""
    for node, is_tail in _text_nodes(element):
        content = node.tail if is_tail else node.text
        if not content or needle not in content:
            continue
        before, _, after = content.partition(needle)
        link = lxml_html.Element("a")
        link.set("href", href)
        if new_tab:
            link.set("target", "_blank")
        link.text = needle
        link.tail = after
        if is_tail:
            parent = node.getparent()
            if parent is None:  # unreachable: tail nodes in a subtree always have a parent
                continue
            node.tail = before
            parent.insert(parent.index(node) + 1, link)
        else:
            node.text = before
            node.insert(0, link)
        return True
    return False


async def wrap_text_with_link(
    client: HaxcmsClient,
    site: str,
    page: str,
    anchor: str,
    text: str,
    url: str,
    *,
    occurrence: str | int | None = None,
    new_tab: bool = False,
) -> BlockOpResult:
    """Wrap the first occurrence of `text` INSIDE the anchored block in `<a href>`.

    The search is case-sensitive over the block's text nodes in document order and
    splits the node around the match, so surrounding markup stays untouched. `new_tab`
    adds `target="_blank"`.
    """
    needle = text or ""
    if not needle.strip():
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "text must not be empty",
            hint="pass the exact text inside the block to turn into a link",
        )
    href = (url or "").strip()
    if not href:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT, "url must not be empty", hint="e.g. https://example.com"
        )

    def mutate(elements: list[HtmlElement]) -> list[Block]:
        index, target = _resolve_index(elements, anchor, occurrence)
        if not _wrap_first_occurrence(elements[index], needle, href, new_tab):
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                f"text {needle!r} not found inside the anchored block",
                hint="the search is case-sensitive and limited to the anchored block",
                details={
                    "block": {
                        "index": target.index,
                        "tag": target.tag,
                        "preview": target.preview,
                    }
                },
            )
        return [to_blocks(elements)[index]]

    return await _run_block_op(client, site, page, "wrap_text_with_link", mutate)
