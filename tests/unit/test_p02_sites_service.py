"""Unit tests for the sites service with respx (PLAN Phase 2 T2.6).

Response bodies mirror the Phase 2 probe of the live 26.8.1 instance (see PROGRESS.md
verified facts): create echoes a JSONOutlineSchemaItem with `metadata.site.name`, clone returns
`{detail, name}`, archive returns `{name, archivedName, detail}`, system themes/skeletons are
lists, and the site summary/themes reads are public.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services import sites as sites_service

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
SITES_URL = f"{BASE}/system/api/v1/sites"
THEMES_URL = f"{BASE}/system/api/v1/themes"
SKELETONS_URL = f"{BASE}/system/api/v1/skeletons"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

THEME_RECORDS = [
    {
        "machineName": "clean-one",
        "machine-name": "clean-one",
        "name": "Clean One",
        "element": "clean-one",
        "description": "Start with a blank site using the Clean One",
        "category": ["Course"],
        "hidden": False,
        "terrible": False,
        "priority": -2,
        "enabled": True,
        "scope": "registry",
    },
    {
        "machineName": "hidden-theme",
        "machine-name": "hidden-theme",
        "name": "Hidden",
        "element": "hidden-theme",
        "hidden": True,
        "terrible": False,
        "priority": 0,
        "enabled": True,
        "scope": "registry",
    },
]

SKELETON_RECORDS = [
    {
        "machineName": "online-course-clean-one",
        "machine-name": "online-course-clean-one",
        "title": "Online Course",
        "description": "Clean One themed online course skeleton",
        "category": ["Course"],
        "enabled": True,
        "priority": -2,
        "image": "thumb.jpg",
        "attributes": [],
        "scope": "core",
        "demo-url": "http://demo",
        "skeleton-url": "/system/api/v1/skeletons/online-course-clean-one",
    }
]

SKELETON_DETAIL = {
    "meta": {
        "name": "online-course-clean-one",
        "description": "Clean One themed online course skeleton",
        "version": "1.0.0",
        "type": "skeleton",
        "priority": -2,
        "useCaseTitle": "Online Course",
        "category": ["Course"],
        "tags": ["online", "lesson", "syllabus"],
        "attributes": [],
    },
    "site": {"name": "online-course-clean-one", "description": "A course", "theme": "clean-one"},
    "build": {
        "type": "skeleton",
        "structure": "from-skeleton",
        "items": [{"id": "item-1", "title": "Syllabus", "slug": "syllabus"}],
    },
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


def info_body(name: str, page_count: int = 1) -> dict[str, Any]:
    return {
        "id": "site-id",
        "name": name,
        "title": name,
        "description": "",
        "location": f"//_sites/{name}/",
        "metadata": {
            "pageCount": page_count,
            "created": "2026-01-01T00:00:00.000Z",
            "updated": "2026-01-02T00:00:00.000Z",
        },
        "links": {"self": f"/system/api/v1/sites/{name}", "siteApi": f"//_sites/{name}/x/api"},
    }


def summary_body(name: str, items: int = 1) -> dict[str, Any]:
    return {
        "id": "site-id",
        "name": name,
        "title": name,
        "description": "",
        "language": "en-US",
        "basePath": f"/_sites/{name}/",
        "theme": "clean-one",
        "updated": "2026-01-02T00:00:00.000Z",
        "counts": {"items": items, "publishedItems": items, "tags": 0, "regions": 0, "files": 0},
        "links": {"self": f"/_sites/{name}/x/api/v1/site"},
    }


def site_name_from_path(path: str) -> str:
    return path.split("/_sites/", 1)[1].split("/", 1)[0]


def _info_effect(request: httpx.Request) -> httpx.Response:
    name = request.url.path.rsplit("/", 1)[-1]
    return httpx.Response(200, json={"status": 200, "data": info_body(name)})


def _summary_effect(request: httpx.Request) -> httpx.Response:
    name = site_name_from_path(request.url.path)
    return httpx.Response(200, json={"status": 200, "data": summary_body(name)})


def mock_site_reads() -> None:
    respx.get(url__regex=r".*/system/api/v1/sites/[^/]+$").mock(side_effect=_info_effect)
    respx.get(url__regex=r".*/x/api/v1/site$").mock(side_effect=_summary_effect)


def mock_themes() -> respx.Route:
    return respx.get(THEMES_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": THEME_RECORDS})
    )


def create_effect(rename_to: str | None = None) -> Any:
    """POST sites echo: the created item, with metadata.site.name from the payload (or forced)."""

    def effect(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requested = body["site"]["name"]
        name = rename_to or requested
        return httpx.Response(
            200,
            json={
                "status": 200,
                "data": {
                    "id": "new-id",
                    "title": requested,
                    "location": f"/_sites/{name}/index.html",
                    "slug": f"/_sites/{name}/index.html",
                    "metadata": {"site": {"name": name, "license": "by-sa"}},
                },
            },
        )

    return effect


@respx.mock
async def test_create_site_happy_path() -> None:
    mock_auth()
    mock_themes()
    create_route = respx.post(SITES_URL).mock(side_effect=create_effect())
    mock_site_reads()

    async with HaxcmsClient(make_settings()) as client:
        detail = await sites_service.create_site(client, "demo")

    assert detail.name == "demo"
    assert detail.title == "demo"
    assert detail.page_count == 1
    assert detail.counts is not None and detail.counts.items == 1
    assert detail.theme == "clean-one"
    assert detail.warnings is None

    sent = json.loads(create_route.calls.last.request.content)
    assert sent["site"]["name"] == "demo"
    assert sent["site"]["license"] == "by-sa"
    assert sent["build"]["items"][0]["title"] == "Home"
    assert "skeletonMachineName" not in sent["build"]


@respx.mock
async def test_create_site_unknown_theme_rejected_before_any_write() -> None:
    mock_auth()
    mock_themes()
    create_route = respx.post(SITES_URL).mock(side_effect=create_effect())

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await sites_service.create_site(client, "demo", theme="no-such-theme")

    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "unknown theme" in error.message
    assert "list_themes" in (error.hint or "")
    assert create_route.call_count == 0  # validated BEFORE the POST: no phantom site


@respx.mock
async def test_create_site_hidden_theme_allowed_with_warning() -> None:
    mock_auth()
    mock_themes()
    respx.post(SITES_URL).mock(side_effect=create_effect())
    mock_site_reads()

    async with HaxcmsClient(make_settings()) as client:
        detail = await sites_service.create_site(client, "demo", theme="hidden-theme")

    assert detail.name == "demo"
    assert detail.warnings and any("hidden" in warning for warning in detail.warnings)


@respx.mock
async def test_create_site_duplicate_name_reports_server_choice() -> None:
    mock_auth()
    mock_themes()
    respx.post(SITES_URL).mock(side_effect=create_effect(rename_to="demo-1"))
    mock_site_reads()

    async with HaxcmsClient(make_settings()) as client:
        detail = await sites_service.create_site(client, "demo")

    assert detail.name == "demo-1"
    assert detail.warnings and any("demo-1" in warning for warning in detail.warnings)
    assert detail.warnings and any("already taken" in warning for warning in detail.warnings)


@respx.mock
async def test_create_site_passes_title_but_warns_it_is_ignored() -> None:
    mock_auth()
    mock_themes()
    create_route = respx.post(SITES_URL).mock(side_effect=create_effect())
    mock_site_reads()

    async with HaxcmsClient(make_settings()) as client:
        detail = await sites_service.create_site(client, "demo", title="Demo Course")

    sent = json.loads(create_route.calls.last.request.content)
    assert sent["site"]["title"] == "Demo Course"  # sent verbatim (upstream ignores it)
    assert detail.warnings and any("ignores site.title" in w for w in detail.warnings)


@respx.mock
async def test_create_site_title_equal_to_name_does_not_warn() -> None:
    mock_auth()
    mock_themes()
    respx.post(SITES_URL).mock(side_effect=create_effect())
    mock_site_reads()

    async with HaxcmsClient(make_settings()) as client:
        detail = await sites_service.create_site(client, "demo", title="demo")

    assert detail.warnings is None


@respx.mock
async def test_create_site_with_skeleton_skips_theme_validation() -> None:
    mock_auth()
    themes_route = mock_themes()
    create_route = respx.post(SITES_URL).mock(side_effect=create_effect())
    mock_site_reads()

    async with HaxcmsClient(make_settings()) as client:
        detail = await sites_service.create_site(client, "demo", skeleton="online-course-clean-one")

    sent = json.loads(create_route.calls.last.request.content)
    assert sent["build"]["skeletonMachineName"] == "online-course-clean-one"
    assert "items" not in sent["build"]
    assert themes_route.call_count == 0  # the skeleton's theme wins; no registry lookup
    assert detail.name == "demo"


@respx.mock
async def test_create_site_from_skeleton_defaults_name_to_machine_name() -> None:
    mock_auth()
    create_route = respx.post(SITES_URL).mock(side_effect=create_effect())
    mock_site_reads()

    async with HaxcmsClient(make_settings()) as client:
        detail = await sites_service.create_site_from_skeleton(client, "online-course-clean-one")

    sent = json.loads(create_route.calls.last.request.content)
    assert sent["site"]["name"] == "online-course-clean-one"
    assert detail.name == "online-course-clean-one"


@respx.mock
async def test_create_site_from_skeleton_requires_a_name() -> None:
    mock_auth()
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await sites_service.create_site_from_skeleton(client, "  ")
        assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


@respx.mock
async def test_clone_site_returns_the_new_name_and_record() -> None:
    mock_auth()
    respx.post(f"{SITES_URL}/demo/clone").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": {"detail": "/_sites/demo-2", "name": "demo-2"},
            },
        )
    )
    mock_site_reads()

    async with HaxcmsClient(make_settings()) as client:
        result = await sites_service.clone_site(client, "demo")

    assert result["name"] == "demo-2"
    site = result["site"]
    assert isinstance(site, dict)
    assert site["name"] == "demo-2"
    assert site["page_count"] == 1


@respx.mock
async def test_clone_site_falls_back_to_parsing_detail() -> None:
    mock_auth()
    respx.post(f"{SITES_URL}/demo/clone").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"detail": "/_sites/demo-3"}})
    )
    mock_site_reads()

    async with HaxcmsClient(make_settings()) as client:
        result = await sites_service.clone_site(client, "demo")

    assert result["name"] == "demo-3"


@respx.mock
async def test_clone_site_without_a_name_is_an_upstream_error() -> None:
    mock_auth()
    respx.post(f"{SITES_URL}/demo/clone").mock(
        return_value=httpx.Response(200, json={"status": 200})
    )

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await sites_service.clone_site(client, "demo")
        assert excinfo.value.code is ErrorCode.UPSTREAM_ERROR


@respx.mock
async def test_archive_site_maps_the_response() -> None:
    mock_auth()
    archive_route = respx.post(f"{SITES_URL}/demo/archive").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": {
                    "name": "demo",
                    "archivedName": "demo",
                    "detail": "Site archived",
                },
            },
        )
    )

    async with HaxcmsClient(make_settings()) as client:
        result = await sites_service.archive_site(client, "demo")

    assert result == {"name": "demo", "archived_name": "demo", "detail": "Site archived"}
    sent = json.loads(archive_route.calls.last.request.content)
    assert sent == {"site": {"name": "demo"}}


@respx.mock
async def test_get_site_merges_info_and_summary() -> None:
    mock_auth()
    mock_site_reads()

    async with HaxcmsClient(make_settings()) as client:
        detail = await sites_service.get_site(client, "demo")

    assert detail.name == "demo"
    assert detail.page_count == 1
    assert detail.counts is not None
    assert detail.counts.items == 1
    assert detail.counts.published_items == 1
    assert detail.theme == "clean-one"
    assert detail.language == "en-US"
    assert detail.created == "2026-01-01T00:00:00.000Z"
    assert detail.updated == "2026-01-02T00:00:00.000Z"
    assert detail.links is not None and detail.links["self"] == "/system/api/v1/sites/demo"
    assert detail.warnings is None


@respx.mock
async def test_get_site_survives_a_summary_failure_with_a_warning() -> None:
    mock_auth()
    respx.get(url__regex=r".*/system/api/v1/sites/[^/]+$").mock(side_effect=_info_effect)
    respx.get(url__regex=r".*/x/api/v1/site$").mock(
        return_value=httpx.Response(
            404, json={"status": 404, "data": {"message": "Site not found"}}
        )
    )

    async with HaxcmsClient(make_settings()) as client:
        detail = await sites_service.get_site(client, "demo")

    assert detail.name == "demo"
    assert detail.page_count == 1
    assert detail.counts is None
    assert detail.warnings and "summary unavailable" in detail.warnings[0]


@respx.mock
async def test_get_site_unknown_raises_not_found() -> None:
    mock_auth()
    respx.get(url__regex=r".*/system/api/v1/sites/[^/]+$").mock(
        return_value=httpx.Response(
            404, json={"status": 404, "data": {"message": "Site not found"}}
        )
    )

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await sites_service.get_site(client, "nope")
        assert excinfo.value.code is ErrorCode.NOT_FOUND


@respx.mock
async def test_list_sites_strips_heavy_extras_but_keeps_scalars() -> None:
    mock_auth()
    heavy_item = {
        "id": "site-id",
        "title": "demo",
        "author": "me",
        "description": "",
        "license": "by-sa",
        "location": "/_sites/demo/index.html",
        "slug": "/_sites/demo/index.html",
        "metadata": {
            "pageCount": 3,
            "site": {"name": "demo", "license": "by-sa"},
            "theme": {"element": "clean-one", "variables": {"icon": "icons:x"}},
        },
        "theme": {"element": "clean-one", "path": "@haxtheweb/clean-one/clean-one.js"},
        "build": {"type": "skeleton", "structure": "from-skeleton", "items": [{"id": "x"}]},
        "node": {"fields": {}},
        "platform": {"audience": "expert", "features": {}, "allowedBlocks": []},
    }
    respx.get(SITES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": {"id": "123", "title": "My sites", "author": "me", "items": [heavy_item]},
            },
        )
    )

    async with HaxcmsClient(make_settings()) as client:
        entries = await sites_service.list_sites(client)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.name == "demo"
    assert entry.page_count == 3
    assert entry.author == "me"  # scalar extras survive
    assert entry.license == "by-sa"
    extras = entry.model_extra or {}
    for heavy in ("theme", "build", "node", "platform", "metadata"):
        assert heavy not in extras


@respx.mock
async def test_list_themes_maps_records() -> None:
    mock_auth()
    mock_themes()

    async with HaxcmsClient(make_settings()) as client:
        themes = await sites_service.list_themes(client)

    by_machine = {theme.machine_name: theme for theme in themes}
    assert by_machine["clean-one"].name == "Clean One"
    assert by_machine["clean-one"].category == ["Course"]
    assert by_machine["clean-one"].hidden is False
    assert by_machine["hidden-theme"].hidden is True


@respx.mock
async def test_list_skeletons_maps_records() -> None:
    mock_auth()
    respx.get(SKELETONS_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": SKELETON_RECORDS})
    )

    async with HaxcmsClient(make_settings()) as client:
        skeletons = await sites_service.list_skeletons(client)

    assert len(skeletons) == 1
    entry = skeletons[0]
    assert entry.machine_name == "online-course-clean-one"
    assert entry.title == "Online Course"
    assert entry.category == ["Course"]
    assert entry.enabled is True


@respx.mock
async def test_get_skeleton_wraps_the_detail() -> None:
    mock_auth()
    respx.get(f"{SKELETONS_URL}/online-course-clean-one").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": SKELETON_DETAIL})
    )

    async with HaxcmsClient(make_settings()) as client:
        skeleton = await sites_service.get_skeleton(client, "online-course-clean-one")

    assert skeleton.meta.machine_name == "online-course-clean-one"
    assert skeleton.meta.title == "Online Course"  # falls back to useCaseTitle
    assert skeleton.meta.tags == ["online", "lesson", "syllabus"]
    assert skeleton.site["theme"] == "clean-one"
    assert skeleton.build["items"][0]["title"] == "Syllabus"
