"""Block parser (PLAN Phase 4 T4.2; §2.3).

`lxml.html` fragment parsing: top-level ELEMENT children are the blocks; stray top-level
text is wrapped in `<p>`; top-level comments and processing instructions are dropped
(HAX-authored bodies carry none, and the save-time sanitizer strips their kind anyway).

`parse_body` returns the working `HtmlElement` list the block operations mutate;
`to_blocks` materialises the `Block` models tools return. Serialization lives in
`services/content/serializer.py`.
"""

from __future__ import annotations

import re

from lxml import html as lxml_html
from lxml.html import HtmlElement

from haxcms_mcp.models.content import Block

_WHITESPACE = re.compile(r"\s+")

PREVIEW_LENGTH = 80


def normalize_text(value: str) -> str:
    """Collapse every whitespace run to one space (the Block.text normalisation)."""
    return _WHITESPACE.sub(" ", value or "").strip()


def element_html(element: HtmlElement) -> str:
    """Outer HTML of one element (lxml's html serializer: double quotes, voids bare)."""
    return str(lxml_html.tostring(element, encoding=str))


def _wrap_text(text: str) -> HtmlElement:
    paragraph = lxml_html.Element("p")
    paragraph.text = text.strip()
    return paragraph


def parse_body(html: str) -> list[HtmlElement]:
    """Parse a stored page body into its top-level block elements (tails detached)."""
    if not html or not html.strip():
        return []
    wrapper = lxml_html.fragment_fromstring(html, create_parent="div")
    elements: list[HtmlElement] = []
    pending = wrapper.text or ""
    for child in wrapper:
        tail = child.tail or ""
        child.tail = None
        if isinstance(child.tag, str):
            if pending.strip():
                elements.append(_wrap_text(pending))
            pending = tail
            elements.append(child)
        else:
            # dropped comment/PI: its tail text is still stray content — accumulate
            pending += tail
    if pending.strip():
        elements.append(_wrap_text(pending))
    return elements


def to_blocks(elements: list[HtmlElement]) -> list[Block]:
    """Materialise the Block models (index, tag, attributes, text, html, preview)."""
    blocks: list[Block] = []
    for index, element in enumerate(elements):
        text = normalize_text("".join(element.itertext()))
        rendered = element_html(element)
        blocks.append(
            Block(
                index=index,
                tag=str(element.tag),
                attributes=dict(element.attrib),
                text=text,
                html=rendered,
                preview=(text or rendered)[:PREVIEW_LENGTH],
            )
        )
    return blocks


def parse_blocks(html: str) -> list[Block]:
    """`parse_body` + `to_blocks`: the read path for get_page_content/get_page_blocks."""
    return to_blocks(parse_body(html))
