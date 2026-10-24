"""Unit tests for the site/page export service (PLAN Phase 8 T8.3).

respx goldens over the source-verified routes: the zip two-step (POST download -> GET the
_published link), the descriptor formats (markdown via content?mode=concat&format=md,
skeleton via the INLINE download-skeleton response), the straight binary formats, the
Chrome-less PDF re-map to UNSUPPORTED, local format validation, and the page exports with
their canonical page_id resolution.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.models.export import SITE_EXPORT_FORMATS
from haxcms_mcp.services.exports import service

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
DOWNLOAD_URL = f"{BASE}/system/api/v1/sites/demo/download"
SKELETON_URL = f"{BASE}/system/api/v1/sites/demo/download-skeleton"
TEMPLATE_URL = f"{BASE}/system/api/v1/sites/demo/save-as-template"
PUBLISHED_URL = f"{BASE}/_published/demo.zip"
ITEMS_HOME_URL = f"{BASE}/_sites/demo/x/api/v1/items/home"
CONTENT_URL = f"{BASE}/_sites/demo/x/api/v1/content"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 16
HTML_BYTES = b"<html><body><h1>Home</h1></body></html>"
NO_CHROME = "No Chrome/Chromium executable found. Install Chrome or set PUPPETEER_EXECUTABLE_PATH."

SKELETON = {
    "meta": {"name": "demo", "machineName": "demo", "type": "skeleton"},
    "build": {"items": [{"id": "item-1", "title": "Home", "content": "<p>Welcome</p>"}]},
}

MARKDOWN_DESCRIPTOR = {
    "format": "markdown",
    "supportedFormats": list(SITE_EXPORT_FORMATS),
    "export": {
        "rel": "download",
        "mediaType": "text/markdown",
        "href": "/_sites/demo/x/api/v1/content?mode=concat&format=md",
    },
}

TEMPLATE_DATA = {
    "saved": True,
    "name": "demo",
    "filename": "demo.json",
    "path": "/var/haxcms/_config/user/skeletons/demo.json",
    "link": "/system/api/v1/skeletons/demo",
}


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        base_url=BASE,
        username="envuser",
        password="envpass",
        output_dir=tmp_path,
    )


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "jwt": "jwt-1"})
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def envelope(data: object) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "data": data})


def site_export_route(fmt: str, response: httpx.Response) -> respx.Route:
    return respx.get(f"{BASE}/_sites/demo/x/api/v1/site/export/{fmt}").mock(return_value=response)


def item_export_route(id_or_slug: str, fmt: str, response: httpx.Response) -> respx.Route:
    quoted = id_or_slug.replace("/", "%2F")
    return respx.get(f"{BASE}/_sites/demo/x/api/v1/items/{quoted}/export/{fmt}").mock(
        return_value=response
    )


def assert_artifact_on_disk(artifact: object, tmp_path: Path, site: str) -> Path:
    dumped = dump_model(artifact)  # type: ignore[arg-type]
    path = Path(dumped["path"])
    assert path.parent == tmp_path / site
    assert path.name.startswith(tuple("0123456789"))
    assert path.exists()
    return path


# --- export_site --------------------------------------------------------------------------------


@respx.mock
async def test_export_site_zip_is_the_two_step_download(tmp_path: Path) -> None:
    mock_auth()
    post = respx.post(DOWNLOAD_URL).mock(
        return_value=envelope({"link": "/_published/demo.zip", "name": "demo.zip"})
    )
    get = respx.get(PUBLISHED_URL).mock(return_value=httpx.Response(200, content=ZIP_BYTES))
    settings = make_settings(tmp_path)
    async with HaxcmsClient(settings) as client:
        artifact = await service.export_site(client, settings, "demo", "zip")
    assert post.call_count == 1
    assert get.call_count == 1
    assert artifact.format == "zip"
    assert artifact.mimetype == "application/zip"
    assert artifact.bytes == len(ZIP_BYTES)
    path = assert_artifact_on_disk(artifact, tmp_path, "demo")
    assert path.name.endswith("-demo.zip")
    assert path.read_bytes() == ZIP_BYTES


@respx.mock
async def test_export_site_zip_falls_back_to_the_site_name(tmp_path: Path) -> None:
    mock_auth()
    respx.post(DOWNLOAD_URL).mock(return_value=envelope({"link": "/_published/demo.zip"}))
    respx.get(PUBLISHED_URL).mock(return_value=httpx.Response(200, content=ZIP_BYTES))
    settings = make_settings(tmp_path)
    async with HaxcmsClient(settings) as client:
        artifact = await service.export_site(client, settings, "demo", "zip")
    assert artifact.path.name.endswith("-demo.zip")


@respx.mock
async def test_export_site_binary_format_streams_straight_to_disk(tmp_path: Path) -> None:
    mock_auth()
    site_export_route(
        "html",
        httpx.Response(
            200,
            content=HTML_BYTES,
            headers={"Content-Type": "text/html; charset=utf-8"},
        ),
    )
    settings = make_settings(tmp_path)
    async with HaxcmsClient(settings) as client:
        artifact = await service.export_site(client, settings, "demo", "html")
    assert artifact.format == "html"
    assert artifact.mimetype == "text/html"
    path = assert_artifact_on_disk(artifact, tmp_path, "demo")
    assert path.name.endswith("-demo.html")
    assert path.read_bytes() == HTML_BYTES


@respx.mock
async def test_export_site_normalizes_the_format(tmp_path: Path) -> None:
    mock_auth()
    site_export_route("html", httpx.Response(200, content=HTML_BYTES))
    settings = make_settings(tmp_path)
    async with HaxcmsClient(settings) as client:
        artifact = await service.export_site(client, settings, "demo", " HTML ")
    assert artifact.format == "html"


@respx.mock
async def test_export_site_pdf_without_chrome_maps_to_unsupported(tmp_path: Path) -> None:
    mock_auth()
    site_export_route(
        "pdf", httpx.Response(502, json={"status": 502, "data": {"message": NO_CHROME}})
    )
    settings = make_settings(tmp_path)
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(settings) as client:
            await service.export_site(client, settings, "demo", "pdf")
    error = excinfo.value
    assert error.code is ErrorCode.UNSUPPORTED
    assert "No Chrome" in error.message
    assert "no Chrome for PDF rendering" in (error.hint or "")


@respx.mock
async def test_export_site_markdown_follows_the_descriptor(tmp_path: Path) -> None:
    mock_auth()
    descriptor = site_export_route("markdown", envelope(MARKDOWN_DESCRIPTOR))
    content = respx.get(url__regex=r".*/x/api/v1/content(\?.*)?$").mock(
        return_value=httpx.Response(200, content=b"# Home\n\nWelcome")
    )
    settings = make_settings(tmp_path)
    async with HaxcmsClient(settings) as client:
        artifact = await service.export_site(client, settings, "demo", "markdown")
    assert descriptor.call_count == 1
    assert content.call_count == 1
    assert artifact.format == "markdown"
    assert artifact.mimetype == "text/markdown"
    path = assert_artifact_on_disk(artifact, tmp_path, "demo")
    assert path.name.endswith("-demo.md")
    assert path.read_text(encoding="utf-8") == "# Home\n\nWelcome"


@respx.mock
async def test_export_site_skeleton_writes_the_inline_skeleton_as_json(tmp_path: Path) -> None:
    mock_auth()
    respx.post(SKELETON_URL).mock(
        return_value=envelope({"skeleton": SKELETON, "filename": "demo.json"})
    )
    settings = make_settings(tmp_path)
    async with HaxcmsClient(settings) as client:
        artifact = await service.export_site(client, settings, "demo", "skeleton")
    assert artifact.format == "skeleton"
    assert artifact.mimetype == "application/json"
    path = assert_artifact_on_disk(artifact, tmp_path, "demo")
    assert path.name.endswith("-demo.json")
    assert json.loads(path.read_text(encoding="utf-8")) == SKELETON


@respx.mock
async def test_export_site_rejects_unknown_formats_locally(tmp_path: Path) -> None:
    # no routes mocked: any HTTP attempt would fail inside respx.mock
    settings = make_settings(tmp_path)
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(settings) as client:
            await service.export_site(client, settings, "demo", "xls")
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "xls" in error.message
    assert "zip, markdown, pdf, docx, epub, html, skeleton" in (error.hint or "")


@respx.mock
async def test_export_site_binary_format_rejects_a_descriptor_answer(tmp_path: Path) -> None:
    mock_auth()
    site_export_route("pdf", envelope(MARKDOWN_DESCRIPTOR))
    settings = make_settings(tmp_path)
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(settings) as client:
            await service.export_site(client, settings, "demo", "pdf")
    assert excinfo.value.code is ErrorCode.UPSTREAM_ERROR
    assert "expected binary bytes" in excinfo.value.message


# --- export_page --------------------------------------------------------------------------------


@respx.mock
async def test_export_page_resolves_the_canonical_page_id(tmp_path: Path) -> None:
    mock_auth()
    respx.get(ITEMS_HOME_URL).mock(
        return_value=envelope({"id": "item-1", "slug": "home", "title": "Home"})
    )
    markdown = b"# Home\n\nWelcome to the site."
    item_export_route(
        "home",
        "md",
        httpx.Response(200, content=markdown, headers={"Content-Type": "text/markdown"}),
    )
    settings = make_settings(tmp_path)
    async with HaxcmsClient(settings) as client:
        artifact = await service.export_page(client, settings, "demo", "home", "md")
    assert artifact.page_id == "item-1"
    assert artifact.format == "md"
    assert artifact.mimetype == "text/markdown"
    path = assert_artifact_on_disk(artifact, tmp_path, "demo")
    assert path.name.endswith("-home.md")
    assert path.read_bytes() == markdown


@respx.mock
async def test_export_page_nested_slugs_keep_the_last_segment(tmp_path: Path) -> None:
    mock_auth()
    nested = f"{BASE}/_sites/demo/x/api/v1/items/unit-one%2Flesson-one"
    respx.get(nested).mock(return_value=envelope({"id": "item-2", "slug": "unit-one/lesson-one"}))
    item_export_route(
        "unit-one/lesson-one",
        "json",
        httpx.Response(200, content=b'{"id": "item-2"}'),
    )
    settings = make_settings(tmp_path)
    async with HaxcmsClient(settings) as client:
        artifact = await service.export_page(
            client, settings, "demo", "unit-one/lesson-one", "json"
        )
    assert artifact.page_id == "item-2"
    assert artifact.path.name.endswith("-lesson-one.json")


@respx.mock
async def test_export_page_pdf_without_chrome_maps_to_unsupported(tmp_path: Path) -> None:
    mock_auth()
    respx.get(ITEMS_HOME_URL).mock(return_value=envelope({"id": "item-1", "slug": "home"}))
    item_export_route(
        "home", "pdf", httpx.Response(502, json={"status": 502, "data": {"message": NO_CHROME}})
    )
    settings = make_settings(tmp_path)
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(settings) as client:
            await service.export_page(client, settings, "demo", "home", "pdf")
    assert excinfo.value.code is ErrorCode.UNSUPPORTED


@respx.mock
async def test_export_page_rejects_site_only_formats(tmp_path: Path) -> None:
    # "markdown" is the SITE format; items use "md" — validated before any HTTP
    settings = make_settings(tmp_path)
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(settings) as client:
            await service.export_page(client, settings, "demo", "home", "markdown")
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "pdf, docx, html, md, json, yaml, xml, epub" in (error.hint or "")


# --- save_site_as_template / download_site_skeleton ----------------------------------------------


@respx.mock
async def test_save_site_as_template_parses_the_response(tmp_path: Path) -> None:
    mock_auth()
    respx.post(TEMPLATE_URL).mock(return_value=envelope(TEMPLATE_DATA))
    settings = make_settings(tmp_path)
    async with HaxcmsClient(settings) as client:
        result = await service.save_site_as_template(client, "demo")
    assert result.saved is True
    assert result.name == "demo"
    assert result.filename == "demo.json"
    assert result.link == "/system/api/v1/skeletons/demo"


@respx.mock
async def test_download_site_skeleton_writes_the_inline_skeleton(tmp_path: Path) -> None:
    mock_auth()
    route = respx.post(SKELETON_URL).mock(
        return_value=envelope({"skeleton": SKELETON, "filename": "demo.json"})
    )
    settings = make_settings(tmp_path)
    async with HaxcmsClient(settings) as client:
        artifact = await service.download_site_skeleton(client, settings, "demo")
    assert route.call_count == 1
    assert artifact.format == "skeleton"
    path = assert_artifact_on_disk(artifact, tmp_path, "demo")
    assert json.loads(path.read_text(encoding="utf-8")) == SKELETON


@respx.mock
async def test_download_site_skeleton_rejects_a_missing_skeleton(tmp_path: Path) -> None:
    mock_auth()
    respx.post(SKELETON_URL).mock(return_value=envelope({"filename": "demo.json"}))
    settings = make_settings(tmp_path)
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(settings) as client:
            await service.download_site_skeleton(client, settings, "demo")
    assert excinfo.value.code is ErrorCode.UPSTREAM_ERROR
    assert "no skeleton object" in excinfo.value.message
