"""Unit tests for the Phase 7 import composites in services/imports.py (PLAN T7.3).

The endpoint helpers are goldened in test_p07_import_payloads.py; these tests cover the
composites on top of them with a stateful respx fake: argument validation BEFORE any
HTTP, the importer `contents` -> bulk-outline `content` mapping (the bulk create is the
same outline write the editor uses, so its body is asserted field by field), parent
resolution, warnings, the createSite `build.structure == "import"` payload, license and
rename fallbacks, the `drupal-book` alias, and the SSRF error-hint rewrite.
"""

from __future__ import annotations

import base64
import json
import secrets
from typing import Any

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services import imports as imports_service

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
IMPORT_HTML_URL = f"{BASE}/system/api/v1/actions/import-html"
PLATFORM_RE = r".*/system/api/v1/site/import/[^/]+$"
SITES_URL = f"{BASE}/system/api/v1/sites"
THEMES_URL = f"{BASE}/system/api/v1/themes"
ITEMS_URL = f"{BASE}/_sites/demo/x/api/v1/items"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

THEMES = [
    {"machineName": "clean-one", "name": "Clean One", "hidden": False, "enabled": True},
    {"machineName": "secret-theme", "name": "Secret", "hidden": True, "enabled": True},
]

# importer golden (Phase 7 probe shape): server-fresh ids, `contents`, nested child slug
IMPORTED = [
    {
        "id": "imp-1",
        "title": "Unit One",
        "slug": "unit-one",
        "parent": "null",
        "indent": 0,
        "order": 0,
        "location": "pages/imp-1/index.html",
        "contents": "<p>Overview</p>",
        "metadata": {},
    },
    {
        "id": "imp-2",
        "title": "Lesson One",
        "slug": "unit-one/lesson-one",
        "parent": "imp-1",
        "indent": 1,
        "order": 0,
        "contents": "<p>Body</p>",
        "metadata": {},
    },
]


def make_settings(**kwargs: object) -> Settings:
    # throwaway credentials built at runtime: nothing credential-shaped is committed
    return Settings(
        base_url=BASE,
        username="test-user",
        password=secrets.token_urlsafe(16),
        **kwargs,  # type: ignore[arg-type]
    )


def html_source(markup: str = "<h1>Unit One</h1><p>Overview</p>") -> str:
    return "base64:lesson.html:" + base64.b64encode(markup.encode()).decode()


def ok(data: object) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "data": data})


class FakeInstance:
    """Stateful respx fake: importer, bulk item create, item list, themes, createSite."""

    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.items: list[dict[str, Any]] = list(existing or [])
        self.import_requests: list[httpx.Request] = []
        self.bulk_bodies: list[dict[str, Any]] = []
        self.create_bodies: list[dict[str, Any]] = []
        self.platform_bodies: list[dict[str, Any]] = []
        self.import_response: dict[str, Any] = {"items": IMPORTED, "filename": "lesson.html"}
        self.created_name: str | None = None
        self.drop_ids: set[str] = set()

    def install(self) -> None:
        respx.post(LOGIN_URL).mock(
            return_value=httpx.Response(200, json={"status": 200, "jwt": "jwt-1"})
        )
        respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))
        respx.post(IMPORT_HTML_URL).mock(side_effect=self._import)
        respx.post(url__regex=PLATFORM_RE).mock(side_effect=self._platform)
        respx.get(ITEMS_URL).mock(side_effect=self._list_items)
        respx.post(ITEMS_URL).mock(side_effect=self._bulk_create)
        respx.get(THEMES_URL).mock(return_value=ok(THEMES))
        respx.post(SITES_URL).mock(side_effect=self._create_site)
        respx.get(url__regex=r".*/system/api/v1/sites/[^/]+$").mock(side_effect=self._site_info)
        respx.get(url__regex=r".*/x/api/v1/site$").mock(side_effect=self._summary)

    def _import(self, request: httpx.Request) -> httpx.Response:
        self.import_requests.append(request)
        return ok(self.import_response)

    def _platform(self, request: httpx.Request) -> httpx.Response:
        self.platform_bodies.append({"path": request.url.path, **json.loads(request.content)})
        return ok(self.import_response)

    def _list_items(self, request: httpx.Request) -> httpx.Response:
        return ok({"count": len(self.items), "total": len(self.items), "items": self.items})

    def _bulk_create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bulk_bodies.append(body)
        for entry in body["items"]:
            if entry["id"] in self.drop_ids:
                continue
            self.items.append(
                {
                    "id": entry["id"],
                    "title": entry["title"],
                    "slug": entry.get("slug") or entry["id"],
                    "parent": entry.get("parent"),
                    "indent": entry.get("indent", 0),
                    "order": entry.get("order", 0),
                    "metadata": {},
                }
            )
        return ok(body["items"][-1])

    def _create_site(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.create_bodies.append(body)
        name = self.created_name or body["site"]["name"]
        return ok({"id": "new", "metadata": {"site": {"name": name}}})

    def _site_info(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        return ok({"id": "s", "name": name, "title": name, "metadata": {"pageCount": 2}})

    def _summary(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.split("/_sites/", 1)[1].split("/", 1)[0]
        return ok({"id": "s", "name": name, "theme": "clean-one", "counts": {"items": 2}})


def multipart_fields(request: httpx.Request) -> str:
    """The decoded multipart body: enough to assert which form fields were sent."""
    return request.content.decode("utf-8", errors="replace")


# --- argument validation happens before any HTTP -----------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"method": "tree"}, "unknown import method"),
        ({"content_type": "textbook"}, "unknown import content type"),
    ],
)
@respx.mock
async def test_import_document_rejects_bad_options_before_http(
    kwargs: dict[str, str], needle: str
) -> None:
    fake = FakeInstance()
    fake.install()
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await imports_service.import_document(
                client, make_settings(), "demo", html_source(), **kwargs
            )
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert needle in excinfo.value.message
    assert fake.import_requests == []
    assert fake.bulk_bodies == []


@respx.mock
async def test_import_document_unknown_kind_is_refused_before_upload() -> None:
    fake = FakeInstance()
    fake.install()
    source = "base64:notes.txt:" + base64.b64encode(b"plain").decode()
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await imports_service.import_document(client, make_settings(), "demo", source)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert fake.import_requests == []


# --- import_document: importer records -> bulk outline create -----------------------------


@respx.mock
async def test_import_document_maps_contents_and_detaches_null_parents() -> None:
    fake = FakeInstance()
    fake.install()
    settings = make_settings()
    async with HaxcmsClient(settings) as client:
        result = await imports_service.import_document(
            client, settings, "demo", html_source(), method=" Branch ", content_type="COURSE"
        )

    # the multipart upload carries the normalized method/type and the file part
    fields = multipart_fields(fake.import_requests[0])
    assert 'name="file-upload"; filename="lesson.html"' in fields
    assert 'name="method"\r\n\r\nbranch' in fields
    assert 'name="type"\r\n\r\ncourse' in fields
    assert 'name="parentId"' not in fields

    [bulk] = fake.bulk_bodies
    assert bulk["site"] == {"name": "demo"}
    first, second = bulk["items"]
    # `contents` becomes `content`; "null" parents and `location` are dropped
    assert first["content"] == "<p>Overview</p>"
    assert "contents" not in first
    assert "parent" not in first
    assert "location" not in first
    # server-fresh ids survive so the child still points at its parent
    assert first["id"] == "imp-1"
    assert second["parent"] == "imp-1"
    assert second["slug"] == "unit-one/lesson-one"

    assert [item.id for item in result.created] == ["imp-1", "imp-2"]
    assert result.skipped == 0
    assert result.warnings is None
    assert result.source_filename == "lesson.html"


@respx.mock
async def test_import_document_resolves_parent_slug_to_id() -> None:
    existing = {
        "id": "page-9",
        "title": "Existing",
        "slug": "existing",
        "parent": None,
        "indent": 0,
        "order": 0,
        "metadata": {},
    }
    fake = FakeInstance(existing=[existing])
    fake.install()
    settings = make_settings()
    async with HaxcmsClient(settings) as client:
        await imports_service.import_document(
            client, settings, "demo", html_source(), parent="existing"
        )
    assert 'name="parentId"\r\n\r\npage-9' in multipart_fields(fake.import_requests[0])


@respx.mock
async def test_import_document_unknown_parent_is_not_found_before_upload() -> None:
    fake = FakeInstance()
    fake.install()
    settings = make_settings()
    async with HaxcmsClient(settings) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await imports_service.import_document(
                client, settings, "demo", html_source(), parent="nope"
            )
    assert excinfo.value.code is ErrorCode.NOT_FOUND
    assert fake.import_requests == []
    assert fake.bulk_bodies == []


@respx.mock
async def test_import_document_with_no_items_writes_nothing() -> None:
    fake = FakeInstance()
    fake.import_response = {"items": [], "filename": "lesson.html"}
    fake.install()
    settings = make_settings()
    async with HaxcmsClient(settings) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await imports_service.import_document(client, settings, "demo", html_source())
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "produced no outline items" in excinfo.value.message
    assert fake.bulk_bodies == []


@respx.mock
async def test_import_document_warns_about_download_maps_and_missing_pages() -> None:
    fake = FakeInstance()
    fake.import_response = {
        "items": IMPORTED,
        "filename": "lesson.html",
        "files": {"a.png": "https://example.org/a.png"},
    }
    fake.drop_ids = {"imp-2"}  # the server "loses" one record
    fake.install()
    settings = make_settings()
    async with HaxcmsClient(settings) as client:
        result = await imports_service.import_document(client, settings, "demo", html_source())
    assert [item.id for item in result.created] == ["imp-1"]
    assert result.skipped == 1
    warnings = result.warnings or []
    assert any("download maps" in warning for warning in warnings)
    assert any("1 imported items did not appear" in warning for warning in warnings)


# --- create_site_from_document --------------------------------------------------------------


@respx.mock
async def test_create_site_from_document_builds_the_import_payload() -> None:
    fake = FakeInstance()
    fake.import_response = {
        "items": IMPORTED,
        "filename": "lesson.html",
        "site": {"license": "by-nc"},
    }
    fake.install()
    settings = make_settings()
    async with HaxcmsClient(settings) as client:
        detail = await imports_service.create_site_from_document(
            client, settings, "my-course", html_source(), description="From a doc"
        )
    # createSite always imports with method=site
    assert 'name="method"\r\n\r\nsite' in multipart_fields(fake.import_requests[0])
    [body] = fake.create_bodies
    assert body["site"] == {
        "name": "my-course",
        "description": "From a doc",
        "theme": "clean-one",
        "license": "by-nc",  # the import's own license wins over the by-sa default
        "domain": None,
    }
    build = body["build"]
    assert build["type"] == "html import"
    assert build["structure"] == "import"
    # raw importer records pass through untouched (createSite materializes them)
    assert build["items"] == IMPORTED
    assert "files" not in build
    assert "siteFiles" not in build
    assert detail.name == "my-course"
    assert fake.bulk_bodies == []  # no second write path


@respx.mock
async def test_create_site_from_document_rejects_bad_names_before_http() -> None:
    fake = FakeInstance()
    fake.install()
    settings = make_settings()
    async with HaxcmsClient(settings) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await imports_service.create_site_from_document(
                client, settings, "My Course", html_source()
            )
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert fake.import_requests == []
    assert fake.create_bodies == []


@respx.mock
async def test_create_site_from_document_unknown_theme_is_refused_before_create() -> None:
    fake = FakeInstance()
    fake.install()
    settings = make_settings()
    async with HaxcmsClient(settings) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await imports_service.create_site_from_document(
                client, settings, "my-course", html_source(), theme="no-such-theme"
            )
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "unknown theme" in excinfo.value.message
    assert fake.create_bodies == []


@respx.mock
async def test_create_site_from_document_reports_hidden_theme_and_rename() -> None:
    fake = FakeInstance()
    fake.created_name = "my-course-1"
    fake.install()
    settings = make_settings()
    async with HaxcmsClient(settings) as client:
        detail = await imports_service.create_site_from_document(
            client, settings, "my-course", html_source(), theme="secret-theme", license="by"
        )
    assert fake.create_bodies[0]["site"]["license"] == "by"
    assert detail.name == "my-course-1"
    warnings = detail.warnings or []
    assert any("marked hidden" in warning for warning in warnings)
    assert any("already taken" in warning and "my-course-1" in warning for warning in warnings)


@respx.mock
async def test_create_site_from_document_with_no_items_never_creates() -> None:
    fake = FakeInstance()
    fake.import_response = {"items": []}
    fake.install()
    settings = make_settings()
    async with HaxcmsClient(settings) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await imports_service.create_site_from_document(
                client, settings, "my-course", html_source()
            )
    assert "the html import produced no outline items" in excinfo.value.message
    assert fake.create_bodies == []


# --- create_site_from_platform --------------------------------------------------------------


@respx.mock
async def test_create_site_from_platform_maps_alias_and_carries_download_maps() -> None:
    fake = FakeInstance()
    fake.import_response = {
        "items": IMPORTED,
        "files": {"files/a.png": "https://example.org/a.png"},
        "siteFiles": {"logo.png": "https://example.org/logo.png"},
    }
    fake.install()
    async with HaxcmsClient(make_settings()) as client:
        await imports_service.create_site_from_platform(
            client, "from-drupal", " Drupal-Book ", "  https://example.org/book  "
        )
    [platform] = fake.platform_bodies
    # the legacy name maps to HAXcms main's `drupal`; the URL is trimmed
    assert platform["path"].endswith("/site/import/drupal")
    assert platform["repoUrl"] == "https://example.org/book"
    assert platform["method"] == "site"
    build = fake.create_bodies[0]["build"]
    assert build["type"] == "drupal import"
    assert build["files"] == {"files/a.png": "https://example.org/a.png"}
    assert build["siteFiles"] == {"logo.png": "https://example.org/logo.png"}
    assert fake.create_bodies[0]["site"]["license"] == "by-sa"  # default


@pytest.mark.parametrize(
    ("platform", "url", "needle"),
    [
        ("myspace", "https://example.org", "unsupported import platform"),
        ("wordpress", "   ", "url must not be empty"),
    ],
)
@respx.mock
async def test_create_site_from_platform_validates_before_http(
    platform: str, url: str, needle: str
) -> None:
    fake = FakeInstance()
    fake.install()
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await imports_service.create_site_from_platform(client, "site-x", platform, url)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert needle in excinfo.value.message
    assert fake.platform_bodies == []
    assert fake.create_bodies == []


def _platform_error(message: str) -> httpx.Response:
    return httpx.Response(
        400, json={"status": 400, "data": {"error": message, "items": [], "filename": None}}
    )


@respx.mock
async def test_create_site_from_platform_rewrites_the_ssrf_hint() -> None:
    fake = FakeInstance()
    fake.install()
    respx.post(url__regex=PLATFORM_RE).mock(
        return_value=_platform_error("Blocked by SSRF guard: private address")
    )
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await imports_service.create_site_from_platform(
                client, "site-x", "html", "http://10.0.0.5/page"
            )
    err = excinfo.value
    assert err.code is ErrorCode.INVALID_ARGUMENT
    assert "SSRF" in err.message
    assert err.hint is not None and "create_site_from_document" in err.hint
    assert fake.create_bodies == []


@respx.mock
async def test_create_site_from_platform_passes_other_errors_through() -> None:
    fake = FakeInstance()
    fake.install()
    respx.post(url__regex=PLATFORM_RE).mock(return_value=_platform_error("Unsupported structure"))
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await imports_service.create_site_from_platform(
                client, "site-x", "gitbook", "https://example.org/book"
            )
    err = excinfo.value
    assert err.code is ErrorCode.INVALID_ARGUMENT
    assert "Unsupported structure" in err.message
    assert err.hint is None or "create_site_from_document" not in err.hint
    assert fake.create_bodies == []
