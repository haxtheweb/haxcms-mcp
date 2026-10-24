"""Unit tests for the content tools (PLAN Phase 4 T4.5).

Two layers: `build_block_html` as a pure function (escaping, flag form, JSON values,
validation), then the registered tools through an in-memory Client against the stateful
respx fake from the block-ops tests — including the add_block contract that catalog
validation rejects bad tags/attributes BEFORE any content HTTP happens.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError
from lxml import html as lhtml

from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.server import build_server
from haxcms_mcp.services.content.blocks import build_block_html

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
ITEMS_RE = r".*/_sites/demo/x/api/v1/items/[^/]+(\?|$)"
CONTENT_RE = r".*/_sites/demo/x/api/v1/content/[^/]+(\?|$)"
BLOCKS_RE = r".*/_sites/demo/x/api/v1/blocks/[a-z0-9-]+(\?|$)"
SCHEMAS_RE = r".*/_sites/demo/x/api/v1/schemas(\?|$)"
CE_RE = r".*/_sites/demo/x/api/v1/custom-elements/[a-z0-9-]+$"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

RECORD: dict[str, Any] = {
    "id": "item-1",
    "title": "Songlines",
    "slug": "songlines",
    "metadata": {"published": True},
}


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass", **kwargs)  # type: ignore[arg-type]


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"status": 200, "jwt": "jwt-1"},
            headers={"set-cookie": "haxcms_refresh_token=r1; Path=/; HttpOnly"},
        )
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def mock_catalog_offline() -> None:
    """The live merge degrades silently: every catalog route answers 404."""
    offline = httpx.Response(404, json={"status": 404, "data": {"message": "Not found"}})
    respx.get(url__regex=BLOCKS_RE).mock(return_value=offline)
    respx.get(url__regex=SCHEMAS_RE).mock(return_value=offline)
    respx.get(url__regex=CE_RE).mock(return_value=offline)


class FakeSite:
    """Stateful item/content endpoints; counts reads so validate-before-fetch is provable."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.gets = 0
        self.patches: list[dict[str, Any]] = []

    def install(self) -> None:
        def get_item(request: httpx.Request) -> httpx.Response:
            self.gets += 1
            data = dict(RECORD)
            if "include=content" in str(request.url):
                data["content"] = self.body
            return httpx.Response(200, json={"status": 200, "data": data})

        def patch_content(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            self.patches.append(payload)
            body = str(payload["body"])
            marker = "></page-break>"
            # upstream pageBreakParser: the stored content is what follows the envelope
            self.body = body.split(marker, 1)[1] if marker in body else body
            return httpx.Response(200, json={"status": 200, "data": dict(RECORD)})

        respx.get(url__regex=ITEMS_RE).mock(side_effect=get_item)
        respx.patch(url__regex=CONTENT_RE).mock(side_effect=patch_content)

    @property
    def last_body(self) -> str:
        return str(self.patches[-1]["body"])

    @property
    def last_schema(self) -> Any:
        return self.patches[-1].get("schema")


# --- build_block_html (pure) ----------------------------------------------------------------


def test_build_block_html_text_and_slotted_children() -> None:
    assert build_block_html("p", None, "Hello prairie") == "<p>Hello prairie</p>"
    html = build_block_html("self-check", {"title": "Check"}, '<p slot="question">Which?</p>')
    assert html == '<self-check title="Check"><p slot="question">Which?</p></self-check>'


def test_build_block_html_flag_and_omitted_values() -> None:
    html = build_block_html(
        "media-image", {"card": True, "source": "files/a.png", "size": 42, "alt": None, "x": False}
    )
    # True -> HAX flag form, False/None omitted, numbers stringified
    assert html == '<media-image card="card" source="files/a.png" size="42"></media-image>'


def test_build_block_html_json_values_round_trip() -> None:
    events = [{"heading": "Start", "details": "Say & see"}]
    html = build_block_html("lrndesign-timeline", {"events": events})
    element = lhtml.fragment_fromstring(html)
    assert json.loads(element.get("events") or "") == events


def test_build_block_html_escapes_text_content() -> None:
    assert build_block_html("p", None, "5 < 6 & 7") == "<p>5 &lt; 6 &amp; 7</p>"


def test_build_block_html_rejects_invalid_tag() -> None:
    for bad in ["", "   ", "bad tag", "media image", "<p>"]:
        with pytest.raises(HaxcmsMcpError) as info:
            build_block_html(bad)
        assert info.value.code is ErrorCode.INVALID_ARGUMENT, bad
        assert "invalid block tag" in info.value.message, bad


def test_build_block_html_rejects_invalid_attribute_name() -> None:
    for bad in ["bad name", 'q"', "a=b"]:
        with pytest.raises(HaxcmsMcpError) as info:
            build_block_html("p", {bad: "x"})
        assert info.value.code is ErrorCode.INVALID_ARGUMENT, bad


def test_build_block_html_rejects_nested_page_break() -> None:
    with pytest.raises(HaxcmsMcpError) as info:
        build_block_html("div", None, '<page-break title="Evil"></page-break><p>Kept.</p>')
    assert info.value.code is ErrorCode.INVALID_ARGUMENT
    assert "page-break" in info.value.message


# --- read tools ------------------------------------------------------------------------------


@respx.mock
async def test_get_page_content_tool() -> None:
    mock_auth()
    FakeSite("<p>One.</p><p>Two.</p>").install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        data = (await client.call_tool("get_page_content", {"page": "songlines"})).data
    assert isinstance(data, dict)
    assert set(data) == {"item", "html", "blocks"}
    assert data["html"] == "<p>One.</p><p>Two.</p>"
    assert data["item"]["title"] == "Songlines"
    assert [(block["index"], block["tag"], block["text"]) for block in data["blocks"]] == [
        (0, "p", "One."),
        (1, "p", "Two."),
    ]


@respx.mock
async def test_get_page_blocks_tool() -> None:
    mock_auth()
    FakeSite("<p>One.</p><h2>Two</h2>").install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        data = (await client.call_tool("get_page_blocks", {"page": "songlines"})).data
    assert isinstance(data, dict)
    assert data["count"] == 2
    assert [block["tag"] for block in data["blocks"]] == ["p", "h2"]


@respx.mock
async def test_set_page_content_tool_envelope_and_schema() -> None:
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
                    "html": '<media-image source="files/a.png"></media-image><p>New.</p>',
                },
            )
        ).data
    assert isinstance(data, dict)
    assert [block["tag"] for block in data["blocks"]] == ["media-image", "p"]
    assert fake.last_body.count("<page-break") == 1
    assert fake.last_schema == [{"tag": "media-image", "properties": {"source": "files/a.png"}}]


# --- add_block -------------------------------------------------------------------------------


@respx.mock
async def test_add_block_validates_saves_and_reports() -> None:
    mock_auth()
    mock_catalog_offline()
    fake = FakeSite("<p>One.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        data = (
            await client.call_tool(
                "add_block",
                {
                    "page": "songlines",
                    "tag": "media-image",
                    "attributes": {"source": "files/a.png", "card": True, "alt": "A path"},
                },
            )
        ).data
    assert isinstance(data, dict)
    assert data["operation"] == "insert_block"
    assert data["saved"] is True
    assert data["site"] == "demo"
    assert data["page_id"] == "item-1"
    assert data["page_slug"] == "songlines"
    assert data["block_count"] == 2
    assert [(block["index"], block["tag"]) for block in data["affected"]] == [(1, "media-image")]
    assert fake.body == (
        '<p>One.</p>\n<media-image source="files/a.png" card="card" alt="A path"></media-image>'
    )
    assert fake.last_schema == [{"tag": "media-image", "properties": {"source": "files/a.png"}}]


@respx.mock
async def test_add_block_native_tag_after_anchor() -> None:
    mock_auth()
    fake = FakeSite("<p>Alpha</p><p>Beta</p><p>Alpha</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        # native tags validate without any catalog HTTP at all
        data = (
            await client.call_tool(
                "add_block",
                {
                    "page": "songlines",
                    "tag": "h2",
                    "attributes": {},
                    "inner_html": "X",
                    "anchor": "Alpha",
                    "occurrence": "last",
                    "placement": "after",
                },
            )
        ).data
    assert isinstance(data, dict)
    assert data["block_count"] == 4
    assert fake.body == "<p>Alpha</p>\n<p>Beta</p>\n<p>Alpha</p>\n<h2>X</h2>"


@respx.mock
async def test_add_block_unknown_tag_rejected_before_content_http() -> None:
    mock_auth()
    mock_catalog_offline()
    fake = FakeSite("<p>One.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "add_block",
                {"page": "songlines", "tag": "media-img", "attributes": {}},
            )
    message = str(excinfo.value)
    assert "[INVALID_ARGUMENT]" in message
    assert "unknown block tag" in message
    assert "media-image" in message  # the closest-match hint names the real tag
    assert fake.gets == 0 and fake.patches == []  # validation ran before any fetch


@respx.mock
async def test_add_block_bad_attributes_rejected_before_content_http() -> None:
    mock_auth()
    mock_catalog_offline()
    fake = FakeSite("<p>One.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "add_block",
                {"page": "songlines", "tag": "media-image", "attributes": {"sauce": "x"}},
            )
        assert "unknown attributes" in str(excinfo.value)
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "add_block",
                {"page": "songlines", "tag": "media-image", "attributes": {"size": "huge"}},
            )
    message = str(excinfo.value)
    assert "invalid size" in message
    assert "allowed values: small, wide" in message
    assert fake.gets == 0 and fake.patches == []


# --- the remaining anchored tools -------------------------------------------------------------


@respx.mock
async def test_update_block_tool_set_and_unset() -> None:
    mock_auth()
    fake = FakeSite('<media-image source="a.png" alt="x"></media-image>')
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        data = (
            await client.call_tool(
                "update_block",
                {
                    "page": "songlines",
                    "anchor": "media-image",
                    "set": {"size": "small", "card": "card"},
                    "unset": ["alt"],
                },
            )
        ).data
    assert isinstance(data, dict)
    assert data["operation"] == "update_block_attributes"
    assert data["affected"][0]["attributes"] == {
        "source": "a.png",
        "size": "small",
        "card": "card",
    }
    assert 'card="card"' in fake.body and "alt" not in fake.body


@respx.mock
async def test_add_link_tool_wraps_text() -> None:
    mock_auth()
    fake = FakeSite("<p>Noticing is the first act. Watch it here.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        data = (
            await client.call_tool(
                "add_link",
                {
                    "page": "songlines",
                    "anchor": "Noticing",
                    "text": "Watch it here.",
                    "url": "https://example.com/lecture",
                },
            )
        ).data
    assert isinstance(data, dict)
    assert data["operation"] == "wrap_text_with_link"
    assert data["affected"][0]["html"] == (
        '<p>Noticing is the first act. <a href="https://example.com/lecture">Watch it here.</a></p>'
    )
    assert len(fake.patches) == 1


# --- catalog tools ----------------------------------------------------------------------------


@respx.mock
async def test_list_blocks_tool_needs_no_site() -> None:
    mock_auth()
    mcp = build_server(make_settings())  # no default_site: the bundled catalog is offline
    async with Client(mcp) as client:
        data = (await client.call_tool("list_blocks", {})).data
    assert isinstance(data, dict)
    assert data["count"] == 31
    tags = [entry["tag"] for entry in data["blocks"]]
    assert tags == sorted(tags)
    assert "media-image" in tags
    assert set(data["blocks"][0]) == {"tag", "title", "description", "category"}


@respx.mock
async def test_get_block_schema_tool_bundled_and_native() -> None:
    mock_auth()
    mcp = build_server(make_settings())  # catalog reads work without a site
    async with Client(mcp) as client:
        bundled = (await client.call_tool("get_block_schema", {"tag": "media-image"})).data
        native = (await client.call_tool("get_block_schema", {"tag": "p"})).data
    assert isinstance(bundled, dict)
    assert bundled["tag"] == "media-image"
    assert bundled["title"] == "Enhanced Image"
    assert bundled["category"] == "media"
    assert bundled["example_html"]
    assert {"source", "alt"} <= {attribute["name"] for attribute in bundled["attributes"]}
    assert isinstance(native, dict)
    assert native["tag"] == "p"
    assert native["category"] == "text"
    assert native["attributes"] == []
