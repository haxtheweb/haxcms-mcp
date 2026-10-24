"""Block serializer (PLAN Phase 4 T4.2; §2.3).

Joins block HTML with newlines. Attribute quoting is double quotes (lxml's html
serializer); boolean attributes carry whatever value the tool gave (`card="card"`), which
is what HAX treats as truth and what survives the save/page-break round trip.
"""

from __future__ import annotations

from lxml.html import HtmlElement

from haxcms_mcp.models.content import Block
from haxcms_mcp.services.content.parser import element_html


def serialize(blocks: list[Block]) -> str:
    """Serialise Block models (the §2.3 signature) — newline-joined outer HTML."""
    return "\n".join(block.html for block in blocks)


def serialize_elements(elements: list[HtmlElement]) -> str:
    """Serialise the working element list (block operations mutate elements directly)."""
    return "\n".join(element_html(element) for element in elements)
