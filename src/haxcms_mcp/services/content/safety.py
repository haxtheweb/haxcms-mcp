"""Client-side content filtering (defence in depth, security audit).

HAXcms sanitises every saved body itself (CONTEXT.md, "Sanitisation") and remains the
authority. This module only makes sure the MCP server never *sends* the obvious script
vectors in the first place, so a compromised or confused agent cannot rely on the server's
sanitiser being the single line of defence:

* URL-bearing tool arguments (`href`, `src`, `source`, `link`, `url`, `*-src`,
  `*-source`) accept `http`, `https`, `mailto`, `tel` and relative paths only.
  `javascript:`, `data:`, `vbscript:` and any other scheme are refused with
  INVALID_ARGUMENT, however they are cased, padded with whitespace/control characters,
  or written as HTML entities. Inline `data:` images belong in `upload_file`.
* Raw HTML (`replace_block`, `set_page_content`, `add_block` inner HTML) has `<script>`
  elements and `on*=` event-handler attributes removed before the PATCH. URL attributes
  with a refused scheme are dropped from raw HTML rather than failing the whole call;
  raster `data:image/*` URIs are kept there, as HAXcms's own sanitiser keeps them.
  Everything else is kept as the agent wrote it.
"""

from __future__ import annotations

import html as html_lib
import re
from typing import Any

from lxml.html import HtmlElement

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

ALLOWED_URL_SCHEMES = frozenset({"http", "https", "mailto", "tel"})
URL_ATTRIBUTE_NAMES = frozenset({"href", "src", "source", "link", "url", "action", "poster"})
URL_ATTRIBUTE_SUFFIXES = ("-src", "-source", "-href", "-url")

# raster image types HAXcms itself keeps in data: URIs (sanitizeContent.js)
_RASTER_DATA_RE = re.compile(r"^data:image/(png|jpeg|gif|webp|avif|bmp)[;,]")
# RFC 3986 scheme production, after whitespace/control stripping and entity decoding
_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.\-]*):")
# browsers strip ASCII whitespace and C0 controls anywhere in the scheme part of a URL,
# so "java\tscript:" and "&#106;avascript:" both run — normalise the same way before matching
_STRIP_RE = re.compile(r"[\x00-\x20\x7f]+")


def is_url_attribute(name: str) -> bool:
    """Whether an attribute name is one HAX elements and browsers read as a URL."""
    lowered = name.lower()
    return lowered in URL_ATTRIBUTE_NAMES or lowered.endswith(URL_ATTRIBUTE_SUFFIXES)


def url_scheme(value: str) -> str | None:
    """The normalised scheme of `value`, or None for relative / protocol-relative URLs."""
    decoded = html_lib.unescape(value or "")
    # entities may themselves spell more entities (double encoding); one more pass is cheap
    decoded = html_lib.unescape(decoded)
    normalised = _STRIP_RE.sub("", decoded).lower()
    match = _SCHEME_RE.match(normalised)
    return match.group(1) if match else None


def is_allowed_url(value: str) -> bool:
    scheme = url_scheme(value)
    return scheme is None or scheme in ALLOWED_URL_SCHEMES


def _is_raster_data_url(value: str) -> bool:
    normalised = _STRIP_RE.sub("", html_lib.unescape(value or "")).lower()
    return bool(_RASTER_DATA_RE.match(normalised))


def check_url_attribute(name: str, value: Any) -> None:
    """Refuse a URL attribute whose scheme is not on the allow-list."""
    if not isinstance(value, str) or is_allowed_url(value):
        return
    scheme = url_scheme(value)
    raise HaxcmsMcpError(
        ErrorCode.INVALID_ARGUMENT,
        f"{name} uses the refused URL scheme {scheme!r}",
        hint="links and media sources must be http(s), mailto, tel, or a site-relative "
        "path such as files/image.png; javascript:, data: and vbscript: URLs are refused "
        "(upload inline images with upload_file first)",
        details={"attribute": name, "scheme": scheme},
    )


def check_url_attributes(attributes: dict[str, Any] | None) -> None:
    """`check_url_attribute` over every URL-bearing name in an attribute mapping."""
    for name, value in (attributes or {}).items():
        if is_url_attribute(name):
            check_url_attribute(name, value)


def _is_script(element: HtmlElement) -> bool:
    return isinstance(element.tag, str) and element.tag.lower() == "script"


def _scrub_attributes(element: HtmlElement) -> None:
    for name in list(element.attrib):
        lowered = name.lower()
        if lowered.startswith("on"):
            del element.attrib[name]
        elif is_url_attribute(lowered):
            value = element.attrib[name]
            if not is_allowed_url(value) and not _is_raster_data_url(value):
                del element.attrib[name]


def sanitize_elements(elements: list[HtmlElement]) -> list[HtmlElement]:
    """Drop `<script>` elements and `on*` attributes from the working element list.

    Mutates the elements in place and returns the surviving top-level list. Tail text of a
    removed nested `<script>` is kept (`drop_tree`), so surrounding prose is not lost.
    """
    kept: list[HtmlElement] = []
    for element in elements:
        if _is_script(element):
            continue
        for node in list(element.iter()):
            if not isinstance(node.tag, str):
                continue  # comments / processing instructions
            if node is not element and _is_script(node):
                node.drop_tree()
                continue
            _scrub_attributes(node)
        kept.append(element)
    return kept
