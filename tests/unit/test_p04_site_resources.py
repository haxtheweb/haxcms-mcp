"""Unit tests for the four `haxcms://sites...` resources (PLAN Phase 4 T4.6).

The live suite (integration/test_p04_resources.py) needs a running HAXcms; these pin the
resource payloads offline through an in-memory Client with respx: the site list and
detail JSON, the indented outline text (two spaces per level, `[unpublished]` marker),
the per-block HTML comments of the page resource, and the error path: a HaxcmsMcpError
raised under a resource read reaches the caller as `[CODE] message. hint` via
ErrorTranslationMiddleware.on_read_resource — including in per-caller HTTP mode, where
fastmcp masks every other exception's text.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from mcp.shared.exceptions import MCPError

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.middleware import ErrorTranslationMiddleware
from haxcms_mcp.resources.sites import register_site_resources
from haxcms_mcp.server import build_server

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
SITES_URL = f"{BASE}/system/api/v1/sites"
ITEMS_URL = f"{BASE}/_sites/demo/x/api/v1/items"
ITEM_RE = r".*/_sites/demo/x/api/v1/items/[^/?]+(\?.*)?$"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

ITEMS: list[dict[str, Any]] = [
    {"id": "a", "title": "Intro", "slug": "intro", "parent": None, "order": 0, "metadata": {}},
    {
        "id": "b",
        "title": "Unit",
        "slug": "unit",
        "parent": None,
        "order": 1,
        "metadata": {"published": False},
    },
    {"id": "b1", "title": "Lesson", "slug": "unit/lesson", "parent": "b", "order": 0},
]

PAGE_BODY = '<h2>Welcome</h2>\n<p>First <b>bold</b></p>\n<media-image source="a.png"></media-image>'


def make_settings(**kwargs: object) -> Settings:
    return Settings(
        base_url=BASE,
        username="test-user",
        password=secrets.token_urlsafe(16),
        **kwargs,  # type: ignore[arg-type]
    )


def ok(data: object) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "data": data})


def not_found() -> httpx.Response:
    return httpx.Response(404, json={"status": 404, "data": {"message": "Site not found"}})


def mock_instance() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "jwt": "jwt-1"})
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))
    site_record = {
        "id": "site-id",
        "title": "Demo",
        "location": "/_sites/demo/index.html",
        "metadata": {"pageCount": 3, "site": {"name": "demo"}},
    }
    respx.get(SITES_URL).mock(return_value=ok({"items": [site_record]}))
    respx.get(f"{BASE}/system/api/v1/sites/demo").mock(
        return_value=ok({"id": "site-id", "name": "demo", "title": "Demo", "metadata": {}})
    )
    respx.get(f"{BASE}/_sites/demo/x/api/v1/site").mock(
        return_value=ok({"id": "site-id", "name": "demo", "theme": "clean-one"})
    )
    respx.get(url__regex=r".*/system/api/v1/sites/ghost$").mock(return_value=not_found())
    respx.get(ITEMS_URL).mock(return_value=ok({"count": 3, "total": 3, "items": ITEMS}))

    def get_item(request: httpx.Request) -> httpx.Response:
        page = request.url.path.rsplit("/", 1)[-1]
        record = next((item for item in ITEMS if page in (item["id"], item["slug"])), None)
        if record is None:
            return httpx.Response(
                404, json={"status": 404, "data": {"message": f"Item {page} not found"}}
            )
        data = dict(record)
        if request.url.params.get("include") == "content":
            data["content"] = PAGE_BODY
        return ok(data)

    respx.get(url__regex=ITEM_RE).mock(side_effect=get_item)


async def read(server: FastMCP, uri: str) -> str:
    async with Client(server) as client:
        contents = await client.read_resource(uri)
    text = getattr(contents[0], "text", None)
    assert isinstance(text, str)
    return text


async def read_error(server: FastMCP, uri: str) -> str:
    async with Client(server) as client:
        with pytest.raises(MCPError) as excinfo:
            await client.read_resource(uri)
    return str(excinfo.value)


@respx.mock
async def test_sites_resource_lists_machine_names() -> None:
    mock_instance()
    payload = json.loads(await read(build_server(make_settings()), "haxcms://sites"))
    assert [entry["name"] for entry in payload] == ["demo"]
    assert payload[0]["page_count"] == 3


@respx.mock
async def test_site_resource_merges_info_and_summary() -> None:
    mock_instance()
    payload = json.loads(await read(build_server(make_settings()), "haxcms://sites/demo"))
    assert payload["name"] == "demo"
    assert payload["theme"] == "clean-one"


@respx.mock
async def test_outline_resource_renders_indented_text_and_tree() -> None:
    mock_instance()
    payload = json.loads(await read(build_server(make_settings()), "haxcms://sites/demo/outline"))
    assert payload["site"] == "demo"
    assert payload["count"] == 3
    assert payload["text"].splitlines() == [
        "- Intro (intro) [a]",
        "- Unit (unit) [b] [unpublished]",
        "  - Lesson (unit/lesson) [b1]",
    ]
    assert [node["item"]["id"] for node in payload["outline"]] == ["a", "b"]
    assert payload["outline"][1]["children"][0]["item"]["id"] == "b1"


@respx.mock
async def test_page_resource_prefixes_every_block_with_its_index() -> None:
    mock_instance()
    html = await read(build_server(make_settings()), "haxcms://sites/demo/pages/a")
    lines = html.splitlines()
    assert lines[0] == "<!-- block 0: h2 -->"
    assert lines[1] == "<h2>Welcome</h2>"
    assert "<!-- block 1: p -->" in lines
    assert "<!-- block 2: media-image -->" in lines
    assert html.count("<!-- block ") == 3


@respx.mock
async def test_unknown_site_surfaces_as_a_coded_resource_error() -> None:
    mock_instance()
    message = await read_error(build_server(make_settings()), "haxcms://sites/ghost")
    assert message.startswith("[NOT_FOUND] Site not found. check the site name")


@respx.mock
async def test_unknown_page_surfaces_as_a_coded_resource_error() -> None:
    mock_instance()
    message = await read_error(
        build_server(make_settings()), "haxcms://sites/demo/pages/no-such-page"
    )
    assert message.startswith("[NOT_FOUND] page 'no-such-page' not found in site 'demo'")
    assert "call list_pages" in message


@respx.mock
async def test_coded_errors_survive_error_masking() -> None:
    # per-caller HTTP mode builds the server with mask_error_details=True; the
    # middleware must still hand the caller the actionable `[CODE] message. hint`
    mock_instance()
    settings = make_settings()
    server = FastMCP("masked", mask_error_details=True)
    server.add_middleware(ErrorTranslationMiddleware())
    register_site_resources(server, settings, HaxcmsClient(settings))
    message = await read_error(server, "haxcms://sites/ghost")
    assert message.startswith("[NOT_FOUND] Site not found. check the site name")
