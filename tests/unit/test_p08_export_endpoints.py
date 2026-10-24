"""Unit tests for the Phase 8 export models and endpoint helpers (PLAN T8.1/T8.2).

respx goldens over the SOURCE-VERIFIED wire shapes (../haxcms-nodejs e969655c:
systemRoutes/v1/routes/{downloadSite,downloadSiteSkeleton,saveSiteAsTemplate}.js,
siteRoutes/v1/exports.js, app.js _published static mount): the `{site:{name}}` POST bodies
with bearer + user token, the unauthenticated _published zip fetch, the inline-skeleton
response, the binary-vs-descriptor split on GET site/export/{format} (Content-Type
discriminator), the 502 conversion-failure shape (the Chrome-less PDF path the service
re-maps to UNSUPPORTED), item exports as raw bytes for every format, and the concat-mode
markdown fetch the markdown descriptor's href points at.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient, site_api, system_api
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.models.export import (
    ITEM_EXPORT_FORMATS,
    SITE_EXPORT_FORMATS,
    ExportArtifact,
    TemplateResult,
)

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
DOWNLOAD_URL = f"{BASE}/system/api/v1/sites/demo/download"
SKELETON_URL = f"{BASE}/system/api/v1/sites/demo/download-skeleton"
TEMPLATE_URL = f"{BASE}/system/api/v1/sites/demo/save-as-template"
PUBLISHED_URL = f"{BASE}/_published/demo.zip"
SITE_EXPORT_PDF_URL = f"{BASE}/_sites/demo/x/api/v1/site/export/pdf"
SITE_EXPORT_MD_URL = f"{BASE}/_sites/demo/x/api/v1/site/export/markdown"
SITE_EXPORT_FOO_URL = f"{BASE}/_sites/demo/x/api/v1/site/export/foo"
ITEM_EXPORT_MD_URL = f"{BASE}/_sites/demo/x/api/v1/items/home/export/md"
CONTENT_URL = f"{BASE}/_sites/demo/x/api/v1/content"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 16
PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 16

# downloadSiteSkeleton golden: the skeleton arrives INLINE (API-REF §3.4 guessed a link).
SKELETON = {
    "meta": {"name": "demo", "machineName": "demo", "type": "skeleton", "version": "1.0.0"},
    "site": {"name": "demo", "description": "", "theme": "clean-one"},
    "build": {
        "type": "skeleton",
        "structure": "from-skeleton",
        "items": [
            {
                "id": "item-1",
                "title": "Home",
                "slug": "home",
                "order": 0,
                "parent": None,
                "indent": 0,
                "content": "<p>Welcome</p>",
                "metadata": {},
            }
        ],
        "files": [],
    },
    "theme": {},
}

TEMPLATE_DATA = {
    "saved": True,
    "name": "demo",
    "filename": "demo.json",
    "path": "/var/haxcms/_config/user/skeletons/demo.json",
    "link": "/system/api/v1/skeletons/demo",
}

MARKDOWN_DESCRIPTOR = {
    "format": "markdown",
    "supportedFormats": list(SITE_EXPORT_FORMATS),
    "export": {
        "rel": "download",
        "mediaType": "text/markdown",
        "href": "/_sites/demo/x/api/v1/content?mode=concat&format=md",
    },
    "links": {
        "self": "/_sites/demo/x/api/v1/site/export/markdown",
        "site": "/_sites/demo/x/api/v1/site",
    },
}


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass", **kwargs)  # type: ignore[arg-type]


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "jwt": "jwt-1"})
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def envelope(data: object) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "data": data})


def assert_user_auth(request: httpx.Request) -> None:
    assert request.headers["Authorization"] == "Bearer jwt-1"
    assert request.headers["X-HAXCMS-User-Token"] == "user-tok"


# --- system helpers: download / skeleton / template -------------------------------------------


@respx.mock
async def test_download_site_posts_the_standard_site_body() -> None:
    mock_auth()
    route = respx.post(DOWNLOAD_URL).mock(
        return_value=envelope({"link": "/_published/demo.zip", "name": "demo.zip"})
    )
    async with HaxcmsClient(make_settings()) as client:
        data = await system_api.download_site(client, "demo")
    request = route.calls.last.request
    assert_user_auth(request)
    assert json.loads(request.content) == {"site": {"name": "demo"}}
    assert data == {"link": "/_published/demo.zip", "name": "demo.zip"}


@respx.mock
async def test_fetch_published_is_unauthenticated() -> None:
    mock_auth()
    route = respx.get(PUBLISHED_URL).mock(
        return_value=httpx.Response(
            200, content=ZIP_BYTES, headers={"Content-Type": "application/zip"}
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        content = await system_api.fetch_published(client, "/_published/demo.zip")
    assert content == ZIP_BYTES
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_download_site_skeleton_returns_the_skeleton_inline() -> None:
    mock_auth()
    route = respx.post(SKELETON_URL).mock(
        return_value=envelope({"skeleton": SKELETON, "filename": "demo.json"})
    )
    async with HaxcmsClient(make_settings()) as client:
        data = await system_api.download_site_skeleton(client, "demo")
    assert_user_auth(route.calls.last.request)
    assert data["filename"] == "demo.json"
    assert data["skeleton"]["build"]["items"][0]["content"] == "<p>Welcome</p>"


@respx.mock
async def test_save_site_as_template_response_parses_into_the_model() -> None:
    mock_auth()
    route = respx.post(TEMPLATE_URL).mock(return_value=envelope(TEMPLATE_DATA))
    async with HaxcmsClient(make_settings()) as client:
        data = await system_api.save_site_as_template(client, "demo")
    assert_user_auth(route.calls.last.request)
    result = TemplateResult.from_api(data)
    assert result.saved is True
    assert result.name == "demo"
    assert result.filename == "demo.json"
    assert result.link == "/system/api/v1/skeletons/demo"


# --- site helpers: site_export / item_export / site_markdown ------------------------------------


@respx.mock
async def test_site_export_binary_format_returns_raw_bytes() -> None:
    mock_auth()
    route = respx.get(SITE_EXPORT_PDF_URL).mock(
        return_value=httpx.Response(
            200,
            content=PDF_BYTES,
            headers={
                "Content-Type": "application/pdf",
                "Content-Disposition": 'attachment; filename="demo.pdf"',
            },
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        result = await site_api.site_export(client, "demo", "pdf")
    assert result == PDF_BYTES
    # bearer only — the export GETs are not site-token gated
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer jwt-1"
    assert "X-HAXCMS-Site-Token" not in request.headers


@respx.mock
async def test_site_export_descriptor_format_returns_the_unwrapped_dict() -> None:
    mock_auth()
    respx.get(SITE_EXPORT_MD_URL).mock(return_value=envelope(MARKDOWN_DESCRIPTOR))
    async with HaxcmsClient(make_settings()) as client:
        result = await site_api.site_export(client, "demo", "markdown")
    assert isinstance(result, dict)
    assert result["export"]["href"].endswith("/content?mode=concat&format=md")
    assert result["supportedFormats"] == list(SITE_EXPORT_FORMATS)


@respx.mock
async def test_site_export_unsupported_format_maps_to_invalid_argument() -> None:
    mock_auth()
    respx.get(SITE_EXPORT_FOO_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "status": 400,
                "data": {
                    "message": 'Unsupported site export format "foo"',
                    "supportedFormats": list(SITE_EXPORT_FORMATS),
                },
            },
        )
    )
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(make_settings()) as client:
            await site_api.site_export(client, "demo", "foo")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "Unsupported site export format" in excinfo.value.message


@respx.mock
async def test_site_export_conversion_failure_maps_to_upstream_error() -> None:
    # the Chrome-less PDF path: exports.js answers 502 {data.message} — the SERVICE
    # re-maps "No Chrome" to UNSUPPORTED (T8.3); the helper preserves the envelope map
    mock_auth()
    respx.get(SITE_EXPORT_PDF_URL).mock(
        return_value=httpx.Response(
            502,
            json={
                "status": 502,
                "data": {
                    "message": (
                        # live-probed wording of the site export route (the converter
                        # actions prefix theirs with "Unable to complete ... conversion:")
                        "No Chrome/Chromium executable found. "
                        "Install Chrome or set PUPPETEER_EXECUTABLE_PATH."
                    )
                },
            },
        )
    )
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(make_settings()) as client:
            await site_api.site_export(client, "demo", "pdf")
    error = excinfo.value
    assert error.code is ErrorCode.UPSTREAM_ERROR
    assert "No Chrome" in error.message
    assert error.details["status_code"] == 502


@respx.mock
async def test_item_export_returns_raw_bytes() -> None:
    mock_auth()
    markdown = b"# Home\n\nWelcome to the site."
    respx.get(ITEM_EXPORT_MD_URL).mock(
        return_value=httpx.Response(
            200,
            content=markdown,
            headers={
                "Content-Type": "text/markdown; charset=utf-8",
                "Content-Disposition": 'attachment; filename="home.md"',
            },
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        result = await site_api.item_export(client, "demo", "home", "md")
    assert result == markdown


@respx.mock
async def test_item_export_percent_encodes_nested_slugs() -> None:
    mock_auth()
    route = respx.get(url__regex=r".*/x/api/v1/items/[^/]+/export/json$").mock(
        return_value=httpx.Response(
            200, content=b'{"id": "item-2"}', headers={"Content-Type": "application/json"}
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        await site_api.item_export(client, "demo", "unit-one/lesson-one", "json")
    # httpx's url.path DECODES %2F back to / — only raw_path shows the real wire path
    raw_path = route.calls.last.request.url.raw_path.decode()
    assert "unit-one%2Flesson-one" in raw_path


@respx.mock
async def test_site_markdown_requests_the_concat_mode() -> None:
    mock_auth()
    route = respx.get(url__regex=r".*/x/api/v1/content(\?.*)?$").mock(
        return_value=httpx.Response(
            200, content=b"# Home\n\nWelcome", headers={"Content-Type": "text/markdown"}
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        text = await site_api.site_markdown(client, "demo")
    assert text == "# Home\n\nWelcome"
    query = route.calls.last.request.url.query.decode()
    assert "mode=concat" in query
    assert "format=md" in query


# --- models --------------------------------------------------------------------------------------


def test_export_artifact_dump_drops_the_none_page_id(tmp_path: Path) -> None:
    artifact = ExportArtifact(
        site="demo",
        format="zip",
        path=tmp_path / "demo.zip",
        bytes=20,
        mimetype="application/zip",
        created_at=1767225600.0,
    )
    dumped = dump_model(artifact)
    assert "page_id" not in dumped
    assert dumped["format"] == "zip"
    assert dumped["bytes"] == 20
    assert dumped["path"].endswith("demo.zip")  # Path serializes to str in json mode


def test_export_artifact_page_dump_keeps_the_page_id(tmp_path: Path) -> None:
    artifact = ExportArtifact(
        site="demo",
        page_id="item-2",
        format="md",
        path=tmp_path / "lesson.md",
        bytes=12,
        mimetype="text/markdown",
        created_at=1767225600.0,
    )
    assert dump_model(artifact)["page_id"] == "item-2"


def test_template_result_ignores_unknown_keys() -> None:
    result = TemplateResult.from_api({**TEMPLATE_DATA, "future": "key"})
    assert result.name == "demo"
    assert "future" not in dump_model(result)


def test_format_lists_match_the_server_allow_lists() -> None:
    # golden against exports.js SITE_EXPORT_FORMATS / ITEM_EXPORT_FORMATS
    assert SITE_EXPORT_FORMATS == ("zip", "markdown", "pdf", "docx", "epub", "html", "skeleton")
    assert ITEM_EXPORT_FORMATS == ("pdf", "docx", "html", "md", "json", "yaml", "xml", "epub")
