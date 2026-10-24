"""Unit tests for the settings service with respx (PLAN Phase 6 test list).

Covers the exact wire bodies each service function sends (scoped-manifest dash keys, the
SHORT seo/author wrappers, the appearance theme block with normalized variables, region
arrays, editor audience, allowedBlocks null-vs-list, MERGED platform features, alternate
formats), the pre-validations that fire before any HTTP (tags UNSUPPORTED, unknown region /
audience / feature key / format, at-least-one-field), home_page id-or-slug resolution
through find_page, dashed block tags checked against custom-elements, the theme registry
validation with its hidden warning, the element-reset warning, the siteManifest lockout
warning, and the 403 feature gate -> FEATURE_DISABLED mapping.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services import settings as settings_service

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
SYSTEM_THEMES_URL = f"{BASE}/system/api/v1/themes"
SITE_JSON_URL = f"{BASE}/_sites/demo/site.json"
API = f"{BASE}/_sites/demo/x/api/v1"
SITE_URL = f"{API}/site"
APPEARANCE_URL = f"{SITE_URL}/appearance"
SEO_URL = f"{SITE_URL}/seo"
EDITOR_URL = f"{SITE_URL}/editor"
BLOCKS_URL = f"{SITE_URL}/blocks"
PLATFORM_URL = f"{SITE_URL}/platform"
ALTFORMATS_URL = f"{SITE_URL}/updateAlternativeFormats"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

MANIFEST = {
    "id": "site-1",
    "title": "Demo",
    "description": "",
    "license": "by-sa",
    "metadata": {
        "site": {
            "name": "demo",
            "homePageId": "item-1",
            "settings": {"lang": "en", "pathauto": True},
        },
        "theme": {"element": "clean-one", "variables": {}},
        "platform": {"audience": "novice", "features": {"addPage": True, "deletePage": True}},
    },
    "items": [{"id": "item-1", "title": "Home", "slug": "home"}],
}

SYSTEM_THEMES = [
    {"machineName": "clean-one", "element": "clean-one"},
    {"machineName": "learn-two-theme", "element": "learn-two-theme"},
    {"machineName": "hidden-theme", "element": "hidden-theme", "hidden": True},
]


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass", **kwargs)  # type: ignore[arg-type]


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "jwt": "jwt-1"})
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def envelope(data: object) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "data": data})


def mock_manifest_get() -> respx.Route:
    # site.json is RAW JSON (no {status, data} envelope)
    return respx.get(SITE_JSON_URL).mock(return_value=httpx.Response(200, json=MANIFEST))


def sent(route: respx.Route) -> dict:
    return json.loads(route.calls.last.request.content)


# --- update_site_info -------------------------------------------------------------------------


@respx.mock
async def test_update_site_info_splits_routes_and_resolves_home_page() -> None:
    mock_auth()
    mock_manifest_get()
    seo_route = respx.patch(SEO_URL).mock(return_value=envelope(MANIFEST))
    item_route = respx.get(f"{API}/items/welcome").mock(
        return_value=envelope({"id": "item-9", "title": "Welcome", "slug": "welcome"})
    )
    site_route = respx.patch(SITE_URL).mock(return_value=envelope(MANIFEST))
    async with HaxcmsClient(make_settings()) as client:
        settings = await settings_service.update_site_info(
            client, "demo", title="New Title", description="Desc", home_page="welcome"
        )
    assert sent(seo_route) == {"site": {"name": "demo"}, "seo": {"description": "Desc"}}
    assert item_route.call_count == 1  # slug pre-resolved to an item id
    assert sent(site_route) == {
        "site": {"name": "demo"},
        "manifest": {
            "site": {"manifest-title": "New Title", "manifest-metadata-site-homePageId": "item-9"}
        },
    }
    assert settings.name == "demo"
    assert settings.title == "Demo"  # parsed from the (mocked, unchanged) site.json


@respx.mock
async def test_update_site_info_empty_home_page_clears() -> None:
    mock_auth()
    mock_manifest_get()
    item_route = respx.get(f"{API}/items/welcome")
    site_route = respx.patch(SITE_URL).mock(return_value=envelope(MANIFEST))
    async with HaxcmsClient(make_settings()) as client:
        await settings_service.update_site_info(client, "demo", home_page="")
    assert item_route.call_count == 0  # no resolution for the clear signal
    assert sent(site_route)["manifest"]["site"] == {"manifest-metadata-site-homePageId": ""}


async def test_update_site_info_tags_unsupported_fail_fast() -> None:
    # tags raise UNSUPPORTED even alongside writable fields, BEFORE any request
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await settings_service.update_site_info(
            None,
            "demo",
            tags=["x"],
            title="T",  # type: ignore[arg-type]
        )
    error = excinfo.value
    assert error.code is ErrorCode.UNSUPPORTED
    assert "tags" in error.message
    assert "site.json" in (error.hint or "")


async def test_update_site_info_requires_a_field() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await settings_service.update_site_info(None, "demo")  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "at least one" in excinfo.value.message


# --- update_author_info ------------------------------------------------------------------------


@respx.mock
async def test_update_author_info_payload() -> None:
    mock_auth()
    mock_manifest_get()
    route = respx.patch(SEO_URL).mock(return_value=envelope(MANIFEST))
    async with HaxcmsClient(make_settings()) as client:
        await settings_service.update_author_info(
            client, "demo", license="by-nc", name="Author", social_link="https://s.invalid"
        )
    assert sent(route) == {
        "site": {"name": "demo"},
        "author": {"license": "by-nc", "name": "Author", "socialLink": "https://s.invalid"},
    }


async def test_update_author_info_requires_a_field() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await settings_service.update_author_info(None, "demo")  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


# --- set_site_theme ------------------------------------------------------------------------------


@respx.mock
async def test_set_site_theme_validates_and_normalizes() -> None:
    mock_auth()
    mock_manifest_get()
    respx.get(SYSTEM_THEMES_URL).mock(return_value=envelope(SYSTEM_THEMES))
    route = respx.patch(APPEARANCE_URL).mock(
        return_value=envelope({"saved": True, "appearance": {"theme": True}})
    )
    async with HaxcmsClient(make_settings()) as client:
        settings = await settings_service.set_site_theme(
            client,
            "demo",
            "learn-two-theme",
            palette=" Learn ",
            accent_color="--simple-colors-default-theme-DEEP-PURPLE-7",
            icon="account",
        )
    assert sent(route) == {
        "site": {"name": "demo"},
        "manifest": {
            "theme": {
                "manifest-metadata-theme-element": "learn-two-theme",
                "manifest-metadata-theme-variables-palette": "learn",
                "manifest-metadata-theme-variables-cssVariable": "deep-purple",
                "manifest-metadata-theme-variables-icon": "account",
            }
        },
    }
    # the element-reset warning is always attached on a theme switch
    assert settings.warnings is not None
    assert any("registry defaults" in warning for warning in settings.warnings)


@respx.mock
async def test_set_site_theme_unknown_rejected() -> None:
    mock_auth()
    respx.get(SYSTEM_THEMES_URL).mock(return_value=envelope(SYSTEM_THEMES))
    route = respx.patch(APPEARANCE_URL)
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await settings_service.set_site_theme(client, "demo", "no-such-theme")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "list_themes" in (excinfo.value.hint or "")
    assert route.call_count == 0


@respx.mock
async def test_set_site_theme_hidden_warns() -> None:
    mock_auth()
    mock_manifest_get()
    respx.get(SYSTEM_THEMES_URL).mock(return_value=envelope(SYSTEM_THEMES))
    respx.patch(APPEARANCE_URL).mock(
        return_value=envelope({"saved": True, "appearance": {"theme": True}})
    )
    async with HaxcmsClient(make_settings()) as client:
        settings = await settings_service.set_site_theme(client, "demo", "hidden-theme")
    assert settings.warnings is not None
    assert any("hidden" in warning for warning in settings.warnings)


# --- set_theme_regions ----------------------------------------------------------------------------


@respx.mock
async def test_set_theme_regions_resolves_pages() -> None:
    mock_auth()
    mock_manifest_get()
    respx.get(f"{API}/items/welcome").mock(
        return_value=envelope({"id": "item-9", "title": "Welcome", "slug": "welcome"})
    )
    respx.get(f"{API}/items/item-1").mock(
        return_value=envelope({"id": "item-1", "title": "Home", "slug": "home"})
    )
    route = respx.patch(APPEARANCE_URL).mock(
        return_value=envelope({"saved": True, "appearance": {"theme": True}})
    )
    async with HaxcmsClient(make_settings()) as client:
        await settings_service.set_theme_regions(
            client, "demo", "sidebarFirst", ["welcome", "item-1"]
        )
    assert sent(route) == {
        "site": {"name": "demo"},
        "manifest": {
            "theme": {"manifest-metadata-theme-regions-sidebarFirst": ["item-9", "item-1"]}
        },
    }


async def test_set_theme_regions_validates_region_before_http() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await settings_service.set_theme_regions(None, "demo", "sidebar-first", [])  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "sidebarFirst" in (excinfo.value.hint or "")


# --- update_seo_settings -------------------------------------------------------------------------


@respx.mock
async def test_update_seo_settings_payload() -> None:
    mock_auth()
    mock_manifest_get()
    route = respx.patch(SEO_URL).mock(return_value=envelope(MANIFEST))
    async with HaxcmsClient(make_settings()) as client:
        await settings_service.update_seo_settings(
            client, "demo", lang="es", ga_id="UA-9", pathauto=False, publish_pages_on=True
        )
    assert sent(route) == {
        "site": {"name": "demo"},
        "seo": {"lang": "es", "gaID": "UA-9", "pathauto": False, "publishPagesOn": True},
    }


async def test_update_seo_settings_requires_a_field() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await settings_service.update_seo_settings(None, "demo")  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


# --- set_editor_audience -------------------------------------------------------------------------


@respx.mock
async def test_set_editor_audience_normalizes() -> None:
    mock_auth()
    mock_manifest_get()
    route = respx.patch(EDITOR_URL).mock(return_value=envelope(MANIFEST))
    async with HaxcmsClient(make_settings()) as client:
        await settings_service.set_editor_audience(client, "demo", " EXPERT ")
    assert sent(route) == {"site": {"name": "demo"}, "platform": {"audience": "expert"}}


async def test_set_editor_audience_rejects_invalid() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await settings_service.set_editor_audience(None, "demo", "beginner")  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "novice, expert" in (excinfo.value.hint or "")


# --- set_allowed_blocks --------------------------------------------------------------------------


@respx.mock
async def test_set_allowed_blocks_dedups_and_validates_dashed_tags() -> None:
    mock_auth()
    mock_manifest_get()
    respx.get(f"{API}/custom-elements/a11y-gif-player").mock(
        return_value=envelope({"tag": "a11y-gif-player"})
    )
    route = respx.patch(BLOCKS_URL).mock(return_value=envelope(MANIFEST))
    async with HaxcmsClient(make_settings()) as client:
        await settings_service.set_allowed_blocks(
            client, "demo", ["image", "a11y-gif-player", "image"]
        )
    assert sent(route) == {
        "site": {"name": "demo"},
        "platform": {"allowedBlocks": ["image", "a11y-gif-player"]},
    }


@respx.mock
async def test_set_allowed_blocks_unknown_tag_named_in_error() -> None:
    mock_auth()
    respx.get(f"{API}/custom-elements/not-a-block").mock(
        return_value=httpx.Response(404, json={"status": 404, "data": {"message": "Not found"}})
    )
    route = respx.patch(BLOCKS_URL)
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await settings_service.set_allowed_blocks(client, "demo", ["image", "not-a-block"])
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "not-a-block" in error.message  # the server's own 400 is generic
    assert route.call_count == 0


@respx.mock
async def test_set_allowed_blocks_null_unrestricted() -> None:
    mock_auth()
    mock_manifest_get()
    route = respx.patch(BLOCKS_URL).mock(return_value=envelope(MANIFEST))
    async with HaxcmsClient(make_settings()) as client:
        await settings_service.set_allowed_blocks(client, "demo", None)
    assert sent(route) == {"site": {"name": "demo"}, "platform": {"allowedBlocks": None}}


# --- set_platform_features -----------------------------------------------------------------------


@respx.mock
async def test_set_platform_features_merges_over_current() -> None:
    mock_auth()
    mock_manifest_get()  # current features: {"addPage": true, "deletePage": true}
    route = respx.patch(PLATFORM_URL).mock(return_value=envelope(MANIFEST))
    async with HaxcmsClient(make_settings()) as client:
        settings = await settings_service.set_platform_features(
            client, "demo", {"deletePage": False}
        )
    # REPLACE semantics upstream: the FULL merged set must be sent
    assert sent(route) == {
        "site": {"name": "demo"},
        "platform": {"features": {"addPage": True, "deletePage": False}},
    }
    assert settings.warnings is None


@respx.mock
async def test_set_platform_features_site_manifest_lockout_warning() -> None:
    mock_auth()
    mock_manifest_get()
    respx.patch(PLATFORM_URL).mock(return_value=envelope(MANIFEST))
    async with HaxcmsClient(make_settings()) as client:
        settings = await settings_service.set_platform_features(
            client, "demo", {"siteManifest": False}
        )
    assert settings.warnings is not None
    assert any("cannot be re-enabled" in warning for warning in settings.warnings)


async def test_set_platform_features_rejections_fire_before_http() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await settings_service.set_platform_features(None, "demo", {})  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await settings_service.set_platform_features(None, "demo", {"manifest": True})  # type: ignore[arg-type]
    assert "unknown platform feature" in excinfo.value.message


@respx.mock
async def test_feature_gate_maps_to_feature_disabled() -> None:
    mock_auth()
    mock_manifest_get()
    respx.patch(PLATFORM_URL).mock(
        return_value=httpx.Response(
            403,
            json={
                "status": 403,
                "data": {"message": "Platform settings are disabled for this site"},
            },
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await settings_service.set_platform_features(client, "demo", {"addPage": False})
    assert excinfo.value.code is ErrorCode.FEATURE_DISABLED


# --- regenerate_alternate_formats ----------------------------------------------------------------


@respx.mock
async def test_regenerate_alternate_formats_payloads() -> None:
    mock_auth()
    route = respx.post(ALTFORMATS_URL).mock(
        return_value=envelope({"updated": True, "site": {"name": "demo"}, "format": None})
    )
    async with HaxcmsClient(make_settings()) as client:
        result = await settings_service.regenerate_alternate_formats(client, "demo")
        assert sent(route) == {"site": {"name": "demo"}}  # no format key -> all formats
        assert result["updated"] is True
        await settings_service.regenerate_alternate_formats(client, "demo", format=" RSS ")
        assert sent(route) == {"site": {"name": "demo"}, "format": "rss"}


async def test_regenerate_alternate_formats_rejects_unknown() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await settings_service.regenerate_alternate_formats(None, "demo", format="atom")  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "service-worker" in (excinfo.value.hint or "")


# --- configure_site_git --------------------------------------------------------------------------


async def test_configure_site_git_always_unsupported() -> None:
    # raises before any network use (client=None): 26.8.1 has NO git-settings route
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await settings_service.configure_site_git(
            None,  # type: ignore[arg-type]
            "demo",
            branch="gh-pages",
            auto_push=True,
            remote_url="git@example.invalid:org/demo.git",
            vendor="github",
        )
    error = excinfo.value
    assert error.code is ErrorCode.UNSUPPORTED
    assert "git publishing settings" in error.message
    assert "metadata.site.git" in (error.hint or "")
    assert "get_site_settings" in (error.hint or "")


# --- get_site_settings ---------------------------------------------------------------------------


@respx.mock
async def test_get_site_settings_parses_manifest() -> None:
    mock_auth()
    mock_manifest_get()
    async with HaxcmsClient(make_settings()) as client:
        settings = await settings_service.get_site_settings(client, "demo")
    assert settings.name == "demo"
    assert settings.home_page_id == "item-1"
    assert settings.theme is not None and settings.theme.element == "clean-one"
    assert settings.platform is not None and settings.platform.audience == "novice"
    assert settings.seo is not None and settings.seo.lang == "en"
