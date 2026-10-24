"""Unit tests for the Page Break envelope builder (PLAN Phase 4 T4.1; API-REF §5.2).

Goldens pin the exact attribute order and value escaping the saveNode parser contract
requires: every flag WITH its canonical value (parse_attributes turns value-less flags
into null), absence-means-false/deletes details reproduced from the record, and
double-quote-safe HTML escaping.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient, site_api
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.item import Item
from haxcms_mcp.services.content.page_break import build_page_break, save_content

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
CONTENT_RE = r".*/_sites/demo/x/api/v1/content/[^/]+(\?|$)"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)


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


FULL_RECORD: dict[str, Any] = {
    "id": "item-123",
    "title": 'A "Quoted" <Title> & More',
    "slug": "unit-1/song-lines",
    "parent": "item-unit-1",
    "indent": 2,
    "order": 7,
    "description": "A description with & ampersand",
    "metadata": {
        "published": True,
        "locked": True,
        "hideInMenu": True,
        "pageType": "lesson",
        "tags": ["week-1", "intro"],
        "relatedItems": ["item-2", "item-3"],
        "image": "files/cover.png",
        "icon": "hax:lesson",
        "accentColor": "purple",
        "theme": {"element": "clean-one", "path": "@haxtheweb/clean-one", "key": "clean-one"},
        "overridePathauto": True,
        "linkUrl": "https://example.com/x",
        "linkTarget": "_blank",
    },
}


# --- builder goldens ------------------------------------------------------------------------


def test_build_page_break_full_item() -> None:
    envelope = build_page_break(Item.from_api(FULL_RECORD))
    assert envelope == (
        '<page-break item-id="item-123"'
        ' title="A &quot;Quoted&quot; &lt;Title&gt; &amp; More"'
        ' slug="unit-1/song-lines" path="unit-1/song-lines" parent="item-unit-1"'
        ' published="published" locked="locked" hide-in-menu="hide-in-menu"'
        ' page-type="lesson" tags="week-1,intro" related-items="item-2,item-3"'
        ' image="files/cover.png" icon="hax:lesson" accent-color="purple"'
        ' link-url="https://example.com/x" link-target="_blank"'
        ' description="A description with &amp; ampersand"'
        ' developer-theme="clean-one" depth="2" order="7"'
        ' override-pathauto="true"></page-break>'
    )


def test_build_page_break_minimal_item() -> None:
    record = {"id": "item-1", "title": "Home", "slug": "home", "metadata": {}}
    envelope = build_page_break(Item.from_api(record))
    # from_api defaults published=True (metadata.published !== false upstream);
    # depth/order are always emitted so saves stay deterministic
    assert envelope == (
        '<page-break item-id="item-1" title="Home" slug="home" path="home"'
        ' published="published" depth="0" order="0"></page-break>'
    )


def test_build_page_break_flags_off_are_absent() -> None:
    record = {
        "id": "item-9",
        "title": "Draft",
        "slug": "draft",
        "metadata": {
            "published": False,
            "locked": False,
            "hideInMenu": False,
            "overridePathauto": False,
        },
    }
    envelope = build_page_break(Item.from_api(record))
    assert "published" not in envelope
    assert "locked" not in envelope
    assert "hide-in-menu" not in envelope
    assert "override-pathauto" not in envelope
    assert envelope == (
        '<page-break item-id="item-9" title="Draft" slug="draft" path="draft"'
        ' depth="0" order="0"></page-break>'
    )


def test_build_page_break_absent_details_are_omitted() -> None:
    # no parent, no description, no metadata extras: nothing beyond the core attrs —
    # upstream would DELETE page-type/tags/image/... anyway, there is nothing to preserve
    record = {"id": "item-2", "title": "Plain", "slug": "plain", "parent": None, "metadata": {}}
    envelope = build_page_break(Item.from_api(record))
    for absent in (
        "parent=",
        "page-type=",
        "tags=",
        "image=",
        "icon=",
        "description=",
        "developer-theme=",
        "related-items=",
        "accent-color=",
        "link-url=",
    ):
        assert absent not in envelope


def test_build_page_break_theme_string_key() -> None:
    # older manifests may store a bare key string instead of the theme object
    record = {"id": "i", "title": "T", "slug": "t", "metadata": {"theme": "clean-portfolio"}}
    assert 'developer-theme="clean-portfolio"' in build_page_break(Item.from_api(record))


def test_build_page_break_tags_from_metadata_csv_string() -> None:
    # manifests also store tags as a CSV string; Item normalises both shapes to a list
    record = {"id": "i", "title": "T", "slug": "t", "metadata": {"tags": "a, b ,c"}}
    assert 'tags="a,b,c"' in build_page_break(Item.from_api(record))


# --- save_content ---------------------------------------------------------------------------


@respx.mock
async def test_save_content_prepends_envelope_and_patches() -> None:
    mock_auth()
    sent: list[dict[str, Any]] = []

    def patch_effect(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        updated = dict(FULL_RECORD)
        updated["title"] = "Saved"
        return httpx.Response(200, json={"status": 200, "data": updated})

    route = respx.patch(url__regex=CONTENT_RE).mock(side_effect=patch_effect)
    client = HaxcmsClient(make_settings())
    item = Item.from_api(FULL_RECORD)
    schema = [{"tag": "media-image", "properties": {"source": "files/a.png"}}]

    result = await save_content(client, "demo", item, "<p>Body.</p>", schema=schema)

    assert route.called
    assert sent[0]["site"] == {"name": "demo"}
    assert sent[0]["body"].startswith("<page-break item-id=")
    assert sent[0]["body"].endswith("></page-break><p>Body.</p>")
    assert sent[0]["schema"] == schema
    assert "details" not in sent[0]
    assert result.title == "Saved"


@respx.mock
async def test_save_content_passes_details() -> None:
    mock_auth()
    sent: list[dict[str, Any]] = []

    def patch_effect(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"status": 200, "data": FULL_RECORD})

    respx.patch(url__regex=CONTENT_RE).mock(side_effect=patch_effect)
    client = HaxcmsClient(make_settings())
    details = {"node": {"configure": {"title": "X"}}}
    await save_content(client, "demo", Item.from_api(FULL_RECORD), "<p>x</p>", details=details)
    assert sent[0]["details"] == details


async def test_save_content_requires_an_id() -> None:
    client = HaxcmsClient(make_settings())
    with pytest.raises(HaxcmsMcpError) as info:
        await save_content(client, "demo", Item(title="no id"), "<p>x</p>")
    assert info.value.code is ErrorCode.INVALID_ARGUMENT


# --- get_content helper ----------------------------------------------------------------------


@respx.mock
async def test_get_content_uses_format_json_and_bearer() -> None:
    mock_auth()
    record = {"id": "item-1", "slug": "home", "title": "Home", "format": "json", "body": "<p>H</p>"}
    route = respx.get(url__regex=CONTENT_RE).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": record})
    )
    client = HaxcmsClient(make_settings())
    data = await site_api.get_content(client, "demo", "item-1")
    assert data["body"] == "<p>H</p>"
    request = route.calls.last.request
    assert "format=json" in str(request.url)
    # nested slugs travel percent-encoded (httpx `.path` decodes, so check the full URL)
    await site_api.get_content(client, "demo", "unit-1/song-lines")
    assert "/content/unit-1%2Fsong-lines" in str(route.calls.last.request.url)
