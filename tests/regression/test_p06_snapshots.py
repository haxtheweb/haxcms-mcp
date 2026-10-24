"""Phase 6 regression snapshots (PLAN §6.4: settings payload goldens).

`settings_payloads` freezes the wire contract of the Phase 6 client helpers AND the pure
payload builders feeding them: the scoped-details PATCH-site body (the `manifest` object
with the admin-UI dash keys — a flat body falls through to the unreachable form path and
403s), the appearance theme block (ONLY `manifest-metadata-theme-*` keys), the SHORT
seo/author wrapper keys (`gaID`, `publishPagesOn`, `socialLink`...), the editor audience,
allowedBlocks list-vs-null, the full merged platform feature set (the route REPLACES),
and the alternate-formats body with/without the `format` key. Requests are captured under
respx (deterministic, no network); auth headers are never snapshotted.

Update deliberately with `pytest --snapshot-update`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient, site_api
from haxcms_mcp.config import Settings
from haxcms_mcp.services.settings import (
    build_appearance_theme,
    build_author_fields,
    build_scoped_manifest_payload,
    build_seo_fields,
)
from tests.harness.snapshots import assert_or_update_snapshot

pytestmark = pytest.mark.regression

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
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


def make_settings() -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass")


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "jwt": "jwt-1"})
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def envelope(data: object) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "data": data})


def capture(route: respx.Route, index: int = -1) -> dict[str, Any]:
    request = route.calls[index].request
    return {
        "method": request.method,
        "path": request.url.path,
        "body": json.loads(request.content),
    }


@respx.mock
async def test_settings_payloads_golden(request: pytest.FixtureRequest) -> None:
    update = bool(request.config.getoption("--snapshot-update", default=False))
    mock_auth()
    manifest_route = respx.get(SITE_JSON_URL).mock(return_value=httpx.Response(200, json={}))
    site_route = respx.patch(SITE_URL).mock(return_value=envelope({}))
    appearance_route = respx.patch(APPEARANCE_URL).mock(return_value=envelope({}))
    seo_route = respx.patch(SEO_URL).mock(return_value=envelope({}))
    editor_route = respx.patch(EDITOR_URL).mock(return_value=envelope({}))
    blocks_route = respx.patch(BLOCKS_URL).mock(return_value=envelope({}))
    platform_route = respx.patch(PLATFORM_URL).mock(return_value=envelope({}))
    altformats_route = respx.post(ALTFORMATS_URL).mock(return_value=envelope({}))

    async with HaxcmsClient(make_settings()) as client:
        await site_api.fetch_site_manifest(client, "demo")
        # the scoped-details body: the builder's output minus the site wrapper the helper adds
        scoped = build_scoped_manifest_payload("demo", title="New Title", home_page_id="item-9")
        await site_api.update_manifest(client, "demo", {"manifest": scoped["manifest"]})
        await site_api.update_appearance(
            client,
            "demo",
            build_appearance_theme(
                element="learn-two-theme",
                palette="learn",
                accent_color="deep-purple",
                icon="account",
                banner_image="files/banner.png",
                banner_alt="Banner",
                banner_link="https://example.invalid",
                region="sidebarFirst",
                region_page_ids=["item-2", "item-3"],
            ),
        )
        await site_api.update_seo(
            client,
            "demo",
            seo=build_seo_fields(
                description="An alpha course.",
                domain="example.invalid",
                logo="files/logo.png",
                lang="es",
                ga_id="G-TEST",
                private=False,
                canonical=True,
                pathauto=True,
                publish_pages_on=False,
            ),
            author=build_author_fields(
                license="by-nc",
                name="Ada Lovelace",
                email="ada@example.invalid",
                image="files/ada.png",
                phone="+44",
                location="London",
                website="https://example.invalid",
                social_link="https://social.invalid/ada",
            ),
        )
        await site_api.update_editor(client, "demo", "expert")
        await site_api.update_allowed_blocks(client, "demo", ["a11y-gif-player", "image"])
        await site_api.update_allowed_blocks(client, "demo", None)
        await site_api.update_platform(client, "demo", {"addPage": True, "deletePage": False})
        await site_api.update_alternative_formats(client, "demo", "rss")
        await site_api.update_alternative_formats(client, "demo")

    golden = {
        "fetch_site_manifest": {
            "method": manifest_route.calls.last.request.method,
            "path": manifest_route.calls.last.request.url.path,
        },
        "update_manifest_scoped_details": capture(site_route),
        "update_appearance_theme": capture(appearance_route),
        "update_seo_and_author": capture(seo_route),
        "update_editor": capture(editor_route),
        "update_allowed_blocks_list": capture(blocks_route, 0),
        "update_allowed_blocks_null": capture(blocks_route, 1),
        "update_platform_features": capture(platform_route),
        "update_alternative_formats_one": capture(altformats_route, 0),
        "update_alternative_formats_all": capture(altformats_route, 1),
    }
    assert_or_update_snapshot("settings_payloads", golden, update=update)
