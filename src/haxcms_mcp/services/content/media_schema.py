"""Media schema for content saves (PLAN Phase 4 T4.2; §2.3, API-REF §5.2).

saveNode fills `metadata.images` / `metadata.videos` from the optional `schema` array for
exactly four tags: `media-image[source]`, `video-player[source]` (videos), `img[src]`,
`a11y-gif-player[src]` (images). Build it from the parsed body on every save so pages keep
their media metadata (card images, theming, feeds).
"""

from __future__ import annotations

from typing import Any

from lxml.html import HtmlElement

SOURCE_ATTR_BY_TAG = {
    "media-image": "source",
    "video-player": "source",
    "img": "src",
    "a11y-gif-player": "src",
}


def build_media_schema(elements: list[HtmlElement]) -> list[dict[str, Any]]:
    """`[{tag, properties: {source|src: url}}]` for every media node in the body.

    Descendants are scanned too (an `img` inside a `<p>`, a `media-image` in a grid-plate
    slot); duplicate (tag, url) pairs collapse.
    """
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for element in elements:
        for node in element.iter():
            if not isinstance(node.tag, str):
                continue
            attr = SOURCE_ATTR_BY_TAG.get(node.tag)
            if attr is None:
                continue
            value = node.get(attr)
            if not value or (node.tag, value) in seen:
                continue
            seen.add((node.tag, value))
            entries.append({"tag": node.tag, "properties": {attr: value}})
    return entries
