"""Page Break envelope builder and content save (PLAN Phase 4 T4.1; API-REF §5.2).

Facts verified against the 26.8.1 source (`saveNode.js`, `HAXCMS.pageBreakParser` ~L4334,
`parse_attributes` ~L4318, `content.js updateContent`; recorded in PROGRESS.md):

* The parser yields segments only for `<page-break ...>...</page-break><content>` — a body
  WITHOUT a page-break produces ZERO segments: nothing is written and the call still
  returns 200 (silent no-op).
* `parse_attributes` accepts `name="value"` pairs and turns value-less attributes into
  `null`, which fails saveNode's truthiness check for `published`/`locked` — every flag is
  therefore emitted WITH its canonical value (`published="published"`, `locked="locked"`,
  `hide-in-menu="hide-in-menu"`, `override-pathauto="true"`).
* ABSENCE means false for `published`, `locked`, `hide-in-menu`, `override-pathauto`, and
  absence DELETES `parent`, `page-type`, `related-items`, `image`, `tags`, `icon`,
  `accent-color`, `link-url`, `link-target` and `developer-theme`; an absent `description`
  is regenerated from the first 200 characters of the stripped body. The envelope is thus
  ALWAYS built from the item's current record so a content save never clears details.
* Under Pathauto with `override-pathauto` absent the slug is regenerated from the title —
  even when a `slug` attribute was sent. `depth`/`order` are parseInt'd when present and
  left untouched when absent; they are emitted always to keep saves deterministic.
* `developer-theme` must be a known theme key (else the page theme is DELETED); saveNode
  stores the full theme object (with `.key`) back into `metadata.theme`.
* `PATCH content/{idOrSlug}` (updateContent) accepts `{site:{name}, body, schema?, details?}`
  (also `content` or `node.body` for the body), forces `node.id` to the resolved item and
  forwards to saveNode; the response `data` is the updated item record.
* Values are HTML-escaped into double quotes (the parser's value class excludes `"`).
  `title` and `description` are entity-decoded + tag-stripped upstream; other attributes
  keep their escaped form.
"""

from __future__ import annotations

from html import escape
from typing import Any

from haxcms_mcp.client import HaxcmsClient, site_api
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.item import Item


def _attr(name: str, value: Any) -> str:
    return f'{name}="{escape(str(value), quote=True)}"'


def build_page_break(item: Item) -> str:
    """The `<page-break>` envelope reproducing ALL of `item`'s current details (§5.2).

    Attribute order follows API-REF §5.2's example, with `link-url`/`link-target` after
    `accent-color` (saveNode deletes both when absent, so they must ride along).
    """
    metadata = item.metadata
    attrs: list[str] = [
        _attr("item-id", item.id),
        _attr("title", item.title),
        _attr("slug", item.slug),
        _attr("path", item.slug),
    ]
    if item.parent:
        attrs.append(_attr("parent", item.parent))
    # boolean flags: absence means FALSE upstream, so emit only when set
    if item.published:
        attrs.append('published="published"')
    if metadata.locked:
        attrs.append('locked="locked"')
    if metadata.hide_in_menu:
        attrs.append('hide-in-menu="hide-in-menu"')
    # absence DELETES these upstream: emit whenever the record has them
    if metadata.page_type:
        attrs.append(_attr("page-type", metadata.page_type))
    tags = item.tags if item.tags else metadata.tags
    if tags:
        attrs.append(_attr("tags", ",".join(str(tag) for tag in tags)))
    if metadata.related_items:
        attrs.append(
            _attr("related-items", ",".join(str(entry) for entry in metadata.related_items))
        )
    if metadata.image:
        attrs.append(_attr("image", metadata.image))
    if metadata.icon:
        attrs.append(_attr("icon", metadata.icon))
    if metadata.accent_color:
        attrs.append(_attr("accent-color", metadata.accent_color))
    # not modelled fields (yet) but saveNode deletes them when absent — preserve from extra
    link_url = metadata.extra.get("linkUrl")
    if link_url:
        attrs.append(_attr("link-url", link_url))
    link_target = metadata.extra.get("linkTarget")
    if link_target:
        attrs.append(_attr("link-target", link_target))
    if item.description:
        attrs.append(_attr("description", item.description))
    theme = metadata.theme
    theme_key = theme.get("key") if isinstance(theme, dict) else theme
    if theme_key:
        attrs.append(_attr("developer-theme", theme_key))
    attrs.append(_attr("depth", item.indent))
    attrs.append(_attr("order", item.order))
    if metadata.override_pathauto:
        attrs.append('override-pathauto="true"')
    return "<page-break " + " ".join(attrs) + "></page-break>"


async def save_content(
    client: HaxcmsClient,
    site: str,
    item: Item,
    body_html: str,
    *,
    schema: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> Item:
    """Prepend the envelope to `body_html` and PATCH content; returns the updated item.

    `item` MUST be a fresh record (get_item) — the envelope replays its details, and a
    stale one would roll them back. `schema` (list of `{tag, properties}`) fills
    `metadata.images`/`metadata.videos` for img / a11y-gif-player / media-image /
    video-player; send it whenever the body carries those tags. Each save is one git
    commit ("Page details updated: <title> (<id>)").
    """
    if not item.id:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "cannot save content for an item without an id",
            hint="fetch the page with get_page/find_page first",
        )
    body = build_page_break(item) + body_html
    data = await site_api.patch_content(client, site, item.id, body, schema=schema, details=details)
    return Item.from_api(data)
