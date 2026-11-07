"""Client-side content filtering (security audit, defence in depth).

Pure checks on `services/content/safety.py` and `middleware/limits.py`, then the tools
through the in-memory Client against the stateful respx fake from the content-tool tests:
refused URL schemes never reach a PATCH, scripts and handlers are stripped before it, and
oversized arguments are refused before any HTTP happens.
"""

from __future__ import annotations

import pytest
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.middleware.limits import check_argument_sizes
from haxcms_mcp.server import build_server
from haxcms_mcp.services.content.blocks import build_block_html
from haxcms_mcp.services.content.parser import parse_body
from haxcms_mcp.services.content.safety import (
    check_url_attribute,
    is_allowed_url,
    sanitize_elements,
    url_scheme,
)
from haxcms_mcp.services.content.serializer import serialize_elements
from tests.unit.test_p04_content_tools import (
    FakeSite,
    make_settings,
    mock_auth,
    mock_catalog_offline,
)

pytestmark = pytest.mark.unit


# --- URL scheme allow-list -----------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/a",
        "http://example.com",
        "HTTPS://EXAMPLE.COM",
        "mailto:someone@example.com",
        "tel:+15555551234",
        "files/image.png",
        "/sites/demo/files/a.png",
        "../other-page",
        "#anchor",
        "?query=1",
        "//cdn.example.com/x.js",  # protocol-relative inherits the page's http(s)
        "",
    ],
)
def test_allowed_urls(value: str) -> None:
    assert is_allowed_url(value)
    check_url_attribute("href", value)  # does not raise


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "  javascript:alert(1)",
        "\tjavascript:alert(1)",
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        "java\x00script:alert(1)",
        "&#106;avascript:alert(1)",
        "&#x6A;avascript:alert(1)",
        "&#106;&#97;&#118;&#97;script:alert(1)",
        "javascript&colon;alert(1)",
        "java&Tab;script:alert(1)",
        "&amp;#106;avascript:alert(1)",  # double-encoded
        "vbscript:MsgBox(1)",
        "VBScript:MsgBox(1)",
        "data:text/html,<script>alert(1)</script>",
        "data:image/svg+xml;base64,PHN2Zz4=",
        "data:image/png;base64,iVBORw0KGgo=",  # even raster data: is refused as an argument
        "livescript:alert(1)",
        "ftp://example.com/file",
        "file:///etc/passwd",
    ],
)
def test_refused_urls(value: str) -> None:
    assert not is_allowed_url(value)
    with pytest.raises(HaxcmsMcpError) as info:
        check_url_attribute("href", value)
    assert info.value.code is ErrorCode.INVALID_ARGUMENT
    assert "refused URL scheme" in info.value.message
    assert "javascript:" in (info.value.hint or "")


def test_url_scheme_normalises_like_a_browser() -> None:
    assert url_scheme("Java\tScript:x") == "javascript"
    assert url_scheme("&#106;avascript:x") == "javascript"
    assert url_scheme("files/a.png") is None
    assert url_scheme("C:/not/a/url") == "c"  # unknown schemes are refused too


# --- build_block_html / typed tool attributes ---------------------------------------------


def test_build_block_html_refuses_script_scheme_in_url_attributes() -> None:
    for name in ("source", "link", "href", "src", "thumbnail-src", "image-src", "url"):
        with pytest.raises(HaxcmsMcpError) as info:
            build_block_html("media-image", {name: "javascript:alert(1)", "alt": "x"})
        assert info.value.code is ErrorCode.INVALID_ARGUMENT, name


def test_build_block_html_keeps_scheme_shaped_text_attributes() -> None:
    # HAX attribute values are routinely "scheme-shaped" (icon="icons:check")
    html = build_block_html("simple-icon", {"icon": "icons:check", "title": "Note: hi"})
    assert 'icon="icons:check"' in html


def test_build_block_html_strips_scripts_and_handlers_from_inner_html() -> None:
    html = build_block_html(
        "div",
        {"class": "x"},
        '<p onmouseover="alert(1)">Hi</p><script>alert(2)</script><img src="x" onerror="alert(3)">',
    )
    assert "<script" not in html
    assert "onerror" not in html and "onmouseover" not in html
    assert 'class="x"' in html
    assert "<p>Hi</p>" in html


def test_build_block_html_refuses_event_handler_attributes() -> None:
    for name in ("onclick", "ONLOAD", "onerror"):
        with pytest.raises(HaxcmsMcpError) as info:
            build_block_html("p", {name: "alert(1)"}, "Hi")
        assert info.value.code is ErrorCode.INVALID_ARGUMENT
        assert "event-handler" in info.value.message


# --- sanitize_elements ----------------------------------------------------------------------


def _sanitize(html: str) -> str:
    return serialize_elements(sanitize_elements(parse_body(html)))


def test_sanitize_drops_top_level_and_nested_scripts() -> None:
    out = _sanitize("<script>a()</script><p>One <script>b()</script>two.</p><h2>H</h2>")
    assert "<script" not in out
    assert "<p>One two.</p>" in out
    assert "<h2>H</h2>" in out


def test_sanitize_drops_event_handlers_case_insensitively() -> None:
    out = _sanitize('<p onClick="x()" ONLOAD="y()" data-on="keep" title="t">T</p>')
    assert "onclick" not in out.lower().replace("data-on", "")
    assert "onload" not in out.lower()
    assert 'data-on="keep"' in out
    assert 'title="t"' in out


def test_sanitize_drops_script_urls_but_keeps_raster_data_images() -> None:
    out = _sanitize(
        '<a href="javascript:alert(1)">x</a>'
        '<media-image source="data:text/html,evil" alt="a"></media-image>'
        '<img src="data:image/png;base64,iVBORw0KGgo=">'
        '<a href="https://example.com">ok</a>'
    )
    assert "javascript:" not in out
    assert "data:text/html" not in out
    assert 'src="data:image/png;base64,iVBORw0KGgo="' in out
    assert 'href="https://example.com"' in out


def test_sanitize_keeps_everything_else() -> None:
    body = (
        '<video-player source="https://youtu.be/x" media-title="T"></video-player>\n'
        '<self-check title="Check"><p slot="question">Which?</p></self-check>\n'
        "<p>Plain <strong>text</strong> &amp; entities.</p>"
    )
    assert _sanitize(body) == body


# --- tools through the server ---------------------------------------------------------------


@respx.mock
async def test_add_link_refuses_javascript_url_before_any_http() -> None:
    mock_auth()
    fake = FakeSite("<p>Watch it now.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match=r"\[INVALID_ARGUMENT\].*refused URL scheme"):
            await client.call_tool(
                "add_link",
                {"page": "songlines", "anchor": "Watch", "text": "now", "url": "javascript:x"},
            )
    assert fake.gets == 0 and fake.patches == []


@respx.mock
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("add_image", {"source": "javascript:alert(1)", "alt": "a"}),
        ("add_image", {"source": "files/a.png", "alt": "a", "link": "vbscript:x"}),
        ("add_video", {"source": "data:text/html,<script>1</script>"}),
        ("add_video", {"source": "https://youtu.be/x", "thumbnail": "javascript:x"}),
        ("add_audio", {"source": "JAVASCRIPT:alert(1)"}),
    ],
)
async def test_typed_media_tools_refuse_script_schemes(tool: str, args: dict[str, str]) -> None:
    mock_auth()
    mock_catalog_offline()
    fake = FakeSite("<p>One.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match=r"\[INVALID_ARGUMENT\].*refused URL scheme"):
            await client.call_tool(tool, {"page": "songlines", **args})
    assert fake.patches == []


@respx.mock
async def test_update_block_refuses_script_urls_and_handlers() -> None:
    mock_auth()
    fake = FakeSite('<media-image source="files/a.png" alt="a"></media-image>')
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        for bad in (
            {"source": "javascript:alert(1)"},
            {"href": "&#106;avascript:alert(1)"},
            {"src": "data:text/html,x"},
            {"onclick": "alert(1)"},
        ):
            with pytest.raises(ToolError, match=r"\[INVALID_ARGUMENT\]"):
                await client.call_tool(
                    "update_block", {"page": "songlines", "anchor": "media-image", "set": bad}
                )
        # and a legitimate change still goes through
        await client.call_tool(
            "update_block",
            {"page": "songlines", "anchor": "media-image", "set": {"source": "files/b.png"}},
        )
    assert len(fake.patches) == 1
    assert 'source="files/b.png"' in fake.last_body


@respx.mock
async def test_set_page_content_strips_scripts_and_handlers_before_patch() -> None:
    mock_auth()
    fake = FakeSite("<p>Old.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        data = (
            await client.call_tool(
                "set_page_content",
                {
                    "page": "songlines",
                    "html": '<script>evil()</script><p onclick="x()">Kept <em>rich</em>.</p>'
                    '<a href="javascript:alert(1)">bad</a><a href="https://x.y">good</a>',
                },
            )
        ).data
    body = fake.last_body
    assert "<script" not in body and "onclick" not in body and "javascript:" not in body
    assert "<p>Kept <em>rich</em>.</p>" in body
    assert '<a href="https://x.y">good</a>' in body
    assert "<a>bad</a>" in body  # the attribute is dropped, the text survives
    assert all(block["tag"] != "script" for block in data["blocks"])


@respx.mock
async def test_replace_block_strips_scripts_and_handlers_before_patch() -> None:
    mock_auth()
    fake = FakeSite("<p>One.</p><p>Two.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        await client.call_tool(
            "replace_block",
            {
                "page": "songlines",
                "anchor": "Two",
                "html": '<h2 onmouseover="x()">Two</h2><script src="https://e.v/x.js"></script>',
            },
        )
    assert fake.last_body.endswith("</page-break><p>One.</p>\n<h2>Two</h2>")
    assert "<script" not in fake.last_body and "onmouseover" not in fake.last_body


@respx.mock
async def test_replace_block_with_only_a_script_is_rejected_as_empty() -> None:
    mock_auth()
    fake = FakeSite("<p>One.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="block html must not be empty"):
            await client.call_tool(
                "replace_block",
                {"page": "songlines", "anchor": "One", "html": "<script>x()</script>"},
            )
    assert fake.patches == []


# --- size cap -------------------------------------------------------------------------------


def test_check_argument_sizes_measures_utf8_of_content_arguments_only() -> None:
    check_argument_sizes({"html": "a" * 10, "page": "x" * 1000}, max_bytes=10)
    with pytest.raises(HaxcmsMcpError) as info:
        check_argument_sizes({"inner_html": "é" * 6}, max_bytes=10)  # 12 bytes
    assert info.value.code is ErrorCode.INVALID_ARGUMENT
    assert "12 bytes" in info.value.message
    for name in ("text", "content_html", "question_html", "text_or_html"):
        with pytest.raises(HaxcmsMcpError):
            check_argument_sizes({name: "x" * 11}, max_bytes=10)
    check_argument_sizes({"title": "x" * 11, "alt": "y" * 11}, max_bytes=10)


@respx.mock
async def test_oversized_html_is_refused_before_any_http() -> None:
    mock_auth()
    fake = FakeSite("<p>Old.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo", max_html_bytes=64))
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match=r"\[INVALID_ARGUMENT\].*HAXCMS_MCP_MAX_HTML_BYTES"):
            await client.call_tool(
                "set_page_content", {"page": "songlines", "html": "<p>" + "x" * 100 + "</p>"}
            )
        with pytest.raises(ToolError, match=r"\[INVALID_ARGUMENT\]"):
            await client.call_tool(
                "set_block_text", {"page": "songlines", "anchor": "Old", "text": "y" * 100}
            )
        # under the cap: runs normally
        await client.call_tool("set_page_content", {"page": "songlines", "html": "<p>ok</p>"})
    assert len(fake.patches) == 1  # only the in-cap call reached HAXcms


def test_default_cap_is_two_megabytes() -> None:
    assert make_settings().max_html_bytes == 2 * 1024 * 1024
